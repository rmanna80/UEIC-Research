"""Trim chiller: second-law-fraction COP with an optional part-load map (Stage 1).

Full-load COP (legacy, unchanged):
    T_evap = T_sup - dt_evap,  T_cond = T_amb + dt_cond                      K
    COP_full = eta_II * T_evap / (T_cond - T_evap), capped at cop_max         [A: Carnot bound; E: eta_II]

Part-load map (DOE-2-style EIR-fPLR quadratic, class F coefficients):
    PLR = Q_ch / Q_ch,design                                                  -
    EIR(PLR) / EIR_full = a + b*PLR + c*PLR**2,  EIR = 1/COP                  -
    COP(PLR) = COP_full / (EIR(PLR)/EIR_full * ... ) with the ratio normalised so that PLR = 1 gives
    COP_full exactly; in DOE-2 the electric input fraction is EIR_ratio(PLR) / PLR of full input
    at PLR, i.e. W = W_full * (a + b*PLR + c*PLR**2) and COP(PLR) = COP_full * PLR / (a + b*PLR + c*PLR**2).
The defaults (a, b, c) = (0, 1, 0) make COP independent of load, which reproduces the legacy plant.
Any other coefficients are a placeholder until a manufacturer's part-load table is used.

Physical checks: COP is positive, never exceeds the Carnot COP for the same temperatures, and the
part-load factor is evaluated only for PLR in (0, 1.2]; beyond 1.2 the map is extrapolation and
is clipped (the chiller is assumed to be sized for the node, so PLR > 1 only in transients).
"""
from __future__ import annotations

import numpy as np


def part_load_factor(plr, cfg):
    """COP multiplier COP(PLR)/COP_full = PLR / (a + b*PLR + c*PLR^2); 1 for the default (0, 1, 0)."""
    a, b, c = float(cfg.chiller_plr_a), float(cfg.chiller_plr_b), float(cfg.chiller_plr_c)
    plr = np.clip(np.asarray(plr, dtype=float), 1e-6, 1.2)
    denom = a + b * plr + c * plr ** 2
    if np.any(denom <= 0):
        raise ValueError("chiller part-load curve gives non-positive input power")
    return plr / denom


def chiller_cop_part_load(T_sup, T_amb, Q_ch, Q_design, cfg):
    """Chiller COP at the given duty, never above the Carnot COP for the same temperatures."""
    from . import carnot_cop, chiller_cop
    cop_full = chiller_cop(T_sup, T_amb, cfg)
    cop = cop_full * part_load_factor(np.asarray(Q_ch, dtype=float) / Q_design, cfg)
    carnot = carnot_cop(T_sup, T_amb, cfg)
    return np.minimum(np.minimum(cop, carnot), cfg.cop_max)
