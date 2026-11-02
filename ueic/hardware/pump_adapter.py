"""Pump speed actuator. Only a simulated pump exists: no real pump driver is written until a controllable
loop with an independent flow interlock is built and reviewed (docs/23). Writes go through
``permissions.GuardedSession`` and are limited to the declared range and step."""
from __future__ import annotations

from .hardware_registry import Capabilities, register
from .permissions import Mode


@register
class MockPump:
    """Simulated variable-speed pump (fraction of rated speed)."""
    kind = "mock_pump"
    MODES = (Mode.SIMULATION, Mode.OPERATOR)

    def __init__(self, speed: float = 0.8):
        self.speed = speed
        self.capabilities = Capabilities(
            "mock_pump", self.kind, {"speed": "-"},
            {"speed": {"range": (0.3, 1.0), "max_step": 0.2, "safe": 1.0}},
            {"min_speed": 0.3, "interlock": "independent low-flow switch (assumed on real hardware)"},
            "simulated pump", "simulation", "n/a", self.MODES)

    def read(self):
        return {"speed": self.speed}

    def read_setpoint(self, actuation: str):
        return self.speed

    def write(self, actuation: str, value: float):
        prev = self.speed
        self.speed = float(value)
        safe = self.capabilities.writes["speed"]["safe"]
        def restore():
            self.speed = safe if safe is not None else prev
        return restore
