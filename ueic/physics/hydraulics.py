"""Pump and system curves (Stage 1 component; not yet used by the simulator).

System curve (legacy):     dp(f) = dp_ref * f**m_dp                                Pa   [A form, E exponent]
Volume flow:               V(f) = n_accel * flow_design_lpm * f / 60e3             m^3/s
Hydraulic power:           P_hyd = dp * V                                          W
Pump efficiency curve:     eta(f) = eta_bep * (1 - k * ((f - f_bep) / f_bep)**2),  clipped to [eta_min, eta_bep]
                           (a parabolic best-efficiency-point curve; class F shape)  -
Electrical power:          P_el = P_hyd / eta(f)                                   W
Affinity laws (same pump, speed ratio r):  V ~ r, dp ~ r**2, P_hyd ~ r**3           [A]

All electrical pump power is assumed to end as heat in the coolant (as in the legacy model).
The legacy simulator uses a constant efficiency (``eta_pump``); ``pump_power_curve`` with
k = 0 reproduces it exactly.
"""
from __future__ import annotations

import numpy as np


def system_pressure_drop(flow_factor, cfg):
    f = np.asarray(flow_factor, dtype=float)
    if np.any(f < 0):
        raise ValueError("flow factor must be >= 0")
    return cfg.dp_ref * f ** cfg.m_dp


def pump_efficiency(flow_factor, eta_bep: float, f_bep: float = 1.0, k: float = 0.5, eta_min: float = 0.05):
    f = np.asarray(flow_factor, dtype=float)
    if not 0 < eta_bep <= 1 or f_bep <= 0 or k < 0:
        raise ValueError("need 0 < eta_bep <= 1, f_bep > 0, k >= 0")
    eta = eta_bep * (1.0 - k * ((f - f_bep) / f_bep) ** 2)
    return np.clip(eta, eta_min, eta_bep)


def pump_power_curve(flow_factor, cfg, f_bep: float = 1.0, k: float = 0.5):
    """Electrical pump power (W) with a best-efficiency-point curve."""
    from . import loop_volume_flow
    f = np.asarray(flow_factor, dtype=float)
    return system_pressure_drop(f, cfg) * loop_volume_flow(f, cfg) / pump_efficiency(f, cfg.eta_pump, f_bep, k)


def affinity(speed_ratio, V0, dp0, P0):
    """Fan/pump affinity laws for one machine at a new speed: (V, dp, P_hyd)."""
    r = np.asarray(speed_ratio, dtype=float)
    return V0 * r, dp0 * r ** 2, P0 * r ** 3
