"""Independent safety filter (Stage 3).

The optimiser proposes; this filter decides what reaches the plant. It shares no state with the
optimiser: it keeps its own plant-setpoint tracker built from the actions it has *approved*.

Checks, in order:
  1. Telemetry: with a dynamic loop the measured supply temperature must be finite; junction
     temperatures, if reported, must be finite. Otherwise -> fallback.
  2. Action limits: clocks in [s_min, 1], flow within limits, setpoint within [t_sup_min, t_sup_max].
     Out-of-range values are clipped and reported.
  3. Thermal: the steady junction temperature of every class (and of an idle chip) at the proposed
     clocks and flow must be <= t_target - safety_margin_K at an upper bound T_check on the supply
     temperature the chips can see before the next decision (interval Delta):
       instant plant, no command delay:  T_check = proposed setpoint
       otherwise:                        T_up = highest plant target that can be in force during the
                                         interval (tracked setpoint, commands arriving within Delta,
                                         the proposal if its delay < Delta);
                                         T_check = T_meas                         if T_up <= T_meas
                                         T_check = min(T_up, T_meas + r Delta)    otherwise,
       tightened, for a tank, by the exponential approach to T_up at the proposed flow
       (``futures.supply_upper_bound``). The rate bound r uses installation ratings only: q_max/(M c_p)
       for a loop of water mass M (q_max = every chip at full clock at t_throttle plus the pump at
       maximum flow; the plant cannot heat water), or the plant ramp limit when there is no tank.
     So the filter never credits cooling that has not arrived, and never assumes warming faster than
     the hardware allows. If the check fails it lowers clocks (then raises flow) to the highest safe
     pair; if none is safe -> fallback.

What it does not do: it does not check energy or service, and it relies on the same steady chip model
as the optimiser (a shared-model error is not caught; the hardware throttle remains the last line).
"""
from __future__ import annotations

import numpy as np

from ..policies import Action, f_grid, s_grid
from .fallback import fallback_action, safest_clocks
from .futures import PlantSetpointTracker, chip_states, supply_upper_bound, temps_ok


class SafetyFilter:
    def __init__(self, cfg):
        self.cfg = cfg
        self.tracker = PlantSetpointTracker(cfg)
        self.counts = {"ok": 0, "clipped": 0, "clocks_lowered": 0, "fallback": 0}

    def _dynamic(self) -> bool:
        c = self.cfg
        return float(c.loop_mass_kg) > 0 or float(c.tsup_ramp_K_per_min) > 0 or float(c.tsup_cmd_delay_s) > 0

    def validate(self, action: Action, obs) -> Action:
        cfg = self.cfg
        sp_now = self.tracker.advance(obs.t)
        T_meas = float(obs.T_sup_actual)
        if self._dynamic() and sp_now is not None and not np.isfinite(T_meas):
            return self._approve(fallback_action(cfg, None, "no-supply-telemetry"), obs, "fallback")
        if np.size(obs.T_j) and not np.all(np.isfinite(obs.T_j)):
            return self._approve(fallback_action(cfg, T_meas, "bad-junction-telemetry"), obs, "fallback")
        S, F = s_grid(cfg), f_grid(cfg)
        s = tuple(float(np.clip(x, S[0], S[-1])) for x in action.s)
        flow = float(np.clip(action.flow, F[0], F[-1]))
        t_sup = float(np.clip(action.t_sup, cfg.t_sup_min, cfg.t_sup_max))
        clipped = s != tuple(action.s) or flow != action.flow or t_sup != action.t_sup
        T_check = t_sup if (not self._dynamic() or sp_now is None) else \
            float(self.supply_bound(obs.t, T_meas, sp_now, t_sup, flow))
        margin = float(cfg.safety_margin_K)
        st = chip_states(cfg, s[0], s[1], T_check, flow)
        if bool(temps_ok(st, cfg, margin)):
            return self._approve(Action(s, t_sup, flow, action.note + (";clipped" if clipped else "")), obs,
                                 "clipped" if clipped else "ok")
        for f in sorted({flow, float(F[-1])}):
            Tc = T_check if (not self._dynamic() or sp_now is None) else float(self.supply_bound(obs.t, T_meas, sp_now, t_sup, f))
            s2, ok = safest_clocks(cfg, Tc, f, margin)
            if ok:
                return self._approve(Action(s2, t_sup, f, action.note + ";filtered"), obs, "clocks_lowered")
        return self._approve(fallback_action(cfg, T_check, "filter-no-safe-action"), obs, "fallback")

    def T_up(self, t: float, sp_now: float, proposal) -> np.ndarray:
        """Highest plant target that can be in force during the next interval (vectorised in proposal)."""
        cfg = self.cfg
        dt = float(cfg.control_interval)
        ups = [sp_now] + [v for a, v in self.tracker.pending if a - t < dt]
        if self.tracker.target is not None:
            ups.append(self.tracker.target)
        base = max(ups)
        return np.maximum(base, proposal) if float(cfg.tsup_cmd_delay_s) < dt else np.full_like(np.asarray(proposal, float), base)

    def supply_bound(self, t: float, T_meas: float, sp_now: float, proposal, flow):
        T_up = self.T_up(t, sp_now, proposal)
        if not np.isfinite(T_meas):
            return np.maximum(T_up, proposal)
        return supply_upper_bound(self.cfg, T_meas, T_up, flow, float(self.cfg.control_interval))

    def _approve(self, a: Action, obs, kind: str) -> Action:
        self.counts[kind] += 1
        self.tracker.issue(obs.t, a.t_sup)
        return a
