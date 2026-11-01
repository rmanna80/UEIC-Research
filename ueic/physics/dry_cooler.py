"""Dry cooler (air-cooled fluid cooler) with variable-speed fans: effectiveness-NTU heat transfer
and fan affinity laws (Stage 1; addresses the E012 limitation).

Why. The legacy plant (``ueic.physics.plant``) charges fan power as a fixed fraction of the heat
rejected and lets the dry cooler reach any outlet temperature down to ``T_amb + dt_drycooler``
at the same cost per watt. Warmer water then has no facility-side benefit, which made E012's
warm-water hypotheses impossible to pass. Here fan power depends on how hard the cooler must
work: a small approach (outlet close to ambient) needs high airflow, and fan power rises with
the cube of fan speed.

Model (SI units; temperatures in degC where only differences matter):

  Water capacity rate     C_w = m_dot_w * c_p,w                           W/K
  Air capacity rate       C_a(x) = C_a,d * x                              W/K   (x = fan speed / design)
  Conductance             UA(x) = UA_d * x**n_air                         W/K   [E: air-side dominated]
  NTU, Cr                 NTU = UA / C_min,  Cr = C_min / C_max
  Effectiveness           crossflow, both fluids unmixed (Incropera & DeWitt, eq. 11.32,
                          an approximation [A/E]):
                          eps = 1 - exp[(NTU**0.22 / Cr) * (exp(-Cr * NTU**0.78) - 1)]
  Heat rejected           Q_dc(x) = eps * C_min * (T_w,in - T_amb)        W
  Fan power               P_fan(x) = P_fan,d * x**3                       W     [A: fan affinity law,
                                                                                   fixed system curve]

Design point (class G sizing choice, class F values): the cooler is sized so that at design water
flow, design heat Q_d (the node's full-load heat) and full fan speed, it reaches the legacy
approach ``dt_drycooler`` with the legacy fan power ``fan_ratio * Q_d``. At that one point the
two models agree; elsewhere this one uses less fan power at part load or a larger approach, and
can reach a smaller approach at part load.

Operation: for a required water outlet temperature, the controller of the dry cooler picks the
lowest fan speed in [x_min, 1] that reaches it (bisection; Q_dc is monotonic in x). A bypass keeps
the outlet from undershooting. If full speed cannot reach it, the dry cooler runs flat out and a
trim chiller (``ueic.physics.chiller``) removes the rest. If the water is not warmer than the air,
the dry cooler is off.

Valid range and limits: single-phase water and dry air; no wet-bulb (adiabatic) assist; the UA
scaling ignores the water-side film and fin efficiency changes; the effectiveness correlation is
an approximation (within a few percent of the exact series for typical NTU). Not validated
against a manufacturer's performance table (validation strategy: compare with a published
dry-cooler selection table when one is obtained; until then all parameters are class F).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

AIR_TEMP_RISE_DESIGN_NOTE = "C_a,d = dc_air_ratio * C_w,d"


def crossflow_effectiveness(ntu, cr):
    """Effectiveness of a crossflow exchanger with both fluids unmixed (approximate correlation).

    Limits: cr -> 0 gives 1 - exp(-NTU) (exact for a condensing/evaporating stream or an infinite
    capacity stream); the result is clipped to [0, 1]."""
    ntu = np.maximum(np.asarray(ntu, dtype=float), 0.0)
    cr = np.clip(np.asarray(cr, dtype=float), 0.0, 1.0)
    small = cr < 1e-9
    crs = np.where(small, 1.0, cr)
    with np.errstate(over="ignore", invalid="ignore"):
        eps_cf = 1.0 - np.exp((ntu ** 0.22 / crs) * (np.exp(-crs * ntu ** 0.78) - 1.0))
    eps = np.where(small, 1.0 - np.exp(-ntu), eps_cf)
    return np.clip(np.nan_to_num(eps, nan=0.0), 0.0, 1.0)


def _ntu_for_effectiveness(eps, cr, lo=1e-6, hi=50.0, iters=80):
    """Invert crossflow_effectiveness for NTU (scalar bisection; effectiveness is monotonic in NTU)."""
    if not 0.0 < eps < 1.0:
        raise ValueError(f"design effectiveness must be in (0, 1); got {eps:.4f}")
    if crossflow_effectiveness(hi, cr) < eps:
        raise ValueError(f"design effectiveness {eps:.3f} is not reachable with Cr = {cr:.3f}; "
                         "raise dc_air_ratio or dt_drycooler")
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if crossflow_effectiveness(mid, cr) < eps:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


@dataclass(frozen=True)
class DryCoolerDesign:
    """Design-point sizing derived from the configuration (all W, W/K, K)."""
    Q_d: float          # design heat, W
    C_w_d: float        # design water capacity rate, W/K
    C_a_d: float        # design air capacity rate (full fan speed), W/K
    UA_d: float         # conductance at full fan speed, W/K
    P_fan_d: float      # fan power at full speed, W
    approach_d: float   # design approach (outlet - ambient), K
    n_air: float        # UA exponent on airflow
    x_min: float        # minimum fan speed fraction when running

    @classmethod
    def from_config(cls, cfg) -> "DryCoolerDesign":
        from . import chip_power, mass_flow_per_accel, pump_power   # legacy functions, unchanged
        Q_d = float(cfg.n_accel * chip_power(1.0, cfg.t_leak_ref, 1.0, cfg) + pump_power(1.0, cfg))
        C_w = float(cfg.n_accel * mass_flow_per_accel(1.0, cfg) * cfg.water_cp)
        C_a = float(cfg.dc_air_ratio) * C_w
        approach = float(cfg.dt_drycooler)
        dT_w = Q_d / C_w                                   # water temperature drop at design
        c_min, c_max = min(C_w, C_a), max(C_w, C_a)
        eps_d = Q_d / (c_min * (approach + dT_w))          # T_w,in - T_amb = approach + dT_w
        ntu_d = _ntu_for_effectiveness(eps_d, c_min / c_max)
        return cls(Q_d=Q_d, C_w_d=C_w, C_a_d=C_a, UA_d=ntu_d * c_min, P_fan_d=float(cfg.fan_ratio) * Q_d,
                   approach_d=approach, n_air=float(cfg.dc_ua_exponent), x_min=float(cfg.dc_fan_min))

    def capacity(self, x, C_w, T_in, T_amb):
        """Heat (W) the cooler rejects at fan speed x from water entering at T_in."""
        x = np.asarray(x, dtype=float)
        C_a = self.C_a_d * x
        c_min, c_max = np.minimum(C_w, C_a), np.maximum(C_w, C_a)
        ntu = self.UA_d * x ** self.n_air / np.maximum(c_min, 1e-12)
        eps = crossflow_effectiveness(ntu, c_min / np.maximum(c_max, 1e-12))
        return eps * c_min * np.maximum(np.asarray(T_in, dtype=float) - np.asarray(T_amb, dtype=float), 0.0)


def dry_cooler_operate(design: DryCoolerDesign, C_w, T_in, T_target, T_amb, iters: int = 40):
    """Run the dry cooler toward a water outlet temperature (vectorised).

    Returns dict with Q_dc (W), T_out (degC), x (fan speed fraction, 0 when off), P_fan (W),
    saturated (bool: full fan speed could not reach the target)."""
    C_w = np.asarray(C_w, dtype=float)
    T_in, T_target, T_amb = np.broadcast_arrays(*(np.asarray(v, dtype=float) for v in (T_in, T_target, T_amb)))
    C_w = np.broadcast_to(C_w, T_in.shape)
    if np.any(C_w <= 0):
        raise ValueError("water capacity rate must be positive")
    Q_need = np.maximum(C_w * (T_in - T_target), 0.0)
    useful = (Q_need > 0) & (T_in > T_amb)
    Q_full = design.capacity(1.0, C_w, T_in, T_amb)
    saturated = useful & (Q_full < Q_need)
    lo = np.full(T_in.shape, design.x_min)
    hi = np.ones(T_in.shape)
    for _ in range(iters):                       # smallest x with capacity(x) >= Q_need
        mid = 0.5 * (lo + hi)
        ok = design.capacity(mid, C_w, T_in, T_amb) >= Q_need
        hi = np.where(ok, mid, hi)
        lo = np.where(ok, lo, mid)
    x = np.where(saturated, 1.0, hi)
    x = np.where(useful, np.maximum(x, design.x_min), 0.0)
    Q_dc = np.where(useful, np.minimum(Q_need, design.capacity(x, C_w, T_in, T_amb)), 0.0)
    return {"Q_dc": Q_dc, "T_out": T_in - Q_dc / C_w, "x": x, "P_fan": design.P_fan_d * x ** 3,
            "saturated": saturated}


def _reject(Cdot, T_hot, T_target, T_amb, cfg):
    """Dry cooler first, trim chiller for the rest; shared by the quasi-steady and dynamic plants."""
    from .chiller import chiller_cop_part_load
    design = DryCoolerDesign.from_config(cfg)
    dc = dry_cooler_operate(design, Cdot, T_hot, T_target, T_amb)
    T_dc_out = dc["T_out"]
    Q_ch = np.maximum(Cdot * (T_dc_out - np.asarray(T_target, dtype=float)), 0.0)
    cop = chiller_cop_part_load(T_target, T_amb, Q_ch, design.Q_d, cfg)
    W_ch = Q_ch / cop
    P_cond_fan = cfg.fan_ratio * (Q_ch + W_ch)        # chiller condenser fans, as in the legacy plant
    return dc, Q_ch, W_ch, cop, P_cond_fan


def plant_ntu(Q_in, T_sup, flow_factor, T_amb, cfg):
    """Quasi-steady plant with the NTU dry cooler; same outputs and sign conventions as
    ``ueic.physics.plant`` (selected by ``plant_model = 1``)."""
    from . import mass_flow_per_accel
    Q_raw = np.asarray(Q_in, dtype=float)
    T_sup = np.asarray(T_sup, dtype=float)
    Cdot = cfg.n_accel * mass_flow_per_accel(flow_factor, cfg) * cfg.water_cp
    Q_pos = np.maximum(Q_raw, 0.0)
    T_ret = T_sup + Q_raw / Cdot
    T_hot = T_sup + Q_pos / Cdot
    dc, Q_ch, W_ch, cop, P_cond = _reject(Cdot, T_hot, T_sup, T_amb, cfg)
    P_fan = dc["P_fan"] + P_cond
    return {"T_ret": T_ret, "Q_dc": dc["Q_dc"], "Q_ch": Q_ch, "W_ch": W_ch, "P_fan": P_fan, "cop": cop,
            "Q_amb": dc["Q_dc"] + Q_ch + W_ch + P_fan, "Cdot": Cdot, "Q_loop_storage": np.minimum(Q_raw, 0.0),
            "fan_speed": dc["x"]}


def plant_split_ntu(Q_plant, T_out, flow_factor, T_amb, cfg):
    """Dynamic-loop plant with the NTU dry cooler; same outputs as ``ueic.physics.plant_split``."""
    from . import mass_flow_per_accel
    Q_plant = np.maximum(np.asarray(Q_plant, dtype=float), 0.0)
    T_out = np.asarray(T_out, dtype=float)
    Cdot = cfg.n_accel * mass_flow_per_accel(flow_factor, cfg) * cfg.water_cp
    T_hot = T_out + Q_plant / Cdot
    dc, Q_ch, W_ch, cop, P_cond = _reject(Cdot, T_hot, T_out, T_amb, cfg)
    P_fan = dc["P_fan"] + P_cond
    return {"T_hot": T_hot, "Q_dc": dc["Q_dc"], "Q_ch": Q_ch, "W_ch": W_ch, "P_fan": P_fan, "cop": cop,
            "Q_amb": dc["Q_dc"] + Q_ch + W_ch + P_fan, "Cdot": Cdot, "fan_speed": dc["x"]}
