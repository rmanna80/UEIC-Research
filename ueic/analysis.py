"""Statistics for paired policy comparisons.

All comparisons are paired by seed: each seed is one workload realisation that
every policy sees. For a metric M, policy A and reference B, the per-seed
relative difference is d_i = (M_A,i - M_B,i) / M_B,i. We report the mean of d
and a two-sided 95% Student-t confidence interval. Negative = A uses less.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

import numpy as np
from scipy import stats


def t_ci(x: np.ndarray, level: float = 0.95) -> tuple[float, float, float]:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = x.size
    if n == 0:
        return np.nan, np.nan, np.nan
    m = float(x.mean())
    if n == 1:
        return m, np.nan, np.nan
    se = float(x.std(ddof=1)) / np.sqrt(n)
    h = float(stats.t.ppf(0.5 + level / 2, n - 1)) * se
    return m, m - h, m + h


def index_runs(runs: Iterable[dict[str, Any]], key=("scenario", "variant"), factor: str = "policy") -> dict:
    """{group: {factor_level: {seed: metrics}}} for completed runs."""
    out: dict = defaultdict(lambda: defaultdict(dict))
    for r in runs:
        if r["status"] != "completed":
            continue
        g = tuple(r[k] for k in key)
        out[g][r[factor]][r["seed"]] = r["metrics"]
    return out


def paired(runs, metric: str, a: str, b: str, key=("scenario", "variant"), factor: str = "policy",
           relative: bool = True) -> list[dict]:
    """Paired comparison of factor level `a` against reference level `b` within each group."""
    idx = index_runs(runs, key, factor)
    rows = []
    for g, lev in idx.items():
        if a not in lev or b not in lev:
            continue
        seeds = sorted(set(lev[a]) & set(lev[b]))
        va = np.array([lev[a][s].get(metric, np.nan) for s in seeds], dtype=float)
        vb = np.array([lev[b][s].get(metric, np.nan) for s in seeds], dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            d = (va - vb) / vb if relative else va - vb
        m, lo, hi = t_ci(d)
        rows.append({"group": g, "metric": metric, "a": a, "b": b, "factor": factor, "n": len(seeds),
                     "mean": m, "lo": lo, "hi": hi,
                     "mean_a": float(np.nanmean(va)) if va.size else np.nan,
                     "mean_b": float(np.nanmean(vb)) if vb.size else np.nan, "relative": relative})
    return rows


def summary(runs, metric: str, key=("scenario", "variant"), factor: str = "policy") -> list[dict]:
    idx = index_runs(runs, key, factor)
    rows = []
    for g, pol in idx.items():
        for p, by_seed in pol.items():
            v = np.array([m.get(metric, np.nan) for m in by_seed.values()], dtype=float)
            m, lo, hi = t_ci(v)
            rows.append({"group": g, factor: p, "metric": metric, "n": v.size, "mean": m, "lo": lo, "hi": hi})
    return rows


def verdict(row: dict, threshold: float) -> str:
    """Classify a relative paired difference against a practical-significance threshold."""
    if not np.isfinite(row["lo"]):
        return "insufficient data"
    if row["hi"] < -threshold:
        return "meaningful reduction (CI beyond threshold)"
    if row["hi"] < 0:
        return "detectable reduction, not confirmed >= threshold"
    if row["lo"] > threshold:
        return "meaningful increase (CI beyond threshold)"
    if row["lo"] > 0:
        return "detectable increase, not confirmed >= threshold"
    return "no detectable difference"
