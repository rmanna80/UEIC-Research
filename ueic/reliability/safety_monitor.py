"""Fault-aware supervisor: validation, residual and degradation monitoring, recovery modes, and an
independent final safety check around any controller. Compared in E019 with ``NominalSupervisor``, which
only catches controller exceptions and holds the last action.

Per control interval:
  1. SensorValidator on junction and supply telemetry.
  2. If telemetry is valid: residual r = mean(T_j) - T_sup - R_model q/N into a two-sided CUSUM, and the
     excess-resistance estimator (DegradationDetector). A low-side CUSUM alarm means the junction
     sensors read low (unsafe direction) and they are no longer trusted until the residual returns to
     its baseline (|z| < 1) for ``clear_intervals`` intervals.
  3. Actuation check: if the GPU reports clocks (obs.s_applied) that differ from the last command by
     more than 0.05 for two intervals, the clocks are not being applied -> SAFE (maximise cooling).
  4. Mode: SAFE if supply telemetry is invalid, actuation failed or the controller raised; DEGRADED if
     junction telemetry is invalid or distrusted (replaced by T_sup + (R_model + dR) q/N + 3 K); else NORMAL.
  5. The proposed action passes a Stage 3 SafetyFilter whose plate resistance includes max(dR, 0).
The simulated hardware throttle still acts on true temperatures underneath all of this.
"""
from __future__ import annotations

import copy

import numpy as np

from .. import physics as ph
from ..control.fallback import fallback_action
from ..control.safety_filter import SafetyFilter
from ..params import make_config
from ..policies import Action, Policy
from .anomaly_detection import ResidualCUSUM
from .degradation_detection import DegradationDetector
from .recovery import RecoveryManager
from .sensor_validation import SensorValidator


class _CrashMixin:
    crash: tuple[float, float, str] | None = None

    def set_crash_window(self, t0: float, t1: float, kind: str) -> None:
        self.crash = (t0, t1, kind)

    def _call_inner(self, obs) -> Action:
        if self.crash and self.crash[0] <= obs.t < self.crash[1]:
            raise RuntimeError(f"injected {self.crash[2]}")
        return self.inner.decide(obs)

    def attach_scenario(self, sc, seed):
        if hasattr(self.inner, "attach_scenario"):
            self.inner.attach_scenario(sc, seed)


class NominalSupervisor(_CrashMixin, Policy):
    name = "nominal"

    def __init__(self, model_cfg, inner):
        super().__init__(model_cfg)
        self.inner = inner
        self.last: Action | None = None
        self.n_exceptions = 0

    def _decide(self, obs):
        try:
            a = self._call_inner(obs)
        except Exception:  # noqa: BLE001 - a nominal stack holds its last command
            self.n_exceptions += 1
            a = self.last or fallback_action(self.cfg, None, "fallback-no-previous-action")
            a = Action(a.s, a.t_sup, a.flow, "hold-last-after-exception")
        self.last = a
        return a

    def diagnostics(self) -> dict:
        d = {"exceptions": self.n_exceptions}
        if hasattr(self.inner, "diagnostics"):
            d.update(self.inner.diagnostics())
        return d


