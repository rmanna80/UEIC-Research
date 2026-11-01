"""Cooling supply-temperature actuator (simulated only; see pump_adapter for the rule on real drivers)."""
from __future__ import annotations

from .hardware_registry import Capabilities, register
from .permissions import Mode


@register
class MockCoolingController:
    """Simulated supply-temperature setpoint of a chiller/CDU."""
    kind = "mock_cooling_controller"
    MODES = (Mode.SIMULATION, Mode.OPERATOR)

    def __init__(self, setpoint: float = 25.0):
        self.setpoint = setpoint
        self.capabilities = Capabilities(
            "mock_cdu", self.kind, {"T_set": "degC"},
            {"T_set": {"range": (18.0, 40.0), "max_step": 2.0, "safe": 20.0}},
            {"max_supply_C": 40.0, "rate_K_per_min": 2.0}, "simulated CDU", "simulation", "n/a", self.MODES)

    def read(self):
        return {"T_set": self.setpoint}

    def read_setpoint(self, actuation: str):
        return self.setpoint

    def write(self, actuation: str, value: float):
        self.setpoint = float(value)
        safe = self.capabilities.writes["T_set"]["safe"]
        def restore():
            self.setpoint = safe
        return restore
