"""Deferrable vs inflexible work (stated rule).

A queued job is *deferrable* at time t with respect to a set of cap windows if it could wait until the
active window ends and still finish by its deadline with a safety factor:
        deadline - t_window_end >= factor x remaining work (full-clock seconds)
Otherwise it is inflexible and is scheduled normally (and is then subject to the power cap like any job).
"""
from __future__ import annotations

from typing import Sequence


def window_end(t: float, windows: Sequence[Sequence[float]]) -> float | None:
    ends = [t1 for t0, t1, *_ in windows if t0 <= t < t1]
    return max(ends) if ends else None


def is_deferrable(job, t: float, windows: Sequence[Sequence[float]], factor: float = 1.5) -> bool:
    te = window_end(t, windows)
    return te is not None and job.deadline - te >= factor * job.remaining
