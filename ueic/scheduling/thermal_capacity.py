"""Thermal capacity budgets: how much more heat a GPU can take over a horizon before its junction limit.

Lumped junction node (the same model the simulators integrate exactly, ``physics.thermal_step``):
    C dT/dt = P - (T - T_in) / R,      tau = R C
With power held at P + dP for a horizon H, starting at T0, the temperature rises monotonically toward
T_ss = T_in + R (P + dP) and reaches T(H) = T_ss + (T0 - T_ss) e^(-H/tau). Requiring T(H) <= T_lim gives

    power budget   dP_max(H) = [ (T_lim - T0 e^(-H/tau)) / (1 - e^(-H/tau)) - T_in ] / R - P          [W]
    energy budget  E(H)      = dP_max(H) * H                                                         [J]

Limits: H -> 0 gives dP_max ~ C (T_lim - T0) / H (stored-heat limited: the heat capacity absorbs a short
burst); H -> inf gives (T_lim - T_in)/R - P (rejection limited: the steady headroom). So the budget is
neither the heat-capacity figure C (T_lim - T0) alone nor the steady headroom alone; which one binds
depends on the job duration relative to tau.

Shared cooling enters through T_in. In a series cold-plate chain every downstream inlet rises by
dP / (m_dot c_p) when power is added upstream, and the plant's supply can rise over the horizon. Both are
passed in explicitly (``inlet_shift``, ``T_in_future``) so the budget is evaluated for the inlet the GPU
*will* see, not the one it sees now. Uncertainty is handled by a margin: T_lim_eff = T_lim - k sigma_T,
with sigma_T combining inlet-forecast and model error (stated by the caller).

Validity: one lumped node per GPU, constant R over the horizon (flow constant), leakage folded into P at
the current temperature (it grows with T, so budgets are slightly optimistic near the limit; callers keep
a margin). Units: K, W, J/K, s.
"""
from __future__ import annotations

import numpy as np


def power_budget(T0, T_in, R, C, P, T_lim, H):
    """Extra constant power (W) that keeps T(H) <= T_lim. Negative means already over budget. Vectorised."""
    T0, T_in, R, C, P = (np.asarray(x, dtype=float) for x in (T0, T_in, R, C, P))
    H = np.asarray(H, dtype=float)
    a = np.exp(-H / (R * C))
    with np.errstate(divide="ignore", invalid="ignore"):
        T_ss_max = np.where(H > 0, (T_lim - T0 * a) / (1.0 - a), np.inf)
    return (T_ss_max - T_in) / R - P


def energy_budget(T0, T_in, R, C, P, T_lim, H):
    return power_budget(T0, T_in, R, C, P, T_lim, H) * np.asarray(H, dtype=float)


def time_to_limit(T0, T_in, R, C, P_total, T_lim):
    """Seconds until T reaches T_lim at constant total power (inf if the steady state is below it)."""
    T0, T_in, R, C, P_total = (np.asarray(x, dtype=float) for x in (T0, T_in, R, C, P_total))
    T_ss = T_in + R * P_total
    with np.errstate(divide="ignore", invalid="ignore"):
        t = R * C * np.log((T_ss - T0) / (T_ss - T_lim))
    return np.where(T0 >= T_lim, 0.0, np.where(T_ss <= T_lim, np.inf, t))


def effective_limit(T_lim: float, sigma_T: float = 0.0, k: float = 2.0) -> float:
    """Limit reduced by k standard deviations of combined temperature uncertainty."""
    if sigma_T < 0:
        raise ValueError("sigma_T must be >= 0")
    return T_lim - k * sigma_T
