"""Physical models: accelerator power, thermal network, pump, heat-rejection plant.

All functions are vectorised with NumPy so the same code serves the time-stepped
simulator and the steady-state digital twin used by the controllers.

Governing equations (evidence class in brackets):
  CMOS dynamic power      P_dyn  = P_dyn_max * a * s * (V/Vmax)^2            [A: P = a C V^2 f]
  Linear V-f scaling      V/Vmax = Vmin_r + (1 - Vmin_r) (s - s_min)/(1 - s_min)  [E]
  Leakage                 P_leak = P_leak_ref * (V/Vmax) * exp(kappa (T - Tref))  [E]
  Lumped RC thermal       C dT/dt = P - (T - T_in) / R_total                   [A, lumped approx]
  Thermal resistance      R_total = R_cond + R_conv(flow) + 1/(2 m_dot cp)     [A + E]
  Coolant energy balance  Q = m_dot cp (T_out - T_in)                          [A]
  Pump power              P_pump = dP * Vdot / eta,  dP = dP_ref (flow)^m      [A + E]
  Chiller                 COP = eta_II * T_evap / (T_cond - T_evap)            [A Carnot bound, E eta_II]
  Exergy of heat stream   Ex = m cp [(T1 - T2) - T0 ln(T1/T2)]                 [A]
  Landauer bound          E_min = k_B T ln 2 per irreversibly erased bit       [A]
"""
from __future__ import annotations

import numpy as np

KELVIN = 273.15


# --------------------------------------------------------------------------- power
def voltage_ratio(s, cfg):
    s = np.asarray(s, dtype=float)
    return cfg.v_min_ratio + (1.0 - cfg.v_min_ratio) * (s - cfg.s_min) / (1.0 - cfg.s_min)


def leakage_power(T, v, cfg):
    return cfg.p_leak_ref * v * np.exp(cfg.kappa_leak * (np.asarray(T, dtype=float) - cfg.t_leak_ref))


def temp_independent_power(s, activity, cfg, busy=True):
    """Dynamic + temperature-independent static power (everything except leakage)."""
    s = np.asarray(s, dtype=float)
    v = voltage_ratio(s, cfg)
    a = activity if busy else cfg.idle_dyn_frac
    return cfg.p_dyn_max * a * s * v ** 2 + cfg.p_static_other


def chip_power(s, T, activity, cfg, busy=True):
    v = voltage_ratio(s, cfg)
    return temp_independent_power(s, activity, cfg, busy) + leakage_power(T, v, cfg)


def idle_power(T, cfg):
    return chip_power(cfg.s_min, T, 0.0, cfg, busy=False)


# ------------------------------------------------------------------------- thermal
def mass_flow_per_accel(flow_factor, cfg):
    """kg/s through one accelerator's cold plate."""
    return cfg.flow_design_lpm * np.asarray(flow_factor, dtype=float) / 60e3 * cfg.water_rho


def r_conv(flow_factor, cfg):
    return cfg.r_conv_ref * np.asarray(flow_factor, dtype=float) ** (-cfg.n_conv)


def r_caloric(flow_factor, cfg):
    """Mean-fluid-temperature rise per watt: 1/(2 m_dot cp)."""
    return 1.0 / (2.0 * mass_flow_per_accel(flow_factor, cfg) * cfg.water_cp)


def r_total(flow_factor, cfg):
    """Junction-to-coolant-inlet thermal resistance (K/W)."""
    return cfg.r_cond + r_conv(flow_factor, cfg) + r_caloric(flow_factor, cfg)


def thermal_step(T, P, T_in, R, C, dt):
    """Exact solution of C dT/dt = P - (T - T_in)/R over dt with P held constant.

    Returns (T_new, Q_to_coolant) where Q_to_coolant is the heat (J) delivered to
    the coolant during the step. Energy is conserved exactly by construction:
        P*dt = C*(T_new - T) + Q_to_coolant
    The step is unconditionally stable for any dt.
    """
    T_ss = T_in + P * R
    a = np.exp(-dt / (R * C))
    T_new = T_ss + (T - T_ss) * a
    Q = P * dt - C * (T_new - T)
    return T_new, Q


def leakage_steady_state_exists(T_in, R, A, L, cfg):
    """Analytic existence test for T = T_in + R*(A + L*exp(kappa*(T-Tref))).

    g(T) = T - T_in - R*A - R*L*exp(kappa*(T-Tref)) is concave, so a (stable)
    steady state exists iff max g >= 0. The maximum is at
        T* = Tref + ln(1/(R*L*kappa))/kappa,    g(T*) = T* - T_in - R*A - 1/kappa.
    If no root exists the chip is in thermal runaway for this cooling setting.
    """
    k = cfg.kappa_leak
    if k == 0:
        return np.ones(np.broadcast(T_in, R, A, L).shape, dtype=bool)
    with np.errstate(divide="ignore"):
        T_star = cfg.t_leak_ref + np.log(1.0 / (R * L * k)) / k
    return (T_star - T_in - R * A - 1.0 / k) >= 0


def steady_temperature(T_in, R, A, L, cfg, iters=60):
    """Stable steady junction temperature with leakage feedback (vectorised Newton).

    Starts from T_lo = T_in + R*A (always left of the stable root) and iterates
    Newton on the concave g(T); iterates increase monotonically to the root.
    Returns (T, ok) where ok=False marks thermal runaway (no steady state).
    """
    T_in, R, A, L = np.broadcast_arrays(*(np.asarray(x, dtype=float) for x in (T_in, R, A, L)))
    k, Tr = cfg.kappa_leak, cfg.t_leak_ref
    T = T_in + R * A
    ok = np.ones(T.shape, dtype=bool)
    for _ in range(iters):
        e = L * np.exp(np.clip(k * (T - Tr), -50, 50))
        g = T - T_in - R * (A + e)
        dg = 1.0 - R * e * k
        ok &= dg > 0
        step = np.where(ok, -g / np.where(dg > 0, dg, 1.0), 0.0)
        T = T + step
        ok &= T < 250.0
        if np.all(np.abs(step[ok]) < 1e-9) if ok.any() else True:
            break
    e = L * np.exp(np.clip(k * (T - Tr), -50, 50))
    ok &= np.abs(T - T_in - R * (A + e)) < 1e-6
    return np.where(ok, T, np.inf), ok


