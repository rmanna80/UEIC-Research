"""Approved fallback action (Stage 3).

Used when the optimiser fails (exception, time budget exceeded, no candidate), when telemetry is
missing or invalid, or when the safety filter cannot repair a proposal. It needs no forecast and no
optimiser, only the steady chip model:

  flow        maximum allowed (lowest junction-to-coolant resistance)
  setpoint    t_sup_min (maximum cooling; the chiller covers what free cooling cannot)
  clocks      the highest clock pair that keeps every chip at or below t_target - safety_margin at the
              assumed supply temperature, where the assumed supply is the measured one if valid, else
              t_sup_max (worst case); if no pair is safe, the lowest clocks

The fallback can cost energy and throughput; it is meant to be safe and simple, not efficient.
Independent hardware protection (throttling at t_throttle in the simulator) stays in force regardless.
"""
from __future__ import annotations

import numpy as np

from ..policies import Action, f_grid, s_grid
from .futures import chip_states, temps_ok


def safest_clocks(cfg, T_assume: float, flow: float, margin: float = 0.0) -> tuple[tuple[float, float], bool]:
    """Highest (s_compute, s_memory) safe at supply T_assume and the given flow; (lowest, False) if none."""
    S = s_grid(cfg)
    st = chip_states(cfg, S[:, None], S[None, :], T_assume, flow)
    ok = temps_ok(st, cfg, margin)
    if not ok.any():
        return (float(S[0]), float(S[0])), False
    # most throughput first (s^beta per class), then the lowest clocks (least power) among equals:
    # with beta_memory = 0 a higher memory-bound clock buys nothing and is not chosen
    thr = S[:, None] ** cfg.beta_compute + S[None, :] ** cfg.beta_memory
    score = np.where(ok, np.round(thr, 9) - 1e-6 * (S[:, None] + S[None, :]), -np.inf)
    i, j = np.unravel_index(np.argmax(score), score.shape)
    return (float(S[i]), float(S[j])), True


def fallback_action(cfg, T_measured: float | None, reason: str) -> Action:
    T_assume = float(T_measured) if T_measured is not None and np.isfinite(T_measured) else float(cfg.t_sup_max)
    flow = float(f_grid(cfg).max())
    s, ok = safest_clocks(cfg, T_assume, flow, float(cfg.safety_margin_K))
    return Action(s, float(cfg.t_sup_min), flow, f"fallback:{reason}" + ("" if ok else ":no-safe-clock"))
