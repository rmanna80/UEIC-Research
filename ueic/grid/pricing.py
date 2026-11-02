"""Electricity price profiles (illustrative; currency units per kWh). A lower bill is not lower energy."""
from __future__ import annotations

import numpy as np

PROFILES = {
    # name: (off-peak price, peak price, peak start h, peak end h)
    "flat": (0.15, 0.15, 0.0, 0.0),
    "tou": (0.10, 0.30, 16.0, 21.0),
}


def price(t_s: float, profile: str = "flat", event_price: float | None = None, windows=()) -> float:
    """Price at time t (s since midnight). During a demand-response window, ``event_price`` if given."""
    if event_price is not None and any(t0 <= t_s < t1 for t0, t1, *_ in windows):
        return event_price
    off, peak, h0, h1 = PROFILES[profile]
    h = (t_s / 3600.0) % 24
    return peak if h0 <= h < h1 else off


def cost(t: np.ndarray, P_W: np.ndarray, profile: str = "flat", **kw) -> float:
    """Integrated cost of a power trace (left Riemann sum over the sample spacing)."""
    t, P = np.asarray(t, dtype=float), np.asarray(P_W, dtype=float)
    dt = np.diff(t, append=t[-1] + (t[-1] - t[-2] if t.size > 1 else 1.0))
    return float(sum(P_i * d / 3.6e6 * price(ti, profile, **kw) for ti, P_i, d in zip(t, P, dt)))
