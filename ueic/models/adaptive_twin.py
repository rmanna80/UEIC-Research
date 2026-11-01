"""Adaptive and periodically recalibrated twins for the joint controller (Stage 2, E016).

All three variants plan with joint_fb (steady-state joint control with the throughput-first overload
fallback), so they differ only in how the model's cold-plate resistance is kept up to date:

  joint_fb        fixed model (the registry/configured resistance)                       [baseline]
  joint_recal     every ``recal_interval_s`` the excess resistance Delta_R is refitted by least squares on
                  the observations since the last refit, and held until the next one
  joint_adaptive  Delta_R is updated by RLS with forgetting factor 0.95 (memory ~ 20 decisions) at every
                  decision

The model's r_cond is replaced by r_cond + max(Delta_R, 0): the model is only allowed to become *more*
conservative from data, never less, because an estimate below the configured value has not been
validated (a stated design choice). Each policy records its prediction error (measured peak junction
minus the twin's predicted steady peak for the action it took) and a Page-Hinkley drift alarm on those
residuals, exposed through ``diagnostics()``.
"""
from __future__ import annotations

import numpy as np

from .. import physics as ph
from .. import twin
from ..params import make_config
from ..policies import JointFallbackPolicy, planned_demand, predicted_peak
from .model_drift import PageHinkley
from .system_identification import ResistanceEstimator


class _TrackedJointFb(JointFallbackPolicy):
    name = "joint_fb_tracked"
    adapt = "none"
    recal_interval_s = 1800.0

    def __init__(self, model_cfg):
        super().__init__(model_cfg)
        self.base_cfg = model_cfg
        self.base = {k: v for k, v in model_cfg.items()}
        self.est = ResistanceEstimator(model_cfg.n_accel, lam=0.95)
        self.dR = 0.0
        self.pred_peak: float | None = None
        self.errors: list[float] = []
        self.ph = PageHinkley(delta=0.5, lam=10.0)
        self.batch: list[tuple[float, float]] = []
        self.next_recal = self.recal_interval_s
        self.last_flow = 1.0

    def _model(self):
        if self.dR <= 0:
            return self.base_cfg
        return make_config({**self.base, "r_cond": float(self.base["r_cond"]) + self.dR})

    def _decide(self, obs):
        cfg_now = self._model()
        if self.pred_peak is not None and np.isfinite(obs.T_j_peak):
            e = float(obs.T_j_peak) - self.pred_peak
            self.errors.append(e)
            self.ph.update(e, obs.t)
        R_model = float(ph.r_total(self.last_flow, cfg_now)) - self.dR      # the configured model's resistance
        if self.adapt == "rls":
            self.dR = max(self.est.update(obs, R_model), 0.0)
        elif self.adapt == "periodic":
            if np.size(obs.T_j) and np.isfinite(obs.T_sup_actual) and obs.q_chips / self.base_cfg.n_accel > 50:
                x = float(obs.q_chips) / self.base_cfg.n_accel
                self.batch.append((x, float(np.mean(obs.T_j)) - float(obs.T_sup_actual) - R_model * x))
            if obs.t >= self.next_recal and self.batch:
                X = np.array([b[0] for b in self.batch]); Y = np.array([b[1] for b in self.batch])
                self.dR = max(float(X @ Y / (X @ X)), 0.0)
                self.batch = []
                self.next_recal += self.recal_interval_s
        self.cfg = self._model()
        a = super()._decide(obs)
        self.last_flow = a.flow
        self.pred_peak = predicted_peak(self.cfg, planned_demand(obs, self.cfg), a, obs.T_amb)
        return a

    def diagnostics(self) -> dict[str, float]:
        e = np.array(self.errors) if self.errors else np.array([np.nan])
        return {"pred_peak_mae_K": float(np.nanmean(np.abs(e))), "pred_peak_bias_K": float(np.nanmean(e)),
                "pred_peak_under_frac": float(np.nanmean(e > 1.0)), "model_dR_final": float(self.dR),
                "drift_alarm_t_s": float(self.ph.alarm_at) if self.ph.alarm_at is not None else -1.0}


class FixedTrackedPolicy(_TrackedJointFb):
    """joint_fb with prediction-error diagnostics (identical decisions to joint_fb)."""
    name = "joint_fixed"
    adapt = "none"


class RecalibratedPolicy(_TrackedJointFb):
    name = "joint_recal"
    adapt = "periodic"


class AdaptivePolicy(_TrackedJointFb):
    name = "joint_adaptive"
    adapt = "rls"
