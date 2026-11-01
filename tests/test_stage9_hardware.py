"""Stage 9: hardware modes, capability declarations, grants, guarded writes with restore, replay, mocks."""
from __future__ import annotations

import csv
import glob
import re
import time
from pathlib import Path

import pytest

import ueic.hardware  # noqa: F401  (registers adapters)
from ueic.hardware.hardware_registry import REGISTRY, create
from ueic.hardware.permissions import REQUIRED_PHRASE, GuardedSession, Mode, Permissions, make_grant
from ueic.hardware.telemetry import TelemetryBus

ROOT = Path(__file__).resolve().parents[1]


def test_every_adapter_declares_capabilities_and_boundary():
    for kind, cls in REGISTRY.items():
        if kind.startswith("csv_") or kind in ("nvml_gpu", "replay_gpu"):
            continue                                         # need a file or a GPU; covered below
        dev = create(kind, cls.MODES[0])
        assert dev.capabilities.boundary and dev.capabilities.reads, kind


def test_modes_are_enforced():
    with pytest.raises(PermissionError):
        create("mock_gpu", Mode.OPERATOR)
    with pytest.raises(PermissionError):
        create("nvml_gpu", Mode.OPERATOR)


def test_writes_need_operator_mode_grant_and_limits():
    pump = create("mock_pump", Mode.OPERATOR, speed=0.8)
    with pytest.raises(PermissionError):
        GuardedSession(Permissions(Mode.READ_ONLY)).write(pump, "speed", 0.7)
    with pytest.raises(PermissionError):
        GuardedSession(Permissions(Mode.OPERATOR)).write(pump, "speed", 0.7)              # no grant
    with pytest.raises(PermissionError):
        make_grant("alice", "mock_pump", "speed", 0.5, 1.0, 10, "yes")                  # wrong phrase
    g = make_grant("alice", "mock_pump", "speed", 0.5, 1.0, 10, REQUIRED_PHRASE)
    perms = Permissions(Mode.OPERATOR, [g])
    with pytest.raises(PermissionError):
        GuardedSession(perms).write(pump, "speed", 0.4)                                  # outside grant
    with pytest.raises(PermissionError):
        GuardedSession(perms).write(pump, "speed", 0.55)                                 # step 0.25 > 0.2
    with pytest.raises(PermissionError):
        GuardedSession(perms).write(pump, "torque", 0.9)                                 # undeclared actuation
    expired = make_grant("alice", "mock_pump", "speed", 0.5, 1.0, 1, REQUIRED_PHRASE)
    assert not expired.covers("mock_pump", "speed", 0.7, now=time.time() + 120)


def test_guarded_session_restores_on_exception():
    pump = create("mock_pump", Mode.OPERATOR, speed=0.8)
    cdu = create("mock_cooling_controller", Mode.OPERATOR, setpoint=25.0)
    perms = Permissions(Mode.OPERATOR, [make_grant("op", "mock_pump", "speed", 0.3, 1.0, 5, REQUIRED_PHRASE),
                                        make_grant("op", "mock_cdu", "T_set", 18, 40, 5, REQUIRED_PHRASE)])
    with pytest.raises(RuntimeError):
        with GuardedSession(perms) as s:
            s.write(pump, "speed", 0.65)
            s.write(cdu, "T_set", 27.0)
            assert (pump.speed, cdu.setpoint) == (0.65, 27.0)
            raise RuntimeError("experiment aborted")
    assert pump.speed == 1.0 and cdu.setpoint == 20.0                   # declared safe values
    assert len(perms.log) == 2


def test_simulated_bus_and_replay(tmp_path):
    gpu = create("mock_gpu", Mode.SIMULATION)
    meter = create("mock_power_meter", Mode.SIMULATION, truth=lambda: 350.0)
    rows = TelemetryBus([gpu, meter], tmp_path / "bus.csv").collect(20, 1.0, advance=gpu.step)
    assert rows > 0 and (tmp_path / "bus.meta.json").exists()
    files = sorted(glob.glob(str(ROOT / "data" / "calibration" / "*" / "telemetry.csv")))
    if files:
        rep = create("replay_gpu", Mode.REPLAY, csv_path=files[0])
        first = rep.read()
        assert first is not None and "power_W" in first and rep.capabilities.provenance.startswith("replay")


def test_csv_ingest_reads_only_new_rows(tmp_path):
    p = tmp_path / "meter.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["t_unix", "power_W"]); w.writerow([1.0, 300.0])
    m = create("csv_power_meter", Mode.READ_ONLY, path=str(p))
    assert m.read()["power_W"] == 300.0 and m.read() is None
    with open(p, "a", newline="") as f:
        csv.writer(f).writerow([2.0, 310.0])
    assert m.read()["power_W"] == 310.0
    assert m.capabilities.writes == {}


def test_no_gpu_setters_anywhere_in_hardware_package():
    bad = re.compile(r"nvmlDeviceSet|nvidia-smi\s+-(lgc|pl|rgc)|subprocess")
    for p in (ROOT / "ueic" / "hardware").rglob("*.py"):
        assert not bad.search(p.read_text()), p
