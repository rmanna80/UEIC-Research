"""Model drift detection on prediction residuals (Stage 2).

Page-Hinkley test for an upward shift in the mean of residuals e_k = measured - predicted (for example,
measured minus predicted peak junction temperature). With running mean m_k of e,
    U_k = sum_{i<=k} (e_i - m_i - delta),   alarm when U_k - min_{i<=k} U_i > lambda.
delta is the smallest drift worth detecting (K); lambda sets the false-alarm/delay trade-off (K).
Both are design choices stated with each experiment, not tuned on its results.
"""
from __future__ import annotations

import numpy as np


class PageHinkley:
    def __init__(self, delta: float = 0.5, lam: float = 10.0, burn_in: int = 5):
        if delta < 0 or lam <= 0:
            raise ValueError("need delta >= 0 and lambda > 0")
        self.delta, self.lam, self.burn_in = delta, lam, burn_in
        self.n = 0
        self.mean = 0.0
        self.U = 0.0
        self.U_min = 0.0
        self.alarm_at: float | None = None

    def update(self, e: float, t: float | None = None) -> bool:
        if not np.isfinite(e):
            return self.alarm_at is not None
        self.n += 1
        self.mean += (e - self.mean) / self.n
        if self.n <= self.burn_in:
            return False
        self.U += e - self.mean - self.delta
        self.U_min = min(self.U_min, self.U)
        if self.alarm_at is None and self.U - self.U_min > self.lam:
            self.alarm_at = t if t is not None else float(self.n)
        return self.alarm_at is not None
