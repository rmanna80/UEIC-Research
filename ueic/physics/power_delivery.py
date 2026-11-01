"""Power conversion losses vs load (Stage 1 component; the simulator still uses constant eta_conv).

Standard three-term loss model for a converter chain (UPS, PSU, voltage regulators) [E form]:
    P_loss(P_out) = P_0 + k_1 * P_out + k_2 * P_out**2 / P_rated                      W
    eta(P_out) = P_out / (P_out + P_loss)
P_0 is the no-load (fixed) loss, k_1 the proportional loss, k_2 the resistive (I^2 R) loss at
rated power. Efficiency rises from zero, peaks where P_out = P_rated * sqrt(P_0 / (k_2 P_rated)),
and falls at high load. Coefficients are class F unless taken from a datasheet curve.

``coefficients_for_constant(eta)`` gives the loss model equal to the legacy constant efficiency
(P_0 = k_2 = 0, k_1 = 1/eta - 1), so the component can replace the constant without changing results.
"""
from __future__ import annotations

import numpy as np


def loss(P_out, P_rated: float, P0: float, k1: float, k2: float):
    P = np.asarray(P_out, dtype=float)
    if np.any(P < 0) or P_rated <= 0 or min(P0, k1, k2) < 0:
        raise ValueError("need P_out >= 0, P_rated > 0 and non-negative loss coefficients")
    return P0 + k1 * P + k2 * P ** 2 / P_rated


def efficiency(P_out, P_rated: float, P0: float, k1: float, k2: float):
    P = np.asarray(P_out, dtype=float)
    L = loss(P, P_rated, P0, k1, k2)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(P > 0, P / (P + L), 0.0)


def coefficients_for_constant(eta: float) -> dict[str, float]:
    if not 0 < eta <= 1:
        raise ValueError("eta must be in (0, 1]")
    return {"P0": 0.0, "k1": 1.0 / eta - 1.0, "k2": 0.0}
