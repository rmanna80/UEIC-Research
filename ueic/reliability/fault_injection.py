"""Fault injection between a supervisor and the simulated plant (simulation only).

``FaultInjector`` is the outermost policy wrapper. Within [t_start, t_end) it corrupts what the supervisor
sees and/or what reaches the plant:

  kind  name              effect
  0     none              (control runs; any alarm is a false positive)
  1     sensor_dropout    junction and supply readings NaN (telemetry network dropout)
  2     sensor_bias       junction readings + magnitude K (negative = reads low)
  8     supply_bias       supply-temperature reading + magnitude K
  3     stale_telemetry   junction and supply readings frozen at their t_start values (stuck sensors, fresh time stamps)
  4     clock_stuck       the GPU keeps the clocks it had at t_start; the reported applied clock shows it
  5     comm_failure      all telemetry frozen and commands not delivered (plant keeps the last delivered action)
  6     controller_crash  the controller raises
  7     solver_infeasible the controller raises an infeasibility error
Physical faults use registry parameters on the *true* plant only, so the controller does not know them:
valve/command delay (``tsup_cmd_delay_s``), fouling (``r_fouling_*``), reduced flow or a degraded pump
(``flow_max_factor``, ``eta_pump``), and wrong model parameters (``model_param_overrides``).
Every observation carries ``s_applied``: the clocks the GPU actually ran in the previous interval (what NVML
would report), which is how an actuation fault can be seen, and ``telemetry_t``: the time stamp of the
newest telemetry sample, which is how a communication failure can be seen.
"""
from __future__ import annotations

import copy

import numpy as np

from ..policies import Action, Policy

KINDS = {0: "none", 1: "sensor_dropout", 2: "sensor_bias", 3: "stale_telemetry", 4: "clock_stuck",
         5: "comm_failure", 6: "controller_crash", 7: "solver_infeasible", 8: "supply_bias"}


class FaultInjector(Policy):
    name = "fault_injector"

    def __init__(self, model_cfg, supervisor, kind: int | None = None, t_start: float | None = None,
                 t_end: float | None = None, magnitude: float | None = None):
        super().__init__(model_cfg)
        g = lambda k, d: getattr(model_cfg, k, None) if getattr(model_cfg, k, None) is not None else d   # noqa: E731
        self.kind = int(kind if kind is not None else g("fault_kind", 0))
        self.t0 = float(t_start if t_start is not None else g("fault_t_start", 3600.0))
        self.t1 = float(t_end if t_end is not None else g("fault_t_end", 5400.0))
        self.mag = float(magnitude if magnitude is not None else g("fault_magnitude", 0.0))
        self.sup = supervisor
        if self.kind in (6, 7):
            supervisor.set_crash_window(self.t0, self.t1, KINDS[self.kind])
        self.frozen_obs = None
        self.applied: tuple | None = None
        self.delivered: Action | None = None
        self.stuck_s: tuple | None = None

    def attach_scenario(self, sc, seed):
        if hasattr(self.sup, "attach_scenario"):
            self.sup.attach_scenario(sc, seed)

    def _active(self, t: float) -> bool:
        return self.kind != 0 and self.t0 <= t < self.t1

    def _decide(self, obs):
        on = self._active(obs.t)
        o = copy.copy(obs)
        o.T_j = np.array(obs.T_j, dtype=float, copy=True)
        o.s_applied = self.applied
        o.telemetry_t = float(obs.t)            # sample time stamped by the telemetry source
        if on and self.kind in (3, 5):
            if self.frozen_obs is None:
                self.frozen_obs = copy.copy(o)
            f = self.frozen_obs
            o.T_j, o.T_j_peak, o.T_sup_actual = f.T_j.copy(), f.T_j_peak, f.T_sup_actual
            if self.kind == 5:
                o.q_chips, o.D_est, o.backlog, o.p_chip_peak, o.s_applied = f.q_chips, f.D_est, f.backlog, f.p_chip_peak, f.s_applied
                o.telemetry_t = f.telemetry_t       # nothing new arrives: the last sample's time stamp
        elif on and self.kind == 1:
            o.T_j[:] = np.nan
            o.T_j_peak = o.T_sup_actual = float("nan")
        elif on and self.kind == 8:
            o.T_sup_actual = o.T_sup_actual + self.mag
        elif on and self.kind == 2:
            o.T_j = o.T_j + self.mag
            o.T_j_peak = o.T_j_peak + self.mag
        if not on:
            self.frozen_obs = None
        a = self.sup.decide(o)
        if on and self.kind == 5 and self.delivered is not None:
            a = self.delivered                                 # command lost: plant keeps the last delivered one
        if on and self.kind == 4:
            if self.stuck_s is None:
                self.stuck_s = self.applied or tuple(a.s)
            a = Action(self.stuck_s, a.t_sup, a.flow, a.note)
        elif not on:
            self.stuck_s = None
        self.delivered = a
        self.applied = tuple(a.s)
        return a

    def diagnostics(self) -> dict:
        d = {"fault_kind": self.kind, "fault_t_start": self.t0, "fault_t_end": self.t1}
        if hasattr(self.sup, "diagnostics"):
            d.update(self.sup.diagnostics())
        return d


def make_stack(model_cfg, inner_name: str, aware: bool, **fault):
    """FaultInjector(Supervisor(controller)). ``fault`` overrides the fault_* parameters."""
    from ..policies import POLICIES
    from .safety_monitor import FaultAwareSupervisor, NominalSupervisor
    inner = POLICIES[inner_name](model_cfg)
    sup = (FaultAwareSupervisor if aware else NominalSupervisor)(model_cfg, inner)
    return FaultInjector(model_cfg, sup, **fault)


def _stack_class(inner_name: str, aware: bool):
    from .safety_monitor import FaultAwareSupervisor, NominalSupervisor

    class Stack(FaultInjector):
        name = f"{'aware' if aware else 'nominal'}_{inner_name}"

        def __init__(self, model_cfg):
            from ..policies import POLICIES
            sup_cls = FaultAwareSupervisor if aware else NominalSupervisor
            super().__init__(model_cfg, sup_cls(model_cfg, POLICIES[inner_name](model_cfg)))

    Stack.__name__ = Stack.__qualname__ = f"Stack_{Stack.name}"
    return Stack


STACKS = [_stack_class(i, a) for i in ("joint_meas", "mpc") for a in (False, True)]
