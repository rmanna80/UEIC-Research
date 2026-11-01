"""Propagating parameter uncertainty to predictions (Stage 1, Part 2.2).

Two methods, with their assumptions stated:
  Delta method (linearised):   Var[g] ~= J Sigma J^T,  J = dg/dtheta at the estimate.
                               Valid when g is close to linear over the uncertainty; cheap.
  Monte Carlo:                 draw theta from a ParameterSet (normal for measured values,
                               uniform over sensitivity ranges for placeholders), evaluate g,
                               report percentiles. A percentile band from uniform placeholder
                               ranges is a stress-test envelope, not a credible interval, and is
                               labelled as such.
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from .parameter_registry import ParameterSet


def delta_method(J, cov) -> np.ndarray:
    J, cov = np.atleast_2d(np.asarray(J, dtype=float)), np.asarray(cov, dtype=float)
    return J @ cov @ J.T


def monte_carlo(g: Callable[[dict], float], ps: ParameterSet, n: int, seed: int = 0,
                names: list[str] | None = None, levels=(2.5, 50.0, 97.5)) -> dict:
    """Percentiles of g over joint parameter draws. ``g`` may raise ValueError for a non-physical draw;
    such draws are counted and excluded (reported, never silently dropped)."""
    draws = ps.sample(n, np.random.default_rng(seed), names)
    vals, rejected = [], 0
    for d in draws:
        try:
            vals.append(float(g(d)))
        except ValueError:
            rejected += 1
    names = names or ps.uncertain()
    has_range = any(ps[k].kind == "range" for k in names)
    v = np.asarray(vals)
    return {"n": n, "n_rejected": rejected, "percentiles": dict(zip([str(x) for x in levels],
                                                                   np.percentile(v, levels).tolist())) if v.size else {},
            "mean": float(v.mean()) if v.size else float("nan"),
            "interpretation": "stress-test envelope (includes uniform placeholder ranges)" if has_range
            else "propagated measurement uncertainty"}
