"""Modes, operator grants and guarded writes.

A ``Grant`` is created by a named operator for a time window, a device, one actuation and a value range,
with the approval text they typed. Grants are stored as JSON (append-only directory). A write is allowed
only if: mode == operator; the device declares the actuation; an unexpired grant covers device,
actuation and value; the value is inside the device's own safety limits; and the rate of change is within
the device's limit. Every allowed write returns a restore callback that puts the actuator back to its
recorded safe value; ``GuardedSession`` calls all of them on exit, including after exceptions.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Callable


class Mode(str, Enum):
    SIMULATION = "simulation"
    REPLAY = "replay"
    READ_ONLY = "read_only"
    OPERATOR = "operator"


@dataclass(frozen=True)
class Grant:
    operator: str
    device: str
    actuation: str
    lo: float
    hi: float
    not_after_unix: float
    approval_text: str
    created_unix: float

    def covers(self, device: str, actuation: str, value: float, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return (self.device == device and self.actuation == actuation and self.lo <= value <= self.hi
                and now <= self.not_after_unix)


REQUIRED_PHRASE = "I AUTHORIZE"


def make_grant(operator: str, device: str, actuation: str, lo: float, hi: float, minutes: float,
               typed: str, store_dir: str | Path | None = None) -> Grant:
    if typed.strip() != REQUIRED_PHRASE:
        raise PermissionError(f"grant not created: the operator must type {REQUIRED_PHRASE!r}")
    if not operator.strip():
        raise PermissionError("grant needs a named operator")
    if not lo <= hi or minutes <= 0 or minutes > 240:
        raise ValueError("need lo <= hi and 0 < minutes <= 240")
    now = time.time()
    g = Grant(operator, device, actuation, float(lo), float(hi), now + 60 * minutes, typed, now)
    if store_dir:
        d = Path(store_dir); d.mkdir(parents=True, exist_ok=True)
        (d / f"grant_{int(now)}_{device}_{actuation}.json").write_text(json.dumps(asdict(g), indent=1), encoding="utf-8")
    return g


class Permissions:
    def __init__(self, mode: Mode, grants: list[Grant] | None = None):
        self.mode, self.grants = Mode(mode), list(grants or [])
        self.log: list[dict] = []

    def authorize(self, device, actuation: str, value: float, now: float | None = None) -> None:
        cap = device.capabilities
        if self.mode != Mode.OPERATOR:
            raise PermissionError(f"writes are not allowed in {self.mode.value} mode")
        if actuation not in cap.writes:
            raise PermissionError(f"{cap.device_id} declares no actuation {actuation!r}")
        lo, hi = cap.writes[actuation]["range"]
        if not lo <= value <= hi:
            raise PermissionError(f"{value} outside {cap.device_id}.{actuation} safety range [{lo}, {hi}]")
        if not any(g.covers(cap.device_id, actuation, value, now) for g in self.grants):
            raise PermissionError(f"no unexpired operator grant covers {cap.device_id}.{actuation} = {value}")


class GuardedSession:
    """Context manager: every write goes through ``write``; all restores run on exit."""

    def __init__(self, perms: Permissions):
        self.perms = perms
        self._restores: list[Callable[[], None]] = []

    def write(self, device, actuation: str, value: float) -> None:
        self.perms.authorize(device, actuation, value)
        rate = device.capabilities.writes[actuation].get("max_step")
        cur = device.read_setpoint(actuation)
        if rate is not None and cur is not None and abs(value - cur) > rate:
            raise PermissionError(f"step {abs(value - cur):.3g} exceeds {device.capabilities.device_id}.{actuation} max_step {rate}")
        restore = device.write(actuation, value)
        self._restores.append(restore)
        self.perms.log.append({"t": time.time(), "device": device.capabilities.device_id, "actuation": actuation, "value": value})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        for r in reversed(self._restores):
            r()
        self._restores.clear()
        return False
