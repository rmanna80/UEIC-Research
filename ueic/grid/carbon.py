"""Carbon-intensity profiles (illustrative gCO2/kWh shapes, not grid data)."""
from __future__ import annotations

import numpy as np

PROFILES = {
    "flat": lambda h: 400.0,
    # solar-heavy shape: low around midday, high in the evening peak
    "diurnal": lambda h: 400.0 - 150.0 * np.exp(-((h - 13.0) / 3.0) ** 2) + 120.0 * np.exp(-((h - 19.0) / 2.0) ** 2),
}


def intensity(t_s: float, profile: str = "flat") -> float:
    return float(PROFILES[profile]((t_s / 3600.0) % 24))


def emissions_kg(E_kWh: float, gCO2_per_kWh: float) -> float:
    return E_kWh * gCO2_per_kWh / 1000.0
