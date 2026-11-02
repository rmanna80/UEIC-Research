"""Slow degradation: excess junction-to-supply resistance tracked online (Stage 2 RLS estimator).

An alarm is raised when the estimated excess resistance Delta_R exceeds ``threshold_K_per_W`` for
``n_confirm`` consecutive updates. Fouling, reduced coolant flow and a degraded pump all appear as
Delta_R > 0 because each raises the junction temperature per watt; the detector does not tell them
apart (a stated limitation; telling them apart needs flow or pressure measurements).
"""
from __future__ import annotations

from ..models.system_identification import ResistanceEstimator


class DegradationDetector:
    def __init__(self, n_accel: int, threshold_K_per_W: float = 0.01, n_confirm: int = 3, lam: float = 0.9):
        self.est = ResistanceEstimator(n_accel, lam=lam)
        self.th, self.n_confirm = threshold_K_per_W, n_confirm
        self.count = 0
        self.alarm_t: float | None = None
        self.dR = 0.0

    def update(self, obs, R_model: float) -> bool:
        self.dR = self.est.update(obs, R_model)
        self.count = self.count + 1 if self.dR > self.th else 0
        if self.count >= self.n_confirm and self.alarm_t is None:
            self.alarm_t = float(obs.t)
        return self.count >= self.n_confirm
