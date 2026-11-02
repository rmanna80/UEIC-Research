"""Plant futures: what the chips will see over a horizon if a setpoint is commanded now (Stage 3).

Same plant equations as the simulator (``ueic.sim``), so predictions are exact when the model's loop
parameters equal the plant's and the heat input is as assumed:

  Command path        a command issued at t reaches the plant at t + d (``tsup_cmd_delay_s``)
  Plant setpoint      sp moves toward the latest arrived command at most r K/s (``tsup_ramp_K_per_min``/60)
  Tank (mass M > 0)   plant active (sp < T_ret = T + q_in/C_dot): T <- sp + (T - sp) exp(-dt C_dot / (M c_p))
                      pass-through (sp >= T_ret):                 T <- T + q_in dt / (M c_p)  (the plant cannot heat water)
  No tank (M = 0)     T = sp
  Heat the plant removes over a step:  Q_plant = q_in + M c_p (T_start - T_end) / dt   (>= 0)

``PlantSetpointTracker`` follows the plant setpoint from the controller's own validated commands
(the plant's setpoint is not a measured signal in the simulator); the tank temperature itself is
measured (``Observation.T_sup_actual``).

Approximation: q_in (heat entering the loop) is held at its current measured value over the horizon.
"""
from __future__ import annotations

from collections import deque

import numpy as np

from .. import physics as ph


