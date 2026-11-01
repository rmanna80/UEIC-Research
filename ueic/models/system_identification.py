"""System identification from telemetry (Stage 2).

Methods are chosen for what the available signals can identify, not for sophistication:

1. First-order thermal ARX (batch least squares). A lumped node C dT/dt = P - (T - T_in)/R sampled
   every h seconds with P held over the sample is exactly
        T[k+1] = a T[k] + b P[k] + d,    a = exp(-h/(R C)),  b = R (1 - a),  d = T_in (1 - a)
   so R = b / (1 - a), tau = R C = -h / ln a, C = tau / R and T_in = d / (1 - a). Standard errors come from
   the OLS covariance mapped through the delta method. Identifiability needs a power *change* (a step or
   sweep): at constant power only the steady state T_in + R P is seen, and R, T_in are confounded.
   Warnings are raised for quantised temperatures (whole degrees from NVML), short records and
   autocorrelated residuals (Durbin-Watson far from 2 means the OLS errors are optimistic).

2. Recursive least squares with exponential forgetting (lambda in (0, 1]) for slowly drifting
   parameters, e.g. a cold-plate resistance that grows with fouling:
        K = P_k x / (lambda + x' P_k x),  theta += K (y - x' theta),  P_k = (P_k - K x' P_k) / lambda
   The covariance P_k * sigma^2 gives an uncertainty; with forgetting it does not shrink to zero, which is
   what lets the estimate follow drift. The effective memory is about 1 / (1 - lambda) samples.

3. Steady-state resistance from the simulator's observations (``ResistanceEstimator``): the mean junction
   rise over supply per watt of mean chip heat, y = mean(T_j) - T_sup, x = q_chips / N, fitted by RLS.
   Biased while temperatures are still moving (thermal capacitance); the bias is small when the chip
   time constant (~25 s here) is short against the control interval (60 s), and it is reported, not hidden.

Extended/unscented Kalman filtering was considered for joint state-parameter estimation; with one
temperature per chip, measured power and a single resistance to track, RLS on the linear regression
above is sufficient and easier to audit, so the EKF is not implemented (documented in docs/15).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ThermalFit:
    a: float
    b: float
    d: float
    R_K_per_W: float
    tau_s: float
    C_J_per_K: float
    T_in_C: float
    se: dict
    n: int
    rmse_K: float
    durbin_watson: float
    warnings: list


def fit_first_order_thermal(t, T, P, min_power_change_W: float = 5.0) -> ThermalFit:
    """Batch OLS fit of the discrete first-order model (see module docstring). t in s (uniform), T in degC, P in W."""
    t, T, P = (np.asarray(v, dtype=float) for v in (t, T, P))
    if not (t.size == T.size == P.size) or t.size < 20:
        raise ValueError("need equal-length records with at least 20 samples")
    h = float(np.median(np.diff(t)))
    if h <= 0 or np.max(np.abs(np.diff(t) - h)) > 0.25 * h:
        raise ValueError("samples must be (nearly) uniform in time; resample first")
    warnings = []
    if np.ptp(P) < min_power_change_W:
        warnings.append(f"power varies by only {np.ptp(P):.1f} W: R and T_in are not separately identifiable")
    if np.all(T == np.round(T)):
        warnings.append("temperature is quantised to whole degrees; small-step dynamics are poorly resolved")
    X = np.column_stack([T[:-1], P[:-1], np.ones(T.size - 1)])
    y = T[1:]
    theta, *_ = np.linalg.lstsq(X, y, rcond=None)
    a, b, d = (float(v) for v in theta)
    resid = y - X @ theta
    n, k = X.shape
    s2 = float(resid @ resid) / max(n - k, 1)
    cov = s2 * np.linalg.pinv(X.T @ X)
    dw = float(np.sum(np.diff(resid) ** 2) / max(resid @ resid, 1e-300))
    if not 1.5 <= dw <= 2.5:
        warnings.append(f"Durbin-Watson {dw:.2f}: residuals autocorrelated, standard errors are optimistic")
    if not 0.0 < a < 1.0:
        warnings.append(f"a = {a:.4f} outside (0, 1): no stable first-order fit")
        nan = float("nan")
        return ThermalFit(a, b, d, nan, nan, nan, nan, {}, n, float(np.sqrt(np.mean(resid ** 2))), dw, warnings)
    R = b / (1 - a)
    tau = -h / np.log(a)
    C = tau / R if R != 0 else float("nan")
    T_in = d / (1 - a)
    # delta method: gradients of (R, tau, T_in) w.r.t. (a, b, d)
    gR = np.array([b / (1 - a) ** 2, 1 / (1 - a), 0.0])
    gtau = np.array([h / (a * np.log(a) ** 2), 0.0, 0.0])
    gTin = np.array([d / (1 - a) ** 2, 0.0, 1 / (1 - a)])
    se = {name: float(np.sqrt(max(g @ cov @ g, 0.0))) for name, g in (("R", gR), ("tau", gtau), ("T_in", gTin))}
    if t.size * h < 3 * tau:
        warnings.append(f"record ({t.size * h:.0f} s) shorter than 3 time constants ({tau:.0f} s)")
    return ThermalFit(a, b, d, float(R), float(tau), float(C), float(T_in), se, n,
                      float(np.sqrt(np.mean(resid ** 2))), dw, warnings)


class RecursiveLeastSquares:
    """RLS with exponential forgetting. ``sigma2`` is a running estimate of the residual variance."""

    def __init__(self, n: int, lam: float = 0.98, theta0=None, p0: float = 1e3):
        if not 0 < lam <= 1:
            raise ValueError("forgetting factor must be in (0, 1]")
        self.lam = lam
        self.theta = np.zeros(n) if theta0 is None else np.asarray(theta0, dtype=float).copy()
        self.P = np.eye(n) * p0
        self.sigma2 = 0.0
        self.n_updates = 0

    def update(self, x, y: float) -> float:
        x = np.asarray(x, dtype=float)
        e = float(y - x @ self.theta)
        Px = self.P @ x
        K = Px / (self.lam + x @ Px)
        self.theta = self.theta + K * e
        self.P = (self.P - np.outer(K, Px)) / self.lam
        self.n_updates += 1
        w = 1.0 / min(self.n_updates, 1.0 / (1.0 - self.lam) if self.lam < 1 else self.n_updates)
        self.sigma2 = (1 - w) * self.sigma2 + w * e * e
        return e

    def se(self) -> np.ndarray:
        return np.sqrt(np.clip(np.diag(self.P) * max(self.sigma2, 0.0), 0.0, None))


class ResistanceEstimator:
    """Online estimate of the excess junction-to-supply resistance Delta_R over a model's R_total(flow),
    from simulator observations, with RLS forgetting:
        y = mean(T_j) - T_sup - R_model(flow) * x,   x = q_chips / N   (mean heat per chip, W)
        y = Delta_R * x
    Delta_R > 0 means the cold plates conduct worse than the model assumes (fouling, low flow)."""

    def __init__(self, n_accel: int, lam: float = 0.95, min_heat_W: float = 50.0):
        self.N = n_accel
        self.rls = RecursiveLeastSquares(1, lam=lam, theta0=[0.0], p0=1e-4)
        self.min_heat = min_heat_W
        self.history: list[tuple[float, float, float]] = []      # (t, Delta_R, se)

    def update(self, obs, R_model: float) -> float:
        if obs.T_j is None or np.size(obs.T_j) == 0 or not np.isfinite(obs.T_sup_actual) or not np.all(np.isfinite(obs.T_j)):
            return float(self.rls.theta[0])
        x = float(obs.q_chips) / self.N
        if x < self.min_heat:
            return float(self.rls.theta[0])
        y = float(np.mean(obs.T_j)) - float(obs.T_sup_actual) - R_model * x
        self.rls.update([x], y)
        dR = float(self.rls.theta[0])
        self.history.append((float(obs.t), dR, float(self.rls.se()[0])))
        return dR


def fit_step_response(t, T, dP_W: float, t_fit_s: float = 20.0, quantum_K: float | None = 1.0) -> dict:
    """Fast thermal time constant from the start of a power step (nonlinear least squares).

    Model over the first ``t_fit_s`` seconds after the step (t = 0 at the step):
        T(t) = T0 + A (1 - exp(-t / tau)) + B t
    A/dP is the fast (die-side) thermal resistance; B t absorbs the start of the slow heatsink/loop rise.
    With whole-degree readings the quantisation noise has standard deviation quantum/sqrt(12); the
    standard errors use the residual scale but a quantised record should be read as indicative."""
    from scipy.optimize import curve_fit
    t, T = np.asarray(t, dtype=float), np.asarray(T, dtype=float)
    m = (t >= 0) & (t <= t_fit_s) & np.isfinite(T)
    t, T = t[m], T[m]
    if t.size < 20:
        raise ValueError("too few samples after the step")
    T0 = float(T[0])
    f = lambda x, A, tau, B: T0 + A * (1 - np.exp(-x / tau)) + B * x   # noqa: E731
    p0 = (max(T.max() - T0, 1.0), 2.0, 0.05)
    popt, pcov = curve_fit(f, t, T, p0=p0, bounds=([0, 0.05, -5], [200, t_fit_s, 5]), maxfev=20000)
    se = np.sqrt(np.clip(np.diag(pcov), 0, None))
    resid = T - f(t, *popt)
    warnings = []
    if quantum_K and np.all(T == np.round(T / quantum_K) * quantum_K):
        warnings.append(f"temperatures quantised to {quantum_K} K; tau below ~1 s is poorly resolved")
    if popt[1] >= 0.9 * t_fit_s:
        warnings.append("tau at the edge of the fit window: not identified")
    return {"A_K": float(popt[0]), "tau_s": float(popt[1]), "B_K_per_s": float(popt[2]),
            "R_fast_K_per_W": float(popt[0] / dP_W) if dP_W else float("nan"),
            "se": {"A_K": float(se[0]), "tau_s": float(se[1]), "B_K_per_s": float(se[2])},
            "rmse_K": float(np.sqrt(np.mean(resid ** 2))), "n": int(t.size), "T0_C": T0, "dP_W": float(dP_W),
            "warnings": warnings, "method": "T0 + A(1 - exp(-t/tau)) + B t over the first seconds after a power step"}
