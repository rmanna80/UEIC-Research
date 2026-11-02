"""Heat pump that upgrades waste heat to a customer's supply temperature (Stage 1 component).

    T_src = source (return-water) temperature, T_sink = delivery temperature            degC
    T_evap = T_src - dt_evap_hp,  T_cond = T_sink + dt_cond_hp                            K
    COP_heating = eta_II,hp * T_cond / (T_cond - T_evap), capped at cop_max_hp            [A: Carnot; F: eta_II, approaches]
    Q_delivered = Q_src + W,  W = Q_delivered / COP_heating                               [A: first law]

If the source is already at or above the delivery temperature no lift is needed (W = 0).
Defaults (eta_II 0.5, approaches 3 K, cap 10) are class F placeholders, not a product rating.
"""
from __future__ import annotations

import numpy as np

KELVIN = 273.15


def heating_cop(T_src, T_sink, eta_ii: float = 0.5, dt_evap: float = 3.0, dt_cond: float = 3.0,
                cop_max: float = 10.0):
    if not 0 < eta_ii <= 1:
        raise ValueError("eta_ii must be in (0, 1]")
    T_e = np.asarray(T_src, dtype=float) - dt_evap + KELVIN
    T_c = np.asarray(T_sink, dtype=float) + dt_cond + KELVIN
    lift = T_c - T_e
    with np.errstate(divide="ignore", invalid="ignore"):
        cop = np.where(lift > 0, eta_ii * T_c / lift, cop_max)
    return np.minimum(cop, cop_max)


def upgrade(Q_src, T_src, T_sink, **kw):
    """Heat delivered and electricity used when a heat pump lifts Q_src (W) from T_src to T_sink."""
    Q_src = np.asarray(Q_src, dtype=float)
    if np.any(Q_src < 0):
        raise ValueError("source heat must be >= 0")
    direct = np.asarray(T_src, dtype=float) >= np.asarray(T_sink, dtype=float)
    cop = heating_cop(T_src, T_sink, **kw)
    W = np.where(direct, 0.0, Q_src / np.maximum(cop - 1.0, 1e-9))     # Q_del = Q_src + W, Q_del = COP*W
    return {"Q_delivered": Q_src + W, "W": W, "cop": np.where(direct, np.inf, cop)}
