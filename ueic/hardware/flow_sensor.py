"""Coolant flow sensors. Boundary: the branch the meter is installed in."""
from __future__ import annotations

from ._sensors import CsvIngestSensor, SimulatedSensor
from .hardware_registry import register


@register
class CsvFlowSensor(CsvIngestSensor):
    """Flow logged by a DAQ to CSV (read-only ingest)."""
    kind = "csv_flow_sensor"

    def __init__(self, path: str, column: str = "flow_lpm", device_id: str = "flow", boundary: str = "branch as installed"):
        super().__init__(path, column, "flow_lpm", "L/min", device_id, boundary)


@register
class MockFlowSensor(SimulatedSensor):
    """Simulated flow sensor."""
    kind = "mock_flow_sensor"

    def __init__(self, truth=lambda: 1.2, accuracy: float = 0.02, seed: int = 0):
        super().__init__("flow_lpm", "L/min", "mock_flow", "simulated loop", truth, accuracy, seed)
