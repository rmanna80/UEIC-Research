"""Electrical constraints: rack and facility IT power limits enforced by a power-capping layer.

The capping layer is part of the simulated *hardware*: it acts after any controller or scheduler and
cannot be overridden by them (like a BMC/rack PDU cap). When a group's IT power exceeds its limit, the
clocks of that group's busy accelerators are multiplied by a common factor m in [s_min, 1], found by
bisection so that the group's power is within the limit (or m = s_min if even that is not enough).
"""
from __future__ import annotations

from typing import Callable

import numpy as np


def cap_group(s: np.ndarray, busy: np.ndarray, power_fn: Callable[[np.ndarray], np.ndarray], limit_W: float,
              s_min: float, iters: int = 30) -> tuple[np.ndarray, bool]:
    """Return capped clocks for one group and whether the cap was active."""
    if power_fn(s).sum() <= limit_W or not busy.any():
        return s, False
    lo, hi = 0.0, 1.0
    for _ in range(iters):
        m = 0.5 * (lo + hi)
        trial = np.where(busy, np.maximum(s_min, s * m), s)
        if power_fn(trial).sum() <= limit_W:
            lo = m
        else:
            hi = m
    return np.where(busy, np.maximum(s_min, s * lo), s), True
