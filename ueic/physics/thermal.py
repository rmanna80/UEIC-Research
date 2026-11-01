"""Chip and cold-plate thermal network (documented view of the legacy model; Stage 1).

Re-exports the legacy functions unchanged:
  R_total(f) = R_cond + R_conv_ref * f**(-n_conv) + 1/(2 m_dot c_p)          K/W   [A + E]
  C dT/dt = P - (T - T_in)/R_total   (one lumped node per accelerator)         [A, lumped approximation]
  Exact step: T(t+dt) = T_ss + (T - T_ss) exp(-dt/(R C)),  T_ss = T_in + P R   (unconditionally stable)
  Steady state with leakage feedback: T = T_in + R (A + L exp(kappa (T - T_ref))); exists iff
  max_T g(T) >= 0 for g(T) = T - T_in - R A - R L exp(...)                     (analytic test)

``time_constant`` gives tau = R C, the scale on which clocks act on temperature; the coolant loop's
own time constant is tau_loop = M c_p / C_dot (``thermal_storage``), usually far longer.
"""
from __future__ import annotations

import numpy as np

from . import leakage_steady_state_exists, r_caloric, r_conv, r_total, steady_temperature, thermal_step  # noqa: F401


def time_constant(flow_factor, cfg):
    """Junction thermal time constant R_total * C (s)."""
    return np.asarray(r_total(flow_factor, cfg), dtype=float) * cfg.c_th


def loop_time_constant(mass_kg: float, flow_factor, cfg):
    """Well-mixed loop time constant M c_p / C_dot (s)."""
    from . import mass_flow_per_accel
    C_dot = cfg.n_accel * mass_flow_per_accel(flow_factor, cfg) * cfg.water_cp
    return mass_kg * cfg.water_cp / C_dot
