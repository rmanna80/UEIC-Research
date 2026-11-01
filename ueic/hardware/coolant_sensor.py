"""Coolant temperature sensors (supply/return). Boundary: the pipe location where the probe sits."""
from __future__ import annotations

from ._sensors import CsvIngestSensor, SimulatedSensor
from .hardware_registry import register


@register
class CsvCoolantSensor(CsvIngestSensor):
    """Coolant temperature logged by a DAQ to CSV (read-only ingest)."""
    kind = "csv_coolant_sensor"

    def __init__(self, path: str, column: str = "T_C", device_id: str = "coolant_T", boundary: str = "probe location as installed"):
        super().__init__(path, column, "T_C", "degC", device_id, boundary)


@register
class MockCoolantSensor(SimulatedSensor):
    """Simulated coolant temperature sensor."""
    kind = "mock_coolant_sensor"

    def __init__(self, truth=lambda: 30.0, accuracy: float = 0.1, seed: int = 0):
        super().__init__("T_C", "degC", "mock_coolant_T", "simulated supply line", truth, accuracy, seed)