class PlantSetpointTracker:
    """Plant setpoint estimate from issued commands, with command delay and ramp limit."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.sp: float | None = None
        self.target: float | None = None
        self.pending: deque[tuple[float, float]] = deque()     # (arrival time, value)
        self.t_last: float | None = None

    def advance(self, t: float) -> float | None:
        """Bring the estimate forward to time t (call before deciding)."""
        if self.t_last is None:
            self.t_last = t
            return self.sp
        ramp = float(self.cfg.tsup_ramp_K_per_min) / 60.0
        tau = self.t_last
        events = [a for a, _ in self.pending if a <= t] + [t]
        for t_ev in events:
            while self.pending and self.pending[0][0] <= tau + 1e-9:
                self.target = self.pending.popleft()[1]
            dt = t_ev - tau
            if self.sp is not None and self.target is not None and dt > 0:
                self.sp = self.target if ramp <= 0 else self.sp + float(np.clip(self.target - self.sp, -ramp * dt, ramp * dt))
            tau = t_ev
        while self.pending and self.pending[0][0] <= t + 1e-9:
            self.target = self.pending.popleft()[1]
        self.t_last = t
        return self.sp

    def issue(self, t: float, value: float) -> None:
        d = float(self.cfg.tsup_cmd_delay_s)
        if self.sp is None:                       # the simulator applies the very first command at once
            self.sp = self.target = float(value)
            self.t_last = t
            return
        if d <= 0:
            self.target = float(value)
        else:
            self.pending.append((t + d, float(value)))

    def schedule(self, t: float, horizon_s: float) -> list[tuple[float, float]]:
        """Commands already issued that will arrive within the horizon: [(seconds from now, value)]."""
        return [(a - t, v) for a, v in self.pending if a - t < horizon_s]


def trajectories(cfg, T0: float, sp0: float, target0: float, pending: list[tuple[float, float]],
                 cmd: np.ndarray, flow: np.ndarray, q_in: float, H: int, dt: float, n_sub: int = 6) -> dict:
    """Predicted supply temperature per control step for every (command, flow) candidate.

    cmd: candidate commands, shape (nC,); flow: candidate flow factors, shape (nF,).
    Returns arrays of shape (H, nC, nF): T_peak (hottest supply in the step), T_mean, sp_mean,
    Q_store (W, heat released by the tank, i.e. extra heat the plant must remove)."""
    cmd = np.asarray(cmd, dtype=float)[:, None]
    flow = np.asarray(flow, dtype=float)[None, :]
    shape = (cmd.shape[0], flow.shape[1])
    M_cp = float(cfg.loop_mass_kg) * cfg.water_cp
    ramp = float(cfg.tsup_ramp_K_per_min) / 60.0
    d = float(cfg.tsup_cmd_delay_s)
    Cdot = cfg.n_accel * ph.mass_flow_per_accel(flow, cfg) * cfg.water_cp
    T = np.full(shape, float(T0))
    sp = np.full(shape, float(sp0))
    target = np.full(shape, float(target0))
    events = sorted(pending) + [(d, None)]              # None = the candidate command (issued now, arrives at d)
    h = dt / n_sub
    out = {k: np.empty((H,) + shape) for k in ("T_peak", "T_mean", "sp_mean", "Q_store")}
    tau = 0.0
    i_ev = 0
    dynamic = M_cp > 0 or ramp > 0 or d > 0
    for k in range(H):
        peak = T.copy() if dynamic else np.full(shape, -np.inf)     # an instant plant delivers the command at once
        acc_T = np.zeros(shape)
        acc_sp = np.zeros(shape)
        T_start = T.copy()
        for _ in range(n_sub):
            while i_ev < len(events) and events[i_ev][0] <= tau + 1e-9:   # commands that have arrived
                v = events[i_ev][1]
                target = np.broadcast_to(cmd, shape).copy() if v is None else np.full(shape, float(v))
                i_ev += 1
            sp = target.copy() if ramp <= 0 else sp + np.clip(target - sp, -ramp * h, ramp * h)
            if M_cp <= 0:
                T = sp.copy()
            else:
                active = sp < T + q_in / Cdot                  # as ueic.sim: plant active below the return temperature
                T = np.where(active, sp + (T - sp) * np.exp(-h * Cdot / M_cp), T + q_in * h / M_cp)
            tau += h
            peak = np.maximum(peak, T)
            acc_T += T
            acc_sp += sp
        out["T_peak"][k] = peak
        out["T_mean"][k] = acc_T / n_sub
        out["sp_mean"][k] = acc_sp / n_sub
        out["Q_store"][k] = M_cp * (T_start - T) / dt if M_cp > 0 else 0.0
    return out


def chip_states(cfg, s_c, s_m, T_sup, flow) -> dict:
    """Steady busy and idle junction temperatures and powers (same equations as ``twin.evaluate``,
    without the plant). Shapes broadcast; s_c (nS,1,...), s_m (1,nS,...), T_sup and flow over candidates."""
    act_m = cfg.activity_memory
    T_sup, flow = np.asarray(T_sup, dtype=float), np.asarray(flow, dtype=float)
    R = ph.r_total(flow, cfg)

    def busy(s, a):
        A = ph.temp_independent_power(s, a, cfg, busy=True)
        L = cfg.p_leak_ref * ph.voltage_ratio(s, cfg)
        T, ok = ph.steady_temperature(T_sup, R, A, L, cfg)
        P = A + L * np.exp(cfg.kappa_leak * (np.where(ok, T, cfg.t_leak_ref) - cfg.t_leak_ref))
        return T, P, ok

    T_c, P_c, ok_c = busy(np.asarray(s_c, dtype=float), 1.0)
    T_m, P_m, ok_m = busy(np.asarray(s_m, dtype=float), act_m)
    A_i = ph.temp_independent_power(cfg.s_min, 0.0, cfg, busy=False) * np.ones(np.broadcast(T_sup, flow).shape)
    L_i = cfg.p_leak_ref * ph.voltage_ratio(cfg.s_min, cfg) * np.ones_like(A_i)
    T_i, ok_i = ph.steady_temperature(T_sup, R, A_i, L_i, cfg)
    P_i = A_i + L_i * np.exp(cfg.kappa_leak * (np.where(ok_i, T_i, cfg.t_leak_ref) - cfg.t_leak_ref))
    return {"T_c": T_c, "P_c": P_c, "ok_c": ok_c, "T_m": T_m, "P_m": P_m, "ok_m": ok_m, "T_i": T_i, "P_i": P_i,
            "ok_i": ok_i}


def temps_ok(st: dict, cfg, margin: float = 0.0):
    lim = cfg.t_target - margin
    return st["ok_i"] & st["ok_c"] & (st["T_c"] <= lim) & st["ok_m"] & (st["T_m"] <= lim) & (st["T_i"] <= lim)


def warming_rate_bound(cfg) -> float:
    """Fastest possible rise of the supply temperature (K/s) from installation ratings: q_max / (M c_p)
    for a loop of water mass M, where q_max = every chip at full clock at t_throttle plus the pump at
    maximum flow (the plant cannot heat water); the plant ramp limit when there is no tank."""
    M_cp = float(cfg.loop_mass_kg) * cfg.water_cp
    if M_cp > 0:
        q_max = cfg.n_accel * float(ph.chip_power(1.0, cfg.t_throttle, 1.0, cfg)) + \
            float(ph.pump_power(cfg.flow_max_factor, cfg))
        return q_max / M_cp
    ramp = float(cfg.tsup_ramp_K_per_min) / 60.0
    return ramp if ramp > 0 else float("inf")


def supply_upper_bound(cfg, T_meas, T_up, flow, dt: float):
    """Upper bound on the supply temperature over the next dt (vectorised over T_up and flow).

    With a tank of water mass M fed by the plant at a temperature no higher than T_up (its setpoint or
    the return water), dT/dt <= (T_up - T) C_dot / (M c_p) and dT/dt <= q_max / (M c_p), so
        T(dt) <= min(T_up - (T_up - T_meas) exp(-dt C_dot / (M c_p)),  T_meas + q_max dt / (M c_p)).
    Without a tank the supply follows the ramp-limited setpoint: T(dt) <= min(T_up, T_meas + ramp dt).
    Never below the measured value (cooling that has not arrived is not credited)."""
    T_meas = float(T_meas)
    T_up = np.asarray(T_up, dtype=float)
    flow = np.asarray(flow, dtype=float)
    rise = T_up > T_meas
    M_cp = float(cfg.loop_mass_kg) * cfg.water_cp
    lin = T_meas + warming_rate_bound(cfg) * dt
    if M_cp > 0:
        Cdot = cfg.n_accel * mass_flow_from(flow, cfg) * cfg.water_cp
        expo = T_up - (T_up - T_meas) * np.exp(-dt * Cdot / M_cp)
        bound = np.minimum(np.minimum(expo, lin), T_up)
    else:
        bound = np.minimum(T_up, lin)
    return np.where(rise, bound, T_meas)


def mass_flow_from(flow, cfg):
    return ph.mass_flow_per_accel(flow, cfg)
