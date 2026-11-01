"""Residual monitoring with a two-sided CUSUM on a physical-consistency residual.

Residual (K): r = mean(T_j) - [T_sup + R_model(flow) q / N]       (measured minus lumped steady model)
The baseline mean mu0 and scale sigma are learned over the first ``n_learn`` valid intervals (assumed
fault-free; a fault inside the learning window is a stated failure mode). sigma is the upper 90% confidence
bound of the sample standard deviation (chi-square), because a CUSUM tuned with an underestimated sigma
raises false alarms far more often than its nominal design. Then
    S+ = max(0, S+ + (r - mu0)/sigma - k),   S- = max(0, S- - (r - mu0)/sigma - k)
and an alarm is raised when S+ or S- exceeds h. S+ catches readings or resistance drifting high
(fouling, low flow); S- catches readings biased low (the dangerous direction). k = 0.5 is the
textbook choice for detecting a 1-sigma shift; h = 8 (rather than the common 4-5) trades a slightly longer
detection delay for a lower false-alarm rate. Stated, not tuned on fault data.
"""
from __future__ import annotations

import numpy as np


class ResidualCUSUM:
    def __init__(self, k: float = 0.5, h: float = 8.0, n_learn: int = 20, sigma_floor: float = 0.2):
        self.k, self.h, self.n_learn, self.sigma_floor = k, h, n_learn, sigma_floor
        self.hist: list[float] = []
        self.mu0 = self.sigma = None
        self.Sp = self.Sm = 0.0
        self.alarm: str | None = None
        self.alarm_t: float | None = None

    def update(self, r: float, t: float) -> str | None:
        if not np.isfinite(r):
            return self.alarm
        if self.mu0 is None:
            self.hist.append(r)
            if len(self.hist) >= self.n_learn:
                self.mu0 = float(np.mean(self.hist))
                from scipy.stats import chi2
                n = len(self.hist)
                s_up = float(np.std(self.hist, ddof=1)) * np.sqrt((n - 1) / chi2.ppf(0.10, n - 1))
                self.sigma = max(s_up, self.sigma_floor)
            return None
        z = (r - self.mu0) / self.sigma
        self.Sp = max(0.0, self.Sp + z - self.k)
        self.Sm = max(0.0, self.Sm - z - self.k)
        new = "residual_high" if self.Sp > self.h else ("residual_low" if self.Sm > self.h else None)
        if new and self.alarm is None:
            self.alarm, self.alarm_t = new, t
        return new

    def reset(self) -> None:
        self.Sp = self.Sm = 0.0
        self.alarm = self.alarm_t = None
