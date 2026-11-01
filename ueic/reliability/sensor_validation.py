"""Telemetry plausibility checks (per control interval).

  dropout   any junction or supply reading not finite
  range     junction outside [T_lo, T_hi] or supply outside [0, 100] C
  rate      a junction changed faster than ``max_rate_K_per_s`` since the previous valid reading
            (the lumped chip cannot: |dT/dt| <= P_max / C, ~3 K/s for the registry chip)
  stale     junction readings bit-identical for ``stale_intervals`` consecutive intervals while the
            measured chip heat changed by more than ``stale_heat_frac`` (frozen telemetry)
  age       the newest telemetry sample (obs.telemetry_t, when the source stamps it) is older than
            ``max_age_s`` (communication loss)
Each check is a stated rule with a stated threshold, not a learned classifier.
"""
from __future__ import annotations

import numpy as np


class SensorValidator:
    def __init__(self, T_lo: float = -5.0, T_hi: float = 125.0, max_rate_K_per_s: float = 5.0,
                 stale_intervals: int = 3, stale_heat_frac: float = 0.02, max_age_s: float = 90.0):
        self.T_lo, self.T_hi, self.max_rate = T_lo, T_hi, max_rate_K_per_s
        self.stale_n, self.stale_frac, self.max_age = stale_intervals, stale_heat_frac, max_age_s
        self.prev_T: np.ndarray | None = None
        self.prev_t: float | None = None
        self.same_count = 0
        self.q_at_freeze: float | None = None

    def check(self, obs) -> dict:
        problems: list[str] = []
        ts = getattr(obs, "telemetry_t", None)
        if ts is not None and float(obs.t) - float(ts) > self.max_age:
            problems.append("age")
        T = np.asarray(obs.T_j, dtype=float)
        sup = float(obs.T_sup_actual)
        if T.size and not np.all(np.isfinite(T)):
            problems.append("dropout")
        elif T.size and (T.min() < self.T_lo or T.max() > self.T_hi):
            problems.append("range")
        if np.isfinite(sup) and not 0.0 <= sup <= 100.0:
            problems.append("supply_range")
        if T.size and np.all(np.isfinite(T)):
            if self.prev_T is not None and self.prev_T.shape == T.shape:
                dt = max(float(obs.t) - float(self.prev_t), 1e-9)
                if np.max(np.abs(T - self.prev_T)) / dt > self.max_rate:
                    problems.append("rate")
                if np.array_equal(T, self.prev_T):
                    self.same_count += 1
                    self.q_at_freeze = self.q_at_freeze if self.q_at_freeze is not None else float(obs.q_chips)
                    dq = abs(float(obs.q_chips) - self.q_at_freeze) / max(abs(self.q_at_freeze), 1.0)
                    if self.same_count >= self.stale_n - 1 and dq > self.stale_frac:
                        problems.append("stale")
                else:
                    self.same_count, self.q_at_freeze = 0, None
            self.prev_T, self.prev_t = T.copy(), float(obs.t)
        return {"valid_T": not any(p in problems for p in ("dropout", "range", "rate", "stale", "age")),
                "valid_sup": np.isfinite(sup) and "supply_range" not in problems and "age" not in problems,
                "problems": problems}
