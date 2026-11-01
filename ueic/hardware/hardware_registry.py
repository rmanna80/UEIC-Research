"""Device capability declarations and the registry of adapters.

Every adapter declares: what it reads (quantity -> unit), what it may write (actuation -> range, max
step, safe value), its safety limits, its measurement boundary, its evidence class for readings and its
calibration status. Adapters that cannot write declare ``writes = {}`` and have no write method that can
change hardware.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .permissions import Mode


@dataclass
class Capabilities:
    device_id: str
    kind: str
    reads: dict[str, str]
    writes: dict[str, dict[str, Any]] = field(default_factory=dict)
    safety_limits: dict[str, Any] = field(default_factory=dict)
    boundary: str = ""
    provenance: str = "simulation"          # simulation | replay | physical_measurement
    calibration: str = "not calibrated"
    modes: tuple = (Mode.SIMULATION,)

    def validate(self) -> None:
        if not self.boundary:
            raise ValueError(f"{self.device_id}: a measurement boundary must be declared")
        for a, w in self.writes.items():
            if "range" not in w or "safe" not in w:
                raise ValueError(f"{self.device_id}.{a}: writes need 'range' and 'safe'")
            lo, hi = w["range"]
            if not lo <= w["safe"] <= hi:
                raise ValueError(f"{self.device_id}.{a}: safe value outside range")


REGISTRY: dict[str, type] = {}


def register(cls):
    REGISTRY[cls.kind] = cls
    return cls


def create(kind: str, mode: Mode, **kw):
    if kind not in REGISTRY:
        raise KeyError(f"unknown device kind {kind!r}; have {sorted(REGISTRY)}")
    if Mode(mode) not in REGISTRY[kind].MODES:              # checked before any device is opened
        raise PermissionError(f"{kind} does not support {Mode(mode).value} mode")
    dev = REGISTRY[kind](**kw)
    dev.capabilities.validate()
    return dev


def describe() -> list[dict[str, Any]]:
    out = []
    for k, cls in sorted(REGISTRY.items()):
        out.append({"kind": k, "modes": [m.value for m in cls.MODES], "doc": (cls.__doc__ or "").strip().splitlines()[0]})
    return out
