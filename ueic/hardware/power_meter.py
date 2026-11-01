"""Wall / PDU power meters. Boundary: whatever the meter is wired to measure (record it per session)."""
from __future__ import annotations

from ._sensors import CsvIngestSensor, SimulatedSensor
from .hardware_registry import register


@register
class CsvPowerMeter(CsvIngestSensor):
    """Power meter whose own software logs to CSV (read-only ingest)."""
    kind = "csv_power_meter"

    def __init__(self, path: str, column: str = "power_W", device_id: str = "wall_meter",
                 boundary: str = "wall outlet of the host (meter as installed)"):
        super().__init__(path, column, "power_W", "W", device_id, boundary)


@register
class MockPowerMeter(SimulatedSensor):
    """Simulated power meter around a callable true power."""
    kind = "mock_power_meter"

    def __init__(self, truth=lambda: 300.0, accuracy: float = 1.0, seed: int = 0):
        super().__init__("power_W", "W", "mock_meter", "simulated host wall power", truth, accuracy, seed)
