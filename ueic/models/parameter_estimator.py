"""Parameter estimation front end (Stage 2): one place that turns telemetry into parameter estimates with
uncertainty, diagnostics and an identifiability verdict, so callers never get a bare number.

  estimate_thermal_rc(t, T, P)  first-order R, C, tau and inlet temperature from a power step (batch OLS),
                                with delta-method standard errors, Durbin-Watson and quantisation warnings,
                                and a Fisher-information identifiability check of (a, b, d)
"""
from __future__ import annotations

import numpy as np

from .identifiability import identifiability
from .system_identification import fit_first_order_thermal


def estimate_thermal_rc(t, T, P, resample_s: float | None = None) -> dict:
    t, T, P = (np.asarray(v, dtype=float) for v in (t, T, P))
    if resample_s:
        grid = np.arange(t[0], t[-1], resample_s)
        T, P, t = np.interp(grid, t, T), np.interp(grid, t, P), grid
    fit = fit_first_order_thermal(t, T, P)
    X = np.column_stack([T[:-1], P[:-1], np.ones(T.size - 1)])
    sigma = max(fit.rmse_K, 1e-6)
    ident = identifiability(X, ["a", "b", "d"], [fit.a, fit.b, fit.d], sigma)
    return {"R_K_per_W": fit.R_K_per_W, "tau_s": fit.tau_s, "C_J_per_K": fit.C_J_per_K, "T_in_C": fit.T_in_C,
            "se": fit.se, "n": fit.n, "rmse_K": fit.rmse_K, "durbin_watson": fit.durbin_watson,
            "warnings": fit.warnings, "identifiability": ident,
            "method": "first-order ARX T[k+1] = a T[k] + b P[k] + d by OLS; R = b/(1-a), tau = -h/ln a"}
