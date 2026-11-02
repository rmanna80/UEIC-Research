"""Local identifiability from the Fisher information (Stage 1, Part 2.2; used in Stage 2).

For a model y = f(theta) + e with independent Gaussian noise of standard deviation sigma, the
Fisher information about theta is
    F = J^T J / sigma^2,     J_ij = d f_i / d theta_j   (sensitivity matrix, evaluated at theta)
Its inverse is the Cramer-Rao lower bound on the covariance of any unbiased estimator. A parameter
direction v with a tiny eigenvalue of F cannot be pinned down by the data: the model output barely
changes along v. That is what happened in the RTX 5070 warm-ups, where a 4-9 K window could not
separate the leakage power from its temperature coefficient.

Reported per parameter: the CRLB standard error, its ratio to |theta|, and a verdict. The verdicts
are judgements with stated thresholds, not theorems: "identifiable" if the relative CRLB error is
below ``rel_tol`` and the direction is not part of a near-null space of F.

Limitations: local (linearised at theta); assumes the noise model; says nothing about bias from a
wrong model form (structural uncertainty), which needs validation on held-out data.
"""
from __future__ import annotations

from typing import Callable, Sequence

import numpy as np


def numerical_jacobian(f: Callable[[np.ndarray], np.ndarray], theta: Sequence[float], rel_step: float = 1e-6,
                       abs_step: float = 1e-9) -> np.ndarray:
    """Central-difference sensitivity matrix of f at theta (rows: outputs, columns: parameters)."""
    th = np.asarray(theta, dtype=float)
    y0 = np.asarray(f(th), dtype=float).ravel()
    J = np.empty((y0.size, th.size))
    for j in range(th.size):
        h = max(abs(th[j]) * rel_step, abs_step)
        tp, tm = th.copy(), th.copy()
        tp[j] += h
        tm[j] -= h
        J[:, j] = (np.asarray(f(tp), dtype=float).ravel() - np.asarray(f(tm), dtype=float).ravel()) / (2 * h)
    return J


def fisher_information(J: np.ndarray, sigma: float | np.ndarray) -> np.ndarray:
    J = np.asarray(J, dtype=float)
    w = 1.0 / np.asarray(sigma, dtype=float) ** 2
    w = np.broadcast_to(w, (J.shape[0],))
    return J.T @ (J * w[:, None])


def identifiability(J: np.ndarray, names: Sequence[str], theta: Sequence[float], sigma: float | np.ndarray,
                    rel_tol: float = 0.5, null_tol: float = 1e-10) -> dict:
    """Identifiability report from the sensitivity matrix J (see module docstring)."""
    th = np.asarray(theta, dtype=float)
    F = fisher_information(J, sigma)
    # scale to relative parameters so eigenvalues are comparable across units
    S = np.diag(np.where(th != 0, np.abs(th), 1.0))
    Fs = S @ F @ S
    evals, evecs = np.linalg.eigh(Fs)
    lam_max = float(max(evals.max(), 0.0))
    null_dirs = []
    for lam, v in zip(evals, evecs.T):
        if lam <= null_tol * max(lam_max, 1e-300):
            top = np.argsort(-np.abs(v))[:3]
            null_dirs.append({"eigenvalue": float(lam),
                              "mix": {names[i]: float(v[i]) for i in top if abs(v[i]) > 0.1}})
    cond = float(evals.max() / evals.min()) if evals.min() > 0 else float("inf")
    try:
        cov = np.linalg.inv(F) if not null_dirs else np.linalg.pinv(F)
        se = np.sqrt(np.clip(np.diag(cov), 0.0, None))
        d = np.sqrt(np.outer(np.diag(cov), np.diag(cov)))
        corr = np.where(d > 0, cov / np.where(d > 0, d, 1.0), 0.0)
    except np.linalg.LinAlgError:
        se = np.full(th.size, np.inf)
        corr = np.full((th.size, th.size), np.nan)
    in_null = set()
    for nd in null_dirs:
        in_null.update(nd["mix"])
    params = []
    for i, n in enumerate(names):
        rel = float(se[i] / abs(th[i])) if th[i] != 0 else float("inf")
        if n in in_null:
            rel = float("inf")
        params.append({"name": n, "value": float(th[i]), "crlb_se": float(se[i]) if n not in in_null else float("inf"),
                       "rel_se": rel, "identifiable": bool(rel < rel_tol)})
    return {"rank": int(np.sum(evals > null_tol * max(lam_max, 1e-300))), "n_params": int(th.size),
            "condition_number": cond, "null_directions": null_dirs, "parameters": params,
            "correlation": corr.tolist(), "rel_tol": rel_tol,
            "method": "Fisher information J^T J / sigma^2 at theta; CRLB standard errors; local, Gaussian noise"}


def leakage_warmup_identifiability(T_window: tuple[float, float], P_mean: float, kappa: float, leak_frac: float,
                                   sigma_W: float, n: int, T_ref: float = 60.0) -> dict:
    """Identifiability of P(T) = c + L exp(kappa (T - T_ref)) from n samples spread over a temperature window.

    Uses the model the calibration fits (``calibrate.fit_leakage``) at a stated true point: total power
    P_mean at mid-window, of which ``leak_frac`` is leakage.

    ``n`` must be the number of *independent* samples. Telemetry logged at 10 Hz is strongly
    autocorrelated, and NVML reports whole degrees, so a warm-up spanning 9 K carries roughly as many
    independent temperature levels as kelvins, not thousands of samples. Passing the raw sample
    count gives an over-optimistic bound."""
    T = np.linspace(T_window[0], T_window[1], n)
    Tm = 0.5 * (T_window[0] + T_window[1])
    L = leak_frac * P_mean / np.exp(kappa * (Tm - T_ref))
    c = P_mean - leak_frac * P_mean
    theta = np.array([c, L, kappa])
    f = lambda th: th[0] + th[1] * np.exp(th[2] * (T - T_ref))   # noqa: E731
    J = numerical_jacobian(f, theta)
    return identifiability(J, ["c_W", "L_ref_W", "kappa"], theta, sigma_W)
