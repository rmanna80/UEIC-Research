"""GPU adapters: live NVML (read-only), replay of recorded NVML CSVs, and a simulated mock.

No adapter here can change clocks, power limits or fans (``writes = {}``); a test enforces that no NVML
setter appears in this package. Boundary: GPU board power from the board sensor, not system or facility power.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .hardware_registry import Capabilities, register
from .permissions import Mode

GPU_READS = {"power_W": "W", "energy_J": "J", "temp_C": "degC", "sm_clock_MHz": "MHz", "util_gpu_pct": "%"}
BOUNDARY = "GPU board (vendor on-board sensor via NVML); excludes host, PSU losses, fans and cooling plant"


@register
class NvmlGpu:
    """Live NVML GPU telemetry (read-only)."""
    kind = "nvml_gpu"
    MODES = (Mode.READ_ONLY,)

    def __init__(self, index: int = 0, nvml=None):
        from ..telemetry import Nvml
        self.nv = Nvml(nvml)
        self.dev = next(d for d in self.nv.devices() if d.index == index)
        self.capabilities = Capabilities(f"gpu{index}", self.kind, GPU_READS, {}, {"vendor_protection": "always on"},
                                         BOUNDARY, "physical_measurement", "manufacturer sensor; not independently calibrated",
                                         self.MODES)

    def read(self) -> dict[str, Any]:
        return self.nv.sample(self.dev)


@register
class ReplayGpu:
    """Replays a recorded NVML CSV (ueic.telemetry format) sample by sample."""
    kind = "replay_gpu"
    MODES = (Mode.REPLAY,)

    def __init__(self, csv_path: str, gpu: int = 0):
        from ..telemetry import read_csv
        self.rows = [r for r in read_csv(csv_path) if r.get("gpu") not in (None, "") and int(float(r["gpu"])) == gpu]
        if not self.rows:
            raise ValueError(f"no rows for gpu {gpu} in {csv_path}")
        self.i = 0
        self.capabilities = Capabilities(f"replay_gpu{gpu}", self.kind, GPU_READS, {}, {}, BOUNDARY + " (recorded)",
                                         "replay of physical_measurement", "as recorded", self.MODES)

    def read(self) -> dict[str, Any] | None:
        if self.i >= len(self.rows):
            return None
        r = self.rows[self.i]
        self.i += 1
        return r


@register
class MockGpu:
    """Simulated GPU: lumped junction node driven by the registry power model (synthetic readings)."""
    kind = "mock_gpu"
    MODES = (Mode.SIMULATION,)

    def __init__(self, s: float = 1.0, activity: float = 1.0, T_in: float = 30.0, seed: int = 0, noise_W: float = 2.0):
        from ..params import make_config
        self.cfg = make_config({})
        self.s, self.a, self.T_in, self.T = s, activity, T_in, T_in + 5.0
        self.t, self.E = 0.0, 0.0
        self.rng, self.noise = np.random.default_rng(seed), noise_W
        self.capabilities = Capabilities("mock_gpu", self.kind, GPU_READS, {}, {"t_throttle": self.cfg.t_throttle},
                                         "simulated GPU board", "simulation", "n/a", self.MODES)

    def step(self, dt: float) -> None:
        from .. import physics as ph
        P = float(ph.chip_power(self.s, self.T, self.a, self.cfg))
        self.T, _ = ph.thermal_step(self.T, P, self.T_in, float(ph.r_total(1.0, self.cfg)), self.cfg.c_th, dt)
        self.E += P * dt
        self.t += dt
        self._P = P

    def read(self) -> dict[str, Any]:
        P = getattr(self, "_P", 0.0)
        return {"t_unix": self.t, "power_W": P + float(self.rng.normal(0, self.noise)), "energy_J": self.E,
                "temp_C": round(self.T), "sm_clock_MHz": 2000 * self.s, "util_gpu_pct": 100 * self.a}