class FaultAwareSupervisor(_CrashMixin, Policy):
    name = "fault_aware"

    def __init__(self, model_cfg, inner, margin_K: float = 3.0):
        super().__init__(model_cfg)
        self.inner, self.margin = inner, margin_K
        self.val, self.cusum = SensorValidator(), ResidualCUSUM()
        self.deg = DegradationDetector(model_cfg.n_accel)
        self.rec = RecoveryManager()
        self.filter = SafetyFilter(model_cfg)
        self.last_cmd: tuple | None = None
        self.last_flow = 1.0
        self.mismatch = 0
        self.distrust_T = False
        self.healthy_z = 0
        self.alarms: dict[str, int] = {}
        self.n_exceptions = 0
        self._dR_cfg = 0.0
        self.first_any_t: float | None = None
        self._t = 0.0

    def _alarm(self, k: str):
        self.alarms[k] = self.alarms.get(k, 0) + 1
        if self.first_any_t is None:
            self.first_any_t = self._t

    def _substitute(self, obs, R_eff: float):
        o = copy.copy(obs)
        sup = float(obs.T_sup_actual) if np.isfinite(obs.T_sup_actual) else self.cfg.t_sup_max
        est = sup + R_eff * float(obs.q_chips) / self.cfg.n_accel + self.margin
        o.T_j = np.full(max(np.size(obs.T_j), self.cfg.n_accel), est)
        o.T_j_peak = est
        return o

    def _decide(self, obs):
        cfg = self.cfg
        self._t = float(obs.t)
        v = self.val.check(obs)
        if self.last_cmd is None and not np.isfinite(obs.T_sup_actual):
            v["valid_sup"] = True            # before the first command there is no supply reading yet
        R_model = float(ph.r_total(self.last_flow, cfg))
        wanted = "NORMAL"
        for p in v["problems"]:
            self._alarm(p)
        if v["valid_T"] and v["valid_sup"] and np.isfinite(obs.T_sup_actual):
            r = float(np.mean(obs.T_j)) - float(obs.T_sup_actual) - R_model * float(obs.q_chips) / cfg.n_accel
            a = self.cusum.update(r, obs.t)
            if a == "residual_low" and not self.distrust_T:
                self.distrust_T, self.healthy_z = True, 0
                self._alarm("bias_low")
            elif a == "residual_high":
                self._alarm("residual_high")
            if self.distrust_T and self.cusum.mu0 is not None:
                z = (r - self.cusum.mu0) / self.cusum.sigma
                self.healthy_z = self.healthy_z + 1 if abs(z) < 1.0 else 0
                if self.healthy_z >= self.rec.clear_n:
                    self.distrust_T = False
                    self.cusum.reset()
            if not self.distrust_T and self.deg.update(obs, R_model):
                self._alarm("degradation")
        dR = max(self.deg.dR, 0.0) if self.deg.alarm_t is not None else 0.0
        s_app = getattr(obs, "s_applied", None)
        if s_app is not None and self.last_cmd is not None and max(abs(a - b) for a, b in zip(s_app, self.last_cmd)) > 0.05:
            self.mismatch += 1
        else:
            self.mismatch = 0
        if self.mismatch >= 2:
            self._alarm("actuation")
        if not v["valid_sup"] or self.mismatch >= 2:
            wanted = "SAFE"
        elif not v["valid_T"] or self.distrust_T:
            wanted = "DEGRADED"
        if self.deg.alarm_t is not None and wanted == "NORMAL":
            wanted = "NORMAL"            # degradation is handled by the filter's larger resistance, not a mode
        mode = self.rec.step(obs.t, wanted)
        o2 = self._substitute(obs, R_model + dR) if (not v["valid_T"] or self.distrust_T) else obs
        sup = float(obs.T_sup_actual) if v["valid_sup"] else None
        if mode == "SAFE":
            a = fallback_action(cfg, sup, "fallback-safe-mode")
        else:
            try:
                a = self._call_inner(o2)
            except Exception:  # noqa: BLE001
                self.n_exceptions += 1
                self._alarm("controller_exception")
                self.rec.step(obs.t, "SAFE")
                a = fallback_action(cfg, sup, "fallback-controller-exception")
        if abs(dR - self._dR_cfg) > 1e-4:
            self.filter.cfg = make_config({**{k: cfg[k] for k in cfg.keys()}, "r_cond": cfg.r_cond + dR})
            self._dR_cfg = dR
        if not np.isfinite(o2.T_sup_actual) and self.last_cmd is not None:
            o2 = copy.copy(o2)
            o2.T_sup_actual = cfg.t_sup_max          # the filter then assumes the warmest supply
        a = self.filter.validate(a, o2)
        self.last_cmd, self.last_flow = tuple(a.s), float(a.flow)
        return a

    def diagnostics(self) -> dict:
        d = {"first_alarm_t": -1.0 if self.first_any_t is None else self.first_any_t,
             "first_mode_change_t": -1.0 if self.rec.first_alarm_t is None else self.rec.first_alarm_t,
             "recovered_t": -1.0 if self.rec.recovered_t is None else self.rec.recovered_t,
             "safe_intervals": self.rec.intervals["SAFE"], "degraded_intervals": self.rec.intervals["DEGRADED"],
             "dR_final": self.deg.dR, "exceptions": self.n_exceptions,
             "degradation_alarm_t": -1.0 if self.deg.alarm_t is None else self.deg.alarm_t}
        for k, n in self.alarms.items():
            d[f"alarm_{k}"] = n
        if hasattr(self.inner, "diagnostics"):
            d.update({f"inner_{k}": v for k, v in self.inner.diagnostics().items()})
        return d
