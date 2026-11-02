"""Shared sensor patterns: a generic CSV-ingest sensor (read-only; for instruments whose own software logs
to a file) and a simulated sensor with declared accuracy. Device-specific drivers are not written until an
instrument is chosen (docs/23): no vendor protocol is assumed here."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np

from .hardware_registry import Capabilities
from .permissions import Mode


class CsvIngestSensor:
    MODES = (Mode.READ_ONLY, Mode.REPLAY)

    def __init__(self, path: str, column: str, quantity: str, unit: str, device_id: str, boundary: str,
                 calibration: str = "per instrument certificate (record it)"):
        self.path, self.column, self.quantity = Path(path), column, quantity
        self.capabilities = Capabilities(device_id, self.kind, {quantity: unit}, {}, {}, boundary,
                                         "physical_measurement", calibration, self.MODES)
        self._pos = 0

    def read(self) -> dict[str, Any] | None:
        """Newest complete row appended since the last read (None if nothing new)."""
        with open(self.path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if len(rows) <= self._pos:
            return None
        self._pos = len(rows)
        r = rows[-1]
        return {"t_unix": float(r.get("t_unix", "nan")), self.quantity: float(r[self.column])}


class SimulatedSensor:
    MODES = (Mode.SIMULATION,)

    def __init__(self, quantity: str, unit: str, device_id: str, boundary: str, truth, accuracy: float, seed: int = 0):
        self.quantity, self.truth, self.acc = quantity, truth, accuracy
        self.rng = np.random.default_rng(seed)
        self.capabilities = Capabilities(device_id, self.kind, {quantity: unit}, {}, {"accuracy": accuracy}, boundary,
                                         "simulation", f"simulated, +/-{accuracy} {unit} (1 sigma)", self.MODES)

    def read(self) -> dict[str, Any]:
        return {self.quantity: float(self.truth()) + float(self.rng.normal(0, self.acc))}
