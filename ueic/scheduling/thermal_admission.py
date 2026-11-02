"""Thermal admission: start a job now (possibly at a lower clock) or hold it.

Rule (stated, not optimised):
  * if some placement has credit >= 0 at full clock, start it;
  * else, if some lower clock s in the allowed set gives credit >= 0 and the job still meets its
    deadline at that clock (remaining time >= work / s^beta), start it at the highest such clock;
  * else, if the job can still wait ``hold_s`` and meet its deadline at full clock, hold it;
  * else start it on the best-credit placement at full clock and let the hardware throttle protect
    the chip (the deadline is at risk either way; throttling is the independent safety layer).
"""
from __future__ import annotations


def admit(best_full: tuple | None, best_reduced: tuple | None, slack_s: float, nominal_s: float,
          hold_s: float) -> tuple[str, tuple | None]:
    """best_* = (credit, gpus, s) or None. Returns (decision, placement) with decision in
    'start', 'start_reduced', 'hold', 'start_over_budget'."""
    if best_full is not None and best_full[0] >= 0:
        return "start", best_full
    if best_reduced is not None and best_reduced[0] >= 0:
        return "start_reduced", best_reduced
    if slack_s - hold_s >= nominal_s:
        return "hold", None
    return ("start_over_budget", best_full) if best_full is not None else ("hold", None)