# ---------------------------------------------------------------------- hydraulics
def loop_volume_flow(flow_factor, cfg):
    """m^3/s through the whole loop (accelerators in parallel)."""
    return cfg.n_accel * cfg.flow_design_lpm * np.asarray(flow_factor, dtype=float) / 60e3


def pump_power(flow_factor, cfg):
    """Electrical pump power (W). All of it is assumed to end up as heat in the coolant."""
    f = np.asarray(flow_factor, dtype=float)
    dp = cfg.dp_ref * f ** cfg.m_dp
    return dp * loop_volume_flow(f, cfg) / cfg.eta_pump


# --------------------------------------------------------------------------- plant
def chiller_cop(T_sup, T_amb, cfg):
    T_evap = np.asarray(T_sup, dtype=float) - cfg.dt_evap + KELVIN
    T_cond = np.asarray(T_amb, dtype=float) + cfg.dt_cond + KELVIN
    lift = T_cond - T_evap
    with np.errstate(divide="ignore", invalid="ignore"):
        cop = np.where(lift > 0, cfg.eta_ii_chiller * T_evap / lift, cfg.cop_max)
    return np.minimum(cop, cfg.cop_max)


def carnot_cop(T_sup, T_amb, cfg):
    T_evap = np.asarray(T_sup, dtype=float) - cfg.dt_evap + KELVIN
    T_cond = np.asarray(T_amb, dtype=float) + cfg.dt_cond + KELVIN
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(T_cond > T_evap, T_evap / (T_cond - T_evap), np.inf)


def plant(Q_in, T_sup, flow_factor, T_amb, cfg):
    """Quasi-steady heat-rejection plant: dry cooler (free cooling) + trim chiller.

    Q_in: heat entering the coolant per unit time (chips + pump), W.
    The dry cooler cools return water toward T_amb + dt_drycooler; the chiller
    removes whatever is left to reach T_sup. Fans run on all heat rejected outdoors.
    """
    Q_raw = np.asarray(Q_in, dtype=float)
    T_sup = np.asarray(T_sup, dtype=float)
    Cdot = cfg.n_accel * mass_flow_per_accel(flow_factor, cfg) * cfg.water_cp  # W/K
    # Net heat can flow from coolant INTO chips (e.g. supply raised above an idle chip's
    # temperature). The plant cannot do negative work, and the quasi-steady loop has no
    # thermal mass, so that (small, transient) deficit is booked as a loop storage term
    # instead of as negative chiller work. Bug found in E001 v1; see research log.
    Q_in = np.maximum(Q_raw, 0.0)
    Q_loop_storage = np.minimum(Q_raw, 0.0)
    T_ret = T_sup + Q_raw / Cdot
    T_ret_pos = T_sup + Q_in / Cdot
    T_floor = np.asarray(T_amb, dtype=float) + cfg.dt_drycooler
    T_dc_out = np.minimum(np.maximum(T_sup, T_floor), T_ret_pos)
    Q_dc = Cdot * (T_ret_pos - T_dc_out)
    Q_ch = Cdot * (T_dc_out - T_sup)
    cop = chiller_cop(T_sup, T_amb, cfg)
    W_ch = Q_ch / cop
    Q_out_pre_fan = Q_dc + Q_ch + W_ch
    P_fan = cfg.fan_ratio * Q_out_pre_fan
    return {
        "T_ret": T_ret, "Q_dc": Q_dc, "Q_ch": Q_ch, "W_ch": W_ch, "P_fan": P_fan,
        "cop": cop, "Q_amb": Q_out_pre_fan + P_fan, "Cdot": Cdot, "Q_loop_storage": Q_loop_storage,
    }


# ---------------------------------------------------------------- thermodynamics
def stream_exergy_rate(Cdot, T_hot, T_cold, T0):
    """Work potential (W) of the heat released when a stream with capacity rate Cdot
    (W/K) is cooled from T_hot to T_cold, relative to dead state T0 (degC in, K inside).

    Only the part of the temperature range above T0 counts: heat below ambient has
    no work potential for reuse (cooling a sub-ambient stream further *consumes*
    exergy, which is the chiller's job and is already counted as chiller work).
    v0.1.0 omitted this clip and reported negative values when T_sup < T_amb."""
    T0c = np.asarray(T0, dtype=float)
    T_hot = np.maximum(np.asarray(T_hot, dtype=float), T0c)
    T_cold = np.maximum(np.asarray(T_cold, dtype=float), T0c)
    Th, Tc, T0k = (np.asarray(x, dtype=float) + KELVIN for x in (T_hot, T_cold, T0c))
    with np.errstate(divide="ignore", invalid="ignore"):
        ex = Cdot * ((Th - Tc) - T0k * np.log(Th / Tc))
    return np.where(Th > Tc, ex, 0.0)


def landauer_energy(T_kelvin, cfg):
    """Minimum heat per irreversibly erased bit, k_B T ln 2 (J). A bound on erasure,
    NOT a minimum energy cost for AI computation in general."""
    return cfg.k_boltzmann * T_kelvin * np.log(2.0)
