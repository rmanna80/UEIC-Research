"""Steady-state digital twin used by the controllers to predict the consequences
of an action before it is applied.

Given an estimated demand D_c (nominal work-seconds per second, per job class)
and a candidate action (per-class clock s_c, coolant supply temperature, flow
factor), it predicts utilisation, busy/idle junction temperatures (with
leakage-temperature feedback), IT power, pump/fan/chiller power, and grid power.

Approximation (class E): chips are modelled as spending a fraction u_c of time
busy on class c at that class's steady busy temperature and the rest idle at
the idle steady temperature. Transients are handled by the time-stepped
simulator, not here.
"""
from __future__ import annotations

import numpy as np

from . import physics as ph


def class_constants(cfg):
    beta = np.array([cfg.beta_compute, cfg.beta_memory])
    act = np.array([1.0, cfg.activity_memory])
    return beta, act


def evaluate(cfg, D, s_c, s_m, T_sup, flow, T_amb):
    """Vectorised over broadcastable action arrays. D = (D_compute, D_memory)."""
    # Inputs are NOT pre-broadcast: busy states depend only on (s_class, T_sup, flow)
    # and idle states only on (T_sup, flow), so passing orthogonal grids
    # (e.g. shapes (6,1,1,1), (1,6,1,1), (1,1,34,1), (1,1,1,6)) keeps the
    # expensive leakage fixed-point solves on the small sub-grids.
    beta, act = class_constants(cfg)
    s_c, s_m, T_sup, flow = (np.asarray(x, dtype=float) for x in (s_c, s_m, T_sup, flow))
    N = cfg.n_accel
    u_c = D[0] / (N * s_c ** beta[0])
    u_m = D[1] / (N * s_m ** beta[1])
    u = u_c + u_m
    R = ph.r_total(flow, cfg)

    def busy_state(s, a):
        A = ph.temp_independent_power(s, a, cfg, busy=True)
        L = cfg.p_leak_ref * ph.voltage_ratio(s, cfg)
        T, ok = ph.steady_temperature(T_sup, R, A, L, cfg)
        P = A + L * np.exp(cfg.kappa_leak * (np.where(ok, T, cfg.t_leak_ref) - cfg.t_leak_ref))
        return T, P, ok

    T_c, P_c, ok_c = busy_state(s_c, act[0])
    T_m, P_m, ok_m = busy_state(s_m, act[1])
    A_i = ph.temp_independent_power(cfg.s_min, 0.0, cfg, busy=False) * np.ones_like(T_sup)
    L_i = cfg.p_leak_ref * ph.voltage_ratio(cfg.s_min, cfg) * np.ones_like(T_sup)
    T_i, ok_i = ph.steady_temperature(T_sup, R, A_i, L_i, cfg)
    P_i = A_i + L_i * np.exp(cfg.kappa_leak * (np.where(ok_i, T_i, cfg.t_leak_ref) - cfg.t_leak_ref))

    P_avg = u_c * P_c + u_m * P_m + np.clip(1.0 - u, 0.0, None) * P_i
    P_it = N * P_avg
    P_pump = ph.pump_power(flow, cfg)
    pl = ph.plant(P_it + P_pump, T_sup, flow, T_amb, cfg)
    P_grid = P_it / cfg.eta_conv + P_pump + pl["P_fan"] + pl["W_ch"]

    need_c, need_m = D[0] > 0, D[1] > 0
    temp_ok = ok_i & (~need_c | (ok_c & (T_c <= cfg.t_target))) & (~need_m | (ok_m & (T_m <= cfg.t_target)))
    feasible = (u <= cfg.u_max) & temp_ok
    return {
        "u": u, "T_c": T_c, "T_m": T_m, "T_i": T_i, "P_c": P_c, "P_m": P_m, "P_i": P_i,
        "P_it": P_it, "P_pump": P_pump, "P_fan": pl["P_fan"], "W_ch": pl["W_ch"],
        "T_ret": pl["T_ret"], "P_grid": P_grid, "feasible": feasible, "temp_ok": temp_ok,
    }


def it_power_fixed_temperature(cfg, D, s_c, s_m, T_assumed):
    """IT power predicted by a compute-only controller that has no thermal model:
    it assumes every chip sits at T_assumed."""
    beta, act = class_constants(cfg)
    s_c, s_m = np.broadcast_arrays(np.asarray(s_c, float), np.asarray(s_m, float))
    N = cfg.n_accel
    u_c = D[0] / (N * s_c ** beta[0])
    u_m = D[1] / (N * s_m ** beta[1])
    u = u_c + u_m
    P_c = ph.chip_power(s_c, T_assumed, act[0], cfg)
    P_m = ph.chip_power(s_m, T_assumed, act[1], cfg)
    P_i = ph.idle_power(T_assumed, cfg)
    P_it = N * (u_c * P_c + u_m * P_m + np.clip(1 - u, 0, None) * P_i)
    return P_it, u
