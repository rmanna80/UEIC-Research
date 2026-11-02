"""Operating modes and recovery bookkeeping.

  NORMAL    the controller's action, through the safety monitor
  DEGRADED  junction readings replaced by a model estimate T_sup + (R_model + Delta_R) q/N + margin
            (analytical redundancy); controller still in charge
  SAFE      the approved conservative fallback (``control.fallback.fallback_action``): maximum flow,
            minimum supply, the highest-throughput clocks that are safe at the measured supply
A mode is left only after ``clear_intervals`` consecutive healthy intervals (hysteresis). Detection and
recovery times are recorded for analysis.
"""
from __future__ import annotations

ORDER = {"NORMAL": 0, "DEGRADED": 1, "SAFE": 2}


class RecoveryManager:
    def __init__(self, clear_intervals: int = 3):
        self.mode = "NORMAL"
        self.clear_n = clear_intervals
        self.healthy = 0
        self.first_alarm_t: float | None = None
        self.recovered_t: float | None = None
        self.intervals = {"NORMAL": 0, "DEGRADED": 0, "SAFE": 0}

    def step(self, t: float, wanted: str) -> str:
        """``wanted`` = the most severe mode the checks call for this interval."""
        if ORDER[wanted] > ORDER["NORMAL"] and self.first_alarm_t is None:
            self.first_alarm_t = t
        if ORDER[wanted] >= ORDER[self.mode]:
            self.mode, self.healthy = wanted, 0
        else:
            self.healthy += 1
            if self.healthy >= self.clear_n:
                self.mode, self.healthy = wanted, 0
                if wanted == "NORMAL" and self.first_alarm_t is not None and self.recovered_t is None:
                    self.recovered_t = t
        self.intervals[self.mode] += 1
        return self.mode
