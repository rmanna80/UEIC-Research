"""Accelerator power and performance (documented view of the legacy model; Stage 1).

The functions are the legacy ones from ``ueic.physics`` (re-exported unchanged, so results do not
move). Equations, units and provenance:

  Clock ratio         s = f / f_ref in [s_min, 1]                                      -
  Voltage ratio       v(s) = v_min + (1 - v_min)(s - s_min)/(1 - s_min)   (linear, registry)
                      v(s) = v_min + (1 - v_min) max(0, (s - k)/(1 - k))  (voltage floor, vf_knee = k;
                                                                           shape fitted to M001, class E)
  Dynamic power       P_dyn = P_dyn_max * a * s * v**2                   W   [A: P = alpha C V^2 f]
  Static power        P_static_other (temperature-independent)            W   [F]
  Leakage             P_leak = P_leak_ref * v * exp(kappa (T - T_ref))    W   [E form; slope matched to M001/M002]
  Throughput          rate = s**beta_class                                -   [beta_c measured 0.983 +/- 0.009;
                                                                               beta_m from a streaming kernel, a bound]
  Energy per work     e(s, T) = P(s, T) / s**beta                          J per nominal work-second

Valid range: s in [s_min, 1]; T within the leakage fit window is interpolation, outside it is
extrapolation (``ueic.models.parameter_registry`` warns). The power surface is per accelerator and
excludes host CPU, memory, network and cooling.
"""
from __future__ import annotations

import numpy as np

from . import chip_power, idle_power, leakage_power, temp_independent_power, voltage_ratio  # noqa: F401


def energy_per_work(s, T, cls: int, cfg):
    """J per nominal work-second for job class cls (0 compute, 1 memory) at clock ratio s and temperature T."""
    beta = cfg.beta_compute if cls == 0 else cfg.beta_memory
    act = 1.0 if cls == 0 else cfg.activity_memory
    s = np.asarray(s, dtype=float)
    return chip_power(s, T, act, cfg) / s ** beta


def most_efficient_clock(T, cls: int, cfg, grid=None):
    """Clock ratio that minimises energy per work at temperature T (ignoring deadlines)."""
    g = np.round(np.arange(cfg.s_min, 1.0 + 1e-9, 0.01), 6) if grid is None else np.asarray(grid, dtype=float)
    e = energy_per_work(g, T, cls, cfg)
    return float(g[int(np.argmin(e))]), float(np.min(e))
