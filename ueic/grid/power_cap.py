"""Time-varying facility power caps (demand response) and compliance accounting.

A cap window is (t_start, t_end, cap_W) on *facility grid power* (IT / conversion + pumps + fans + chiller).
Enforcement in the facility simulator: the energy-management layer converts the grid cap into an IT power
limit using the previous step's non-IT power, and the power-capping layer scales clocks to it. Cooling
cannot be capped this way, so compliance depends on how much cooling power is running when the cap
begins (cooling inertia) and on whether stored cold can replace chiller work during the window.
"""
from __future__ import annotations

from typing import Sequence


def active_cap(t: float, windows: Sequence[Sequence[float]]) -> float | None:
    caps = [c for t0, t1, c in windows if t0 <= t < t1]
    return min(caps) if caps else None


class Compliance:
    """Accumulates energy above the cap, the largest exceedance and time out of compliance."""

    def __init__(self):
        self.E_above_J = 0.0
        self.max_exceed_W = 0.0
        self.t_out_s = 0.0
        self.E_event_J = 0.0
        self.t_event_s = 0.0

    def add(self, P_W: float, cap_W: float | None, dt: float) -> None:
        if cap_W is None:
            return
        self.E_event_J += P_W * dt
        self.t_event_s += dt
        over = P_W - cap_W
        if over > 0:
            self.E_above_J += over * dt
            self.t_out_s += dt
            self.max_exceed_W = max(self.max_exceed_W, over)
