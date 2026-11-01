"""Held-out validation of model predictions (Stage 1, Part 2.2; used by Stages 2-3).

Metrics on held-out data (never on the data used to fit):
  RMSE = sqrt(mean((y - yhat)^2)),  MAE = mean|y - yhat|,  bias = mean(yhat - y),  max |error|
  Interval coverage: fraction of y inside [lo, hi]; a calibrated 95% interval should cover ~95%.
Model comparison adds complexity: AIC = n ln(RSS/n) + 2k, BIC = n ln(RSS/n) + k ln n (Gaussian errors).
A more complex model is preferred only if it lowers held-out error, not merely in-sample error
(the research plan's rule for machine-learning residual models).
"""
from __future__ import annotations

from typing import Callable, Sequence

import numpy as np


def holdout_metrics(y, yhat, lo=None, hi=None) -> dict:
    y, yhat = np.asarray(y, dtype=float), np.asarray(yhat, dtype=float)
    if y.shape != yhat.shape or y.size == 0:
        raise ValueError("y and yhat must be non-empty and the same shape")
    e = yhat - y
    out = {"n": int(y.size), "rmse": float(np.sqrt(np.mean(e ** 2))), "mae": float(np.mean(np.abs(e))),
           "bias": float(np.mean(e)), "max_abs": float(np.max(np.abs(e)))}
    if lo is not None and hi is not None:
        lo, hi = np.asarray(lo, dtype=float), np.asarray(hi, dtype=float)
        out["coverage"] = float(np.mean((y >= lo) & (y <= hi)))
    return out


def information_criteria(rss: float, n: int, k: int) -> dict:
    if n <= 0 or rss < 0:
        raise ValueError("need n > 0 and rss >= 0")
    rss = max(rss, 1e-300)
    return {"aic": float(n * np.log(rss / n) + 2 * k), "bic": float(n * np.log(rss / n) + k * np.log(n))}


def kfold_indices(n: int, k: int, seed: int = 0) -> list[tuple[np.ndarray, np.ndarray]]:
    if not 2 <= k <= n:
        raise ValueError("need 2 <= k <= n")
    idx = np.random.default_rng(seed).permutation(n)
    folds = np.array_split(idx, k)
    return [(np.concatenate([folds[j] for j in range(k) if j != i]), folds[i]) for i in range(k)]


def cross_validate(fit: Callable, predict: Callable, X, y, k: int = 5, seed: int = 0) -> dict:
    """k-fold cross-validated metrics for a model given fit(X, y) -> model and predict(model, X) -> yhat."""
    X, y = np.asarray(X, dtype=float), np.asarray(y, dtype=float)
    pred = np.empty_like(y)
    for tr, te in kfold_indices(len(y), k, seed):
        pred[te] = predict(fit(X[tr], y[tr]), X[te])
    return holdout_metrics(y, pred)


def compare(models: Sequence[dict]) -> list[dict]:
    """Rank candidate models by held-out RMSE; each dict needs name, k (parameters) and metrics."""
    return sorted(models, key=lambda m: (m["metrics"]["rmse"], m["k"]))
