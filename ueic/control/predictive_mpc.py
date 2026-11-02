"""Multi-step model predictive control that credits cooling when it will arrive (Stage 3).

Motivation (E010-E014): steady-state joint control judged safety at a setpoint that had not arrived
and overheated chips under a slow loop; the measured-state rule (joint_meas / joint_lag) fixed the
safety but never used the slow actuator, giving up capacity. This controller predicts the supply
temperature trajectory each candidate command produces and plans clocks for every future step.

Decision at time t (every control interval Delta):
  candidates      supply setpoint c on the controller grid, flow f on the flow grid, both held
                  over the horizon (move blocking: one block); clocks chosen per step
  futures         T_k(c, f): predicted supply in step k (``futures.trajectories``: command delay,
                  ramp limit, well-mixed tank; exact when model = plant and heat input is as assumed)
  per step k      demand forecast D_k (``forecast``), backlog B_k (work-seconds per class),
                  effective demand D_eff = D_k + B_k / backlog_clear_s;
                  for every clock pair (s_c, s_m): utilisation u = D_eff,c/(N s_c^b_c) + D_eff,m/(N s_m^b_m),
                  chip power from the steady chip model at the step's peak supply T_k (safety) ,
                  plant heat Q = P_IT + P_pump + Q_store,k and plant power at the plant setpoint;
                  choose the cheapest pair with u <= u_max and all temperatures <= t_target at T_k;
                  if none, the safe pair with the lowest u (throughput first) and serve D_eff u_max/u;
                  if no pair is safe at T_k the candidate is rejected
  backlog         B_{k+1} = max(0, B_k + D_k Delta - served_k)
  objective       sum_k [P_grid,k Delta + w B_{k+1} Delta] + w B_H backlog_clear_s
                  (w = mpc_backlog_weight, W per work-second: an explicit, tunable service price)
  action          step-0 clocks, flow f*, setpoint command c*; then the independent SafetyFilter
                  validates it before it reaches the plant.

Failure handling: any exception, a decision slower than ``mpc_time_budget_s``, or no feasible
candidate returns the approved fallback (``fallback.py``); all are counted in ``self.events``.
Approximations: heat into the loop over the horizon is bounded by the full-clock heat at t_throttle
(conservative: predicted tank warming is never optimistic, matching the safety filter); chip power is
evaluated at the step's peak supply temperature (slightly conservative on energy); the plant cost
uses the steady plant at the step's mean plant setpoint.
"""
from __future__ import annotations

from time import perf_counter

import numpy as np

from .. import physics as ph
from ..policies import Action, Policy, _with_target, f_grid, s_grid, t_grid
from .fallback import fallback_action
from .forecast import PersistenceForecaster, make_forecaster
from .futures import PlantSetpointTracker, chip_states, temps_ok, trajectories
from .safety_filter import SafetyFilter


