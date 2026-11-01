"""Coordinated compute control helpers: clock within a thermal budget, deadline-aware batching.

  max_clock_within_budget  the highest clock in a set whose predicted power fits a power budget (W);
                           used to lower a job's clock instead of letting the hardware throttle it.
  edf_batches              group requests into batches of at most ``max_batch`` in earliest-deadline-first
                           order, closing a batch early if waiting for more would make its first request late.
"""
from __future__ import annotations

from typing import Callable, Sequence


def max_clock_within_budget(power_fn: Callable[[float], float], budget_W: float,
                            clocks: Sequence[float] = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5)) -> float | None:
    for s in sorted(clocks, reverse=True):
        if power_fn(s) <= budget_W:
            return s
    return None


def edf_batches(requests: Sequence[dict], max_batch: int, batch_time_s: Callable[[int], float],
                now: float) -> list[list[dict]]:
    """requests: dicts with 'arrival' and 'deadline'. Returns batches in execution order (all requests)."""
    if max_batch < 1:
        raise ValueError("max_batch must be >= 1")
    q = sorted(requests, key=lambda r: r["deadline"])
    out, t = [], now
    while q:
        b = [q.pop(0)]
        while q and len(b) < max_batch and t + batch_time_s(len(b) + 1) <= b[0]["deadline"]:
            b.append(q.pop(0))
        out.append(b)
        t += batch_time_s(len(b))
    return out
