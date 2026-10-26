"""Read-only GPU telemetry through NVML (Phase 4).

Safety rule (charter section 13): this module only *reads* from the GPU. It never calls
an NVML setter (clocks, power limits, fan, persistence, ...). A test enforces that no
`nvmlDeviceSet*` call appears in this file. Changing clocks for a calibration sweep is
an action the user takes with `nvidia-smi`, outside this code (see docs/09).

Measurement boundary: NVML board power as reported by the driver. It excludes the host
CPU, memory, PSU losses, fans outside the GPU, and the cooling plant. A GPU-only
measurement is never a facility measurement.

Requires `nvidia-ml-py` (import name `pynvml`) and an NVIDIA driver. Works on Windows
and Linux.
"""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

FIELDS = ["t_unix", "gpu", "power_W", "energy_J", "temp_C", "sm_clock_MHz", "mem_clock_MHz",
          "util_gpu_pct", "util_mem_pct", "pstate", "clock_event_reasons", "fan_pct", "label", "power_limit_W"]
# power_limit_W (enforced limit, per sample) was added after the first sessions; older files lack it.


def _load_nvml():
    try:
        import pynvml  # provided by the `nvidia-ml-py` package
    except ImportError as e:  # pragma: no cover - depends on the host
        raise RuntimeError("NVML bindings not installed. Run: pip install nvidia-ml-py") from e
    return pynvml