class MPCPolicy(Policy):
    name = "mpc"
    robust = False

    def __init__(self, model_cfg):
        super().__init__(model_cfg)
        self.tracker = PlantSetpointTracker(model_cfg)
        self.filter = SafetyFilter(model_cfg)
        self.forecaster = PersistenceForecaster()
        self.events: dict[str, int] = {}
        self.fail_next: str | None = None           # test hook: "raise" or "timeout"

    def attach_scenario(self, sc, seed: int) -> None:
        self.forecaster = make_forecaster(self.cfg, sc, seed)

    def _count(self, k: str) -> None:
        self.events[k] = self.events.get(k, 0) + 1

    # ------------------------------------------------------------------ decision
    def _decide(self, obs):
        cfg = self.cfg
        sp = self.tracker.advance(obs.t)
        t0 = perf_counter()
        try:
            if self.fail_next == "raise":
                raise RuntimeError("injected solver failure")
            proposal = self._optimise(obs, sp)
            if self.fail_next == "timeout" or perf_counter() - t0 > float(cfg.mpc_time_budget_s):
                raise TimeoutError("time budget exceeded")
            self._count("opt")
        except TimeoutError:
            self._count("fallback:timeout")
            proposal = fallback_action(cfg, obs.T_sup_actual, "timeout")
        except Exception:                                   # noqa: BLE001 - any solver failure is an operational case
            self._count("fallback:solver-error")
            proposal = fallback_action(cfg, obs.T_sup_actual, "solver-error")
        if proposal is None:
            self._count("fallback:infeasible")
            proposal = fallback_action(cfg, obs.T_sup_actual, "infeasible")
        approved = self.filter.validate(proposal, obs)
        if approved.note.endswith("filtered"):
            self._count("filtered")
        self.tracker.issue(obs.t, approved.t_sup)
        return approved

    def _safety_scenarios(self) -> list:
        return [self.cfg]

    def _optimise(self, obs, sp: float | None) -> Action | None:
        cfg = self.cfg
        H = int(cfg.mpc_horizon_steps)
        dt = float(cfg.control_interval)
        S, C, F = s_grid(cfg), t_grid(cfg), f_grid(cfg)
        nS, nC, nF = len(S), len(C), len(F)
        N = cfg.n_accel
        beta = np.array([cfg.beta_compute, cfg.beta_memory])
        D = np.asarray(self.forecaster.demand(obs, H, dt, cfg), dtype=float)          # (H, 2)
        T_amb = np.asarray(self.forecaster.ambient(obs, H, dt), dtype=float)          # (H,)
        T0 = obs.T_sup_actual if np.isfinite(obs.T_sup_actual) else None
        sp_known = sp is not None and T0 is not None and self.filter._dynamic()
        if sp is None or T0 is None:                     # first decision: nothing commanded yet
            sp = T0 = float(np.clip(cfg.fixed_t_sup if T0 is None else T0, cfg.t_sup_min, cfg.t_sup_max))
        pending = self.tracker.schedule(obs.t, H * dt)
        target0 = self.tracker.target if self.tracker.target is not None else sp
        # Safety-side heat input: every chip at full clock at t_throttle plus the pump at maximum flow, the
        # same bound the safety filter uses, so predicted warming of the tank is never optimistic.
        q_in = cfg.n_accel * float(ph.chip_power(1.0, cfg.t_throttle, 1.0, cfg)) + float(ph.pump_power(cfg.flow_max_factor, cfg))
        # supply trajectories; the robust variant takes the hottest over its model scenarios
        peaks, means, sps, qst = [], [], [], []
        for c in self._safety_scenarios():
            tr = trajectories(c, T0, sp, target0, pending, C, F, q_in, H, dt)
            peaks.append(tr["T_peak"]); means.append(tr["T_mean"]); sps.append(tr["sp_mean"]); qst.append(tr["Q_store"])
        T_peak = np.max(peaks, axis=0)
        sp_mean, Q_store = sps[0], qst[0]
        safety_cfg = _with_target(cfg, cfg.t_target - float(cfg.mpc_robust_margin_K)) if self.robust else cfg
        sc = S[:, None, None, None]
        sm = S[None, :, None, None]
        Fb = F[None, None, None, :]
        B = np.broadcast_to(np.maximum(np.asarray(obs.backlog, dtype=float), 0.0), (nC, nF, 2)).copy()
        cost = np.zeros((nC, nF))
        alive = np.ones((nC, nF), dtype=bool)
        first = None
        w = float(cfg.mpc_backlog_weight)
        P_pump = ph.pump_power(F, cfg)[None, None, None, :]
        if sp_known:          # step 0 uses the safety filter's own supply bound, so proposals pass the filter
            T_peak[0] = np.maximum(T_peak[0], self.filter.supply_bound(obs.t, T0, sp, C[:, None], F[None, :]))
        for k in range(H):
            st = chip_states(cfg, sc, sm, T_peak[k][None, None], Fb)
            ok_t = temps_ok(st, safety_cfg)                                              # (nS, nS, nC, nF)
            D_eff = D[k][None, None, :] + B / float(cfg.backlog_clear_s)                 # (nC, nF, 2)
            u_c = D_eff[None, None, :, :, 0] / (N * sc ** beta[0])
            u_m = D_eff[None, None, :, :, 1] / (N * sm ** beta[1])
            u = u_c + u_m
            P_it = N * (u_c * st["P_c"] + u_m * st["P_m"] + np.clip(1.0 - u, 0.0, None) * st["P_i"])
            Q_plant = np.maximum(P_it + P_pump + Q_store[k][None, None], 0.0)
            pl = ph.plant(Q_plant, sp_mean[k][None, None], Fb, T_amb[k], cfg)
            P_grid = P_it / cfg.eta_conv + P_pump + pl["P_fan"] + pl["W_ch"]
            feas = ok_t & (u <= cfg.u_max)
            any_feas = feas.any(axis=(0, 1))
            any_safe = ok_t.any(axis=(0, 1))
            obj = np.where(feas, P_grid, np.inf).reshape(nS * nS, nC, nF)
            i_f = np.argmin(obj, axis=0)
            key = np.where(ok_t, u + 1e-9 * P_grid, np.inf).reshape(nS * nS, nC, nF)
            i_s = np.argmin(key, axis=0)
            idx = np.where(any_feas, i_f, i_s)
            take = lambda a: np.take_along_axis(np.broadcast_to(a, (nS, nS, nC, nF)).reshape(nS * nS, nC, nF),
                                                idx[None], axis=0)[0]
            P_sel, u_sel = take(P_grid), take(u)
            frac = np.where(any_feas, 1.0, np.minimum(1.0, cfg.u_max / np.maximum(u_sel, 1e-12)))
            served = D_eff * frac[:, :, None] * dt
            B = np.maximum(0.0, B + D[k][None, None, :] * dt - served)
            alive &= any_safe
            cost += np.where(any_safe, P_sel * dt + w * B.sum(axis=2) * dt, np.inf)
            if k == 0:
                first = idx
        cost += w * B.sum(axis=2) * float(cfg.backlog_clear_s)
        cost = np.where(alive, cost, np.inf)
        if not np.isfinite(cost).any():
            return None
        ic, jf = np.unravel_index(np.argmin(cost), cost.shape)
        i_s, j_s = np.unravel_index(int(first[ic, jf]), (nS, nS))
        return Action((float(S[i_s]), float(S[j_s])), float(C[ic]), float(F[jf]), "mpc:opt")


class RobustMPCPolicy(MPCPolicy):
    """Scenario-robust variant: candidate supply trajectories must be safe for the nominal loop model
    and for loop mass x0.5 / x2 and ramp x0.5 / x2 (hottest supply over the five), with an extra
    ``mpc_robust_margin_K`` below t_target for cold-plate and leakage model error. Costs are nominal.
    This is scenario robustness over a stated set, not a probabilistic guarantee."""
    name = "mpc_robust"
    robust = True

    def _safety_scenarios(self) -> list:
        from ..params import make_config
        base = {k: v for k, v in self.cfg.items()}
        out = [self.cfg]
        for key, fac in (("loop_mass_kg", 0.5), ("loop_mass_kg", 2.0), ("tsup_ramp_K_per_min", 0.5),
                         ("tsup_ramp_K_per_min", 2.0)):
            if float(base[key]) > 0:
                out.append(make_config({**base, key: float(base[key]) * fac}))
        return out
