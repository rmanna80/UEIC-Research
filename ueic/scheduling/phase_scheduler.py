"""Clock choice per execution phase (compute-bound vs memory-bound), e.g. LLM prefill vs decode.

For a phase with clock sensitivity beta and activity a, throughput ~ s^beta and energy per unit work is
    e(s) = P(s, T) / s^beta     (physics.gpu.energy_per_work)
The phase clock is the s that minimises e(s) subject to a throughput floor s^beta >= rho (from a
deadline or SLO). Memory-bound phases (small beta) lose little throughput at lower clocks, so their
energy-optimal clock is lower. Uses the registry's power model; with measured beta (M001: compute
~0.98 on the RTX 5070) it is a prediction for that GPU, not a measurement of a serving engine's phases.
"""
from __future__ import annotations

import numpy as np

from ..physics.gpu import energy_per_work


def phase_clock(cfg, memory_bound: bool, T: float, throughput_floor: float = 0.0, grid=None) -> dict:
    beta = cfg.beta_memory if memory_bound else cfg.beta_compute
    g = np.round(np.arange(cfg.s_min, 1.0 + 1e-9, 0.01), 6) if grid is None else np.asarray(grid, dtype=float)
    ok = g ** beta >= throughput_floor - 1e-12
    if not ok.any():
        return {"s": 1.0, "feasible": False, "beta": beta}
    e = energy_per_work(g, T, 1 if memory_bound else 0, cfg)
    e = np.where(ok, e, np.inf)
    i = int(np.argmin(e))
    e1 = float(energy_per_work(1.0, T, 1 if memory_bound else 0, cfg))
    return {"s": float(g[i]), "feasible": True, "beta": beta, "J_per_work": float(e[i]), "saving_vs_max": 1 - float(e[i]) / e1}


def phase_plan(cfg, phases: list[dict], T: float) -> list[dict]:
    """phases: [{"name", "memory_bound", "floor"}] -> clock per phase."""
    return [{"name": p["name"], **phase_clock(cfg, p["memory_bound"], T, p.get("floor", 0.0))} for p in phases]