def _try(fn: Callable[[], Any]) -> Any:
    """NVML calls raise on unsupported queries (common on laptop GPUs); record None instead."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 - any NVMLError means "not available on this device"
        return None


def _s(x) -> str:
    return x.decode() if isinstance(x, bytes) else str(x)


@dataclass
class Device:
    index: int
    name: str
    uuid: str | None
    max_sm_clock_MHz: int | None
    max_mem_clock_MHz: int | None
    power_limit_W: float | None
    handle: Any = field(repr=False, default=None)


class Nvml:
    """Thin read-only wrapper. `nvml` may be injected (tests pass a fake module)."""

    def __init__(self, nvml=None):
        self.n = nvml or _load_nvml()
        self.n.nvmlInit()
        self.driver = _s(_try(self.n.nvmlSystemGetDriverVersion) or "unknown")

    def close(self):
        _try(self.n.nvmlShutdown)

    def devices(self) -> list[Device]:
        out = []
        for i in range(self.n.nvmlDeviceGetCount()):
            h = self.n.nvmlDeviceGetHandleByIndex(i)
            pl = _try(lambda: self.n.nvmlDeviceGetEnforcedPowerLimit(h))
            out.append(Device(
                index=i, name=_s(self.n.nvmlDeviceGetName(h)), uuid=_try(lambda: _s(self.n.nvmlDeviceGetUUID(h))),
                max_sm_clock_MHz=_try(lambda: self.n.nvmlDeviceGetMaxClockInfo(h, self.n.NVML_CLOCK_SM)),
                max_mem_clock_MHz=_try(lambda: self.n.nvmlDeviceGetMaxClockInfo(h, self.n.NVML_CLOCK_MEM)),
                power_limit_W=None if pl is None else pl / 1000.0, handle=h))
        return out

    def supported_sm_clocks(self, dev: Device) -> list[int] | None:
        """Lockable SM clocks at the highest memory clock (read-only query), or None if unsupported."""
        n, h = self.n, dev.handle
        mems = _try(lambda: n.nvmlDeviceGetSupportedMemoryClocks(h))
        if not mems:
            return None
        clocks = _try(lambda: n.nvmlDeviceGetSupportedGraphicsClocks(h, max(mems)))
        return sorted(int(c) for c in clocks) if clocks else None

    def sample(self, dev: Device, label: str = "") -> dict[str, Any]:
        n, h = self.n, dev.handle
        p = _try(lambda: n.nvmlDeviceGetPowerUsage(h))
        e = _try(lambda: n.nvmlDeviceGetTotalEnergyConsumption(h))
        pl = _try(lambda: n.nvmlDeviceGetEnforcedPowerLimit(h))   # can change at run time on laptops
        u = _try(lambda: n.nvmlDeviceGetUtilizationRates(h))
        reasons_fn = getattr(n, "nvmlDeviceGetCurrentClocksEventReasons", None) or \
            getattr(n, "nvmlDeviceGetCurrentClocksThrottleReasons", None)
        return {
            "t_unix": time.time(), "gpu": dev.index,
            "power_W": None if p is None else p / 1000.0,
            "energy_J": None if e is None else e / 1000.0,
            "temp_C": _try(lambda: n.nvmlDeviceGetTemperature(h, n.NVML_TEMPERATURE_GPU)),
            "sm_clock_MHz": _try(lambda: n.nvmlDeviceGetClockInfo(h, n.NVML_CLOCK_SM)),
            "mem_clock_MHz": _try(lambda: n.nvmlDeviceGetClockInfo(h, n.NVML_CLOCK_MEM)),
            "util_gpu_pct": None if u is None else u.gpu, "util_mem_pct": None if u is None else u.memory,
            "pstate": _try(lambda: n.nvmlDeviceGetPerformanceState(h)),
            "clock_event_reasons": None if reasons_fn is None else _try(lambda: reasons_fn(h)),
            "fan_pct": _try(lambda: n.nvmlDeviceGetFanSpeed(h)),
            "label": label,
            "power_limit_W": None if pl is None else pl / 1000.0,
        }


class Logger:
    """Samples one or more GPUs at a fixed interval into a CSV, with a metadata sidecar."""

    def __init__(self, out_csv: str | Path, interval_s: float = 0.1, gpus: list[int] | None = None,
                 nvml=None, label: str = ""):
        if interval_s < 0.02:
            raise ValueError("interval_s below 20 ms is not meaningful for NVML power readings")
        self.path = Path(out_csv)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.interval = interval_s
        self.nv = Nvml(nvml)
        devs = self.nv.devices()
        self.devs = [d for d in devs if gpus is None or d.index in gpus]
        if not self.devs:
            raise RuntimeError("No matching NVIDIA GPU found")
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.n_samples = 0
        self.started_utc = None

    def set_label(self, label: str) -> None:
        self.label = label

    def _run(self, duration_s: float | None):
        t0 = time.perf_counter()
        with open(self.path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            next_t = t0
            while not self._stop.is_set():
                for d in self.devs:
                    w.writerow(self.nv.sample(d, self.label))
                    self.n_samples += 1
                f.flush()
                next_t += self.interval
                if duration_s is not None and next_t - t0 >= duration_s:
                    break
                time.sleep(max(0.0, next_t - time.perf_counter()))

    def start(self, duration_s: float | None = None) -> "Logger":
        self.started_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._thread = threading.Thread(target=self._run, args=(duration_s,), daemon=True)
        self._thread.start()
        return self

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread:
            self._thread.join()
        meta = self.metadata()
        self.path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1))
        self.nv.close()
        return meta

    def run(self, duration_s: float) -> dict[str, Any]:
        self.start(duration_s)
        self._thread.join()
        return self.stop()

    def metadata(self) -> dict[str, Any]:
        raw = self.path.read_bytes() if self.path.exists() else b""
        return {
            "kind": "nvml_telemetry", "provenance": "physical_measurement",
            "measurement_boundary": "GPU board power as reported by NVML; excludes host, PSU losses, "
                                    "chassis fans and the cooling plant",
            "instrument": f"NVML via nvidia-ml-py; driver {self.nv.driver}",
            "calibration_status": "manufacturer on-board sensor; not independently calibrated",
            "sampling_interval_s": self.interval, "started_utc": self.started_utc,
            "stopped_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_samples": self.n_samples, "host": platform.platform(),
            "devices": [{k: v for k, v in d.__dict__.items() if k != "handle"} for d in self.devs],
            "csv": self.path.name, "csv_sha256": hashlib.sha256(raw).hexdigest(),
        }


def read_csv(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            out = {}
            for k, v in r.items():
                if k == "label":
                    out[k] = v
                elif v in ("", "None", None):
                    out[k] = None
                else:
                    out[k] = float(v)
            rows.append(out)
    return rows
