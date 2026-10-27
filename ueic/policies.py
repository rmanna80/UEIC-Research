"""Control policies compared in the benchmark (charter workstreams B, C, D).

  fixed         conventional baseline: full clock when busy, fixed supply temp and flow
  compute_only  energy-aware DVFS per job class (no thermal model), fixed cooling
  cooling_only  full clock, cooling plant optimised for the measured chip heat
  independent   compute_only + cooling_only running side by side, uncoordinated
  joint         one model-predictive optimiser over clocks, supply temp and flow,
                using the steady-state digital twin (leakage-temperature coupling and
                cooling energy included), subject to hard thermal/utilisation limits

Each policy receives its own `model_cfg`: what the controller *believes* the plant
is. By default it equals the simulator's true configuration; the robustness
experiment deliberately makes them differ.

Hardware protection is not part of any policy. It lives in the simulator and
throttles any chip above t_throttle regardless of what the controller asks for.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

import numpy as np

from . import physics as ph
from . import twin


@dataclass(frozen=True)
class Action:
    s: tuple[float, float]   # clock for (compute-bound, memory-bound) jobs
    t_sup: float
    flow: float
    note: str = ""


@dataclass
class Observation:
    t: float
    D_est: np.ndarray          # estimated arriving work per class (nominal s per s)
    backlog: np.ndarray        # queued nominal work per class (s)
    T_amb: float
    p_chip_peak: float         # max per-chip power observed over the recent window, W
    q_chips: float             # mean total chip heat over the last interval, W
    T_j: np.ndarray = field(default_factory=lambda: np.zeros(0))
    T_j_peak: float = float("nan")      # hottest junction seen during the last interval, degC
    T_sup_actual: float = float("nan")  # supply temperature actually reaching the chips, degC


def s_grid(cfg):
    return np.round(np.arange(cfg.s_min, 1.0 + 1e-9, 0.1), 6)


def t_grid(cfg):
    return np.arange(cfg.t_sup_min, cfg.t_sup_max + 1e-9, cfg.t_sup_step)


def f_grid(cfg):
    g = np.array([0.5, 0.75, 1.0, 1.25, 1.5, 2.0])
    return g[(g >= cfg.flow_min_factor - 1e-9) & (g <= cfg.flow_max_factor + 1e-9)]


def planned_demand(obs: Observation, cfg) -> np.ndarray:
    return obs.D_est + obs.backlog / cfg.backlog_clear_s


# ------------------------------------------------------------------ sub-optimisers
def optimise_compute(cfg, D):
    """Minimise predicted IT power over per-class clocks, temperature assumed fixed."""
    S = s_grid(cfg)
    sc, sm = np.meshgrid(S, S, indexing="ij")
    P, u = twin.it_power_fixed_temperature(cfg, D, sc, sm, cfg.t_assume_compute)
    feas = u <= cfg.u_max
    if not feas.any():
        return (1.0, 1.0), "compute:infeasible->max clock"
    i = np.unravel_index(np.argmin(np.where(feas, P, np.inf)), P.shape)
    return (float(sc[i]), float(sm[i])), "compute:opt"


def optimise_cooling(cfg, p_peak, q_chips, T_amb):
    """Minimise pump+fan+chiller power keeping the hottest chip (at its measured
    peak power, treated as fixed) at or below t_target. No leakage feedback."""
    T, F = np.meshgrid(t_grid(cfg), f_grid(cfg), indexing="ij")
    T_pred = T + ph.r_total(F, cfg) * p_peak
    P_pump = ph.pump_power(F, cfg)
    pl = ph.plant(q_chips + P_pump, T, F, T_amb, cfg)
    cost = P_pump + pl["P_fan"] + pl["W_ch"]
    feas = T_pred <= cfg.t_target
    if not feas.any():
        return float(cfg.t_sup_min), float(f_grid(cfg).max()), "cooling:infeasible->max cooling"
    i = np.unravel_index(np.argmin(np.where(feas, cost, np.inf)), cost.shape)
    return float(T[i]), float(F[i]), "cooling:opt"


def optimise_joint(cfg, D, T_amb, T_seen=None):
    """Grid search over (s_compute, s_memory, supply setpoint, flow) on the steady-state twin.

    T_seen (optional, shape (n_tsup, n_flow)): the hottest supply temperature the chips will
    actually see before the next decision if that setpoint and flow are commanded (lag-aware
    control). Thermal feasibility is then checked at T_seen instead of at the setpoint, while the
    energy objective stays the steady-state cost of the commanded action. If nothing is feasible,
    safety comes before capacity: the highest clocks that are thermally safe at T_seen."""
    S, Tg, Fg = s_grid(cfg), t_grid(cfg), f_grid(cfg)
    sc = S[:, None, None, None]
    sm = S[None, :, None, None]
    T = Tg[None, None, :, None]
    F = Fg[None, None, None, :]
    r = twin.evaluate(cfg, D, sc, sm, T, F, T_amb)
    shape = np.broadcast_shapes(sc.shape, sm.shape, T.shape, F.shape)
    if T_seen is not None:
        rs = twin.evaluate(cfg, D, sc, sm, np.asarray(T_seen, float)[None, None, :, :], F, T_amb)
        safe = np.broadcast_to(rs["temp_ok"], shape)
        feasible = np.broadcast_to(r["u"] <= cfg.u_max, shape) & safe
        obj = np.where(feasible, np.broadcast_to(r["P_grid"], shape), np.inf)
        if np.isfinite(obj).any():
            i = np.unravel_index(np.argmin(obj), shape)
            return (float(S[i[0]]), float(S[i[1]])), float(Tg[i[2]]), float(Fg[i[3]]), "joint_lag:opt"
        if safe.any():
            # capacity short: maximise throughput among safe actions (lowest utilisation), then cheapest
            u = np.broadcast_to(r["u"], shape)
            key = np.where(safe, u + 1e-9 * np.broadcast_to(r["P_grid"], shape), np.inf)
            i = np.unravel_index(np.argmin(key), shape)
            return (float(S[i[0]]), float(S[i[1]])), float(Tg[i[2]]), float(Fg[i[3]]), "joint_lag:safety-first"
        return (float(S[0]), float(S[0])), float(Tg[0]), float(Fg[-1]), "joint_lag:infeasible->min clock, max cooling"
    obj = np.broadcast_to(np.where(r["feasible"], r["P_grid"], np.inf), shape)
    if np.isfinite(obj).any():
        i = np.unravel_index(np.argmin(obj), shape)
        note = "joint:opt"
    else:
        # Demand exceeds planned capacity: run full clock, cheapest thermally safe cooling.
        ok = np.broadcast_to(r["temp_ok"], shape)[-1, -1]
        pg = np.broadcast_to(r["P_grid"], shape)[-1, -1]
        if ok.any():
            j = np.unravel_index(np.argmin(np.where(ok, pg, np.inf)), pg.shape)
            i = (len(S) - 1, len(S) - 1, j[0], j[1])
            note = "joint:capacity-limited"
        else:
            i = (len(S) - 1, len(S) - 1, 0, len(Fg) - 1)
            note = "joint:infeasible->max cooling"
    return (float(S[i[0]]), float(S[i[1]])), float(Tg[i[2]]), float(Fg[i[3]]), note


# ------------------------------------------------------------------------ policies
class Policy:
    name = "base"

    def __init__(self, model_cfg):
        self.cfg = model_cfg
        self.decision_wall_s: list[float] = []

    def decide(self, obs: Observation) -> Action:
        t0 = perf_counter()
        a = self._decide(obs)
        self.decision_wall_s.append(perf_counter() - t0)
        return a

    def _decide(self, obs: Observation) -> Action:  # pragma: no cover
        raise NotImplementedError


class FixedPolicy(Policy):
    name = "fixed"

    def _decide(self, obs):
        return Action((1.0, 1.0), float(self.cfg.fixed_t_sup), float(self.cfg.fixed_flow), "fixed")


class ComputeOnlyPolicy(Policy):
    name = "compute_only"

    def _decide(self, obs):
        s, note = optimise_compute(self.cfg, planned_demand(obs, self.cfg))
        return Action(s, float(self.cfg.fixed_t_sup), float(self.cfg.fixed_flow), note)


class CoolingOnlyPolicy(Policy):
    name = "cooling_only"

    def _decide(self, obs):
        t, f, note = optimise_cooling(self.cfg, obs.p_chip_peak, obs.q_chips, obs.T_amb)
        return Action((1.0, 1.0), t, f, note)


class IndependentPolicy(Policy):
    name = "independent"

    def _decide(self, obs):
        s, n1 = optimise_compute(self.cfg, planned_demand(obs, self.cfg))
        t, f, n2 = optimise_cooling(self.cfg, obs.p_chip_peak, obs.q_chips, obs.T_amb)
        return Action(s, t, f, f"{n1};{n2}")


def _with_target(cfg, t_target):
    """Copy of a Config with a different thermal target (Config is read-only)."""
    from .params import Config
    c = Config()
    dict.update(c, cfg)
    dict.__setitem__(c, "t_target", t_target)
    return c


def predicted_peak(cfg, D, a: Action, T_amb) -> float:
    """Twin-predicted hottest steady junction temperature under action `a` for demand D."""
    r = twin.evaluate(cfg, D, a.s[0], a.s[1], a.t_sup, a.flow, T_amb)
    temps = [float(r["T_i"])]
    if D[0] > 0:
        temps.append(float(r["T_c"]))
    if D[1] > 0:
        temps.append(float(r["T_m"]))
    return max(temps)


class JointPolicy(Policy):
    """Joint model-predictive controller.

    Phase 3 option (cfg.joint_switch_rel > 0): move suppression. The previous action is
    kept while it is still feasible and predicted to cost no more than (1 + joint_switch_rel)
    times the new optimum, which removes switching driven by tiny predicted differences."""
    name = "joint"

    def __init__(self, model_cfg):
        super().__init__(model_cfg)
        self.prev: Action | None = None

    def _plan(self, obs, cfg) -> Action:
        D = planned_demand(obs, cfg)
        s, t, f, note = optimise_joint(cfg, D, obs.T_amb)
        best = Action(s, t, f, note)
        thr = float(cfg.joint_switch_rel)
        if thr > 0 and self.prev is not None and best != self.prev:
            p = self.prev
            rp = twin.evaluate(cfg, D, p.s[0], p.s[1], p.t_sup, p.flow, obs.T_amb)
            rb = twin.evaluate(cfg, D, s[0], s[1], t, f, obs.T_amb)
            if bool(rp["feasible"]) and float(rp["P_grid"]) <= (1.0 + thr) * float(rb["P_grid"]):
                best = Action(p.s, p.t_sup, p.flow, "joint:hold")
        self.prev = Action(best.s, best.t_sup, best.flow, best.note) if best.note != "joint:hold" else self.prev
        return best

    def _decide(self, obs):
        return self._plan(obs, self.cfg)


class JointRobustPolicy(JointPolicy):
    """Joint controller with offset-free temperature correction (Phase 3).

    After each interval it compares the hottest measured junction temperature with the
    twin's prediction for the action it took, keeps a one-sided EWMA of the error
    (b >= 0), and plans the next action against a tightened target t_target - b. This is
    the standard disturbance-estimation idea from offset-free MPC, applied only in the
    safe direction: the bias can make the controller more conservative, never less."""
    name = "joint_robust"

    def __init__(self, model_cfg):
        super().__init__(model_cfg)
        self.bias = 0.0
        self.pred_peak: float | None = None
        self.bias_history: list[float] = []

    def _decide(self, obs):
        g = float(self.cfg.joint_bias_gain)
        if self.pred_peak is not None and np.isfinite(obs.T_j_peak):
            e = obs.T_j_peak - self.pred_peak
            self.bias = max(0.0, (1.0 - g) * self.bias + g * e)
        self.bias_history.append(self.bias)
        cfg = _with_target(self.cfg, self.cfg.t_target - self.bias) if self.bias > 0 else self.cfg
        a = self._plan(obs, cfg)
        self.pred_peak = predicted_peak(self.cfg, planned_demand(obs, self.cfg), a, obs.T_amb)
        return a


def supply_peak(cfg, T0, sp0, q_in, horizon_s, n_sub=6):
    """Hottest supply temperature the chips see over the next `horizon_s` seconds, for every
    (setpoint, flow) on the controller's grid, given the measured supply (tank) temperature T0,
    the plant's current (ramp-limited) setpoint sp0 and the heat entering the loop q_in.

    Same plant model as the simulator: the setpoint moves toward the command at the ramp limit;
    the tank approaches a lower setpoint with time constant M*cp/Cdot(flow) and, when the setpoint
    is above it, warms only from the heat entering the loop (the plant cannot heat water)."""
    Tg, Fg = t_grid(cfg), f_grid(cfg)
    T_cmd = np.broadcast_to(Tg[:, None], (len(Tg), len(Fg))).astype(float)
    Cdot = cfg.n_accel * ph.mass_flow_per_accel(Fg, cfg) * cfg.water_cp
    M_cp = float(cfg.loop_mass_kg) * cfg.water_cp
    ramp = float(cfg.tsup_ramp_K_per_min) / 60.0
    if M_cp <= 0 and ramp <= 0:
        return T_cmd.copy()                       # quasi-steady plant: the command applies at once
    dt = horizon_s / n_sub
    sp = np.full_like(T_cmd, float(sp0))
    T = np.full_like(T_cmd, float(T0))
    peak = T.copy() if M_cp > 0 or ramp > 0 else np.full_like(T_cmd, -np.inf)
    for _ in range(n_sub):
        sp = T_cmd if ramp <= 0 else sp + np.clip(T_cmd - sp, -ramp * dt, ramp * dt)
        if M_cp <= 0:
            T = sp.copy()
        else:
            tau = M_cp / Cdot[None, :]
            cool = sp < T
            T = np.where(cool, sp + (T - sp) * np.exp(-dt / tau), np.minimum(sp, T + q_in * dt / M_cp))
        peak = np.maximum(peak, T)
    return peak


class JointLagPolicy(JointPolicy):
    """Lag-aware joint controller (Phase 3, E011).

    E006 and E010 showed the steady-state joint controller overheating chips under a slow coolant
    loop: it picks clocks that are safe at the commanded supply temperature while the chips still
    see warmer water in the tank. This controller keeps track of the plant's ramp-limited setpoint
    from its own commands, predicts the supply temperature the chips will actually see until the
    next decision (`supply_peak`), and requires the clocks and flow to be safe at that temperature.
    Clocks and flow act immediately; the supply setpoint is the slow actuator. With a quasi-steady
    plant it makes exactly the same decisions as `joint`."""
    name = "joint_lag"

    def __init__(self, model_cfg):
        super().__init__(model_cfg)
        self.sp_est: float | None = None
        self.last_cmd: float | None = None

    def _decide(self, obs):
        cfg = self.cfg
        ci = float(cfg.control_interval)
        ramp = float(cfg.tsup_ramp_K_per_min) / 60.0
        dynamic = float(cfg.loop_mass_kg) > 0 or ramp > 0
        if not dynamic or not np.isfinite(obs.T_sup_actual):
            a = self._plan(obs, cfg)
        else:
            if self.sp_est is None or self.last_cmd is None:
                self.sp_est = float(obs.T_sup_actual)
            else:   # where the plant setpoint got to during the last interval
                step = ramp * ci if ramp > 0 else np.inf
                self.sp_est = float(self.sp_est + np.clip(self.last_cmd - self.sp_est, -step, step))
            D = planned_demand(obs, cfg)
            q_in = float(obs.q_chips) + float(ph.pump_power(1.0, cfg))
            T_seen = supply_peak(cfg, float(obs.T_sup_actual), self.sp_est, q_in, ci + 3.0 * cfg.c_th * cfg.r_cond)
            s, t, f, note = optimise_joint(cfg, D, obs.T_amb, T_seen=T_seen)
            a = Action(s, t, f, note)
        self.last_cmd = float(np.clip(a.t_sup, cfg.t_sup_min, cfg.t_sup_max))
        return a


class JointFallbackPolicy(JointPolicy):
    """Ablation control for E011B: steady-state joint control (no loop-lag model) with joint_lag's
    overload fallback.

    E011 found that most of joint_lag's energy advantage over joint came from what each does when
    demand exceeds planned capacity, not from modelling the loop: joint then runs every clock at
    maximum, joint_lag maximises throughput among safe actions and breaks ties on power, which keeps
    clock-insensitive (memory-bound) work at a low clock. This policy checks feasibility at the
    commanded setpoint, exactly like joint, and falls back like joint_lag."""
    name = "joint_fb"

    def _decide(self, obs):
        cfg = self.cfg
        Tg, Fg = t_grid(cfg), f_grid(cfg)
        T_cmd = np.broadcast_to(Tg[:, None], (len(Tg), len(Fg))).astype(float)
        s, t, f, note = optimise_joint(cfg, planned_demand(obs, cfg), obs.T_amb, T_seen=T_cmd)
        return Action(s, t, f, note.replace("joint_lag", "joint_fb"))


POLICIES = {p.name: p for p in (FixedPolicy, ComputeOnlyPolicy, CoolingOnlyPolicy, IndependentPolicy, JointPolicy,
                                JointRobustPolicy, JointLagPolicy, JointFallbackPolicy)}
