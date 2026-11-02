"""Multi-device telemetry: poll several read-capable adapters into one CSV with a metadata sidecar that
records each device's capabilities (boundary, provenance, calibration). Simulation, replay and live
read-only adapters all work, so an analysis pipeline can be exercised on replayed data first."""
from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict
from pathlib import Path


class TelemetryBus:
    def __init__(self, devices: list, out_csv: str | Path):
        self.devices, self.path = devices, Path(out_csv)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def collect(self, n: int, interval_s: float = 0.0, advance=None) -> int:
        """Poll every device n times. ``advance(dt)`` steps simulated devices; None for live/replay."""
        rows = 0
        with open(self.path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_poll", "device", "quantity", "value"])
            for _ in range(n):
                if advance:
                    advance(interval_s)
                elif interval_s:
                    time.sleep(interval_s)
                t = time.time()
                for d in self.devices:
                    r = d.read()
                    if r is None:
                        continue
                    for q in d.capabilities.reads:
                        if q in r and r[q] is not None:
                            w.writerow([t, d.capabilities.device_id, q, r[q]]); rows += 1
        meta = {"devices": [{k: (v if not hasattr(v, "value") else v.value) for k, v in asdict(d.capabilities).items()
                             if k != "modes"} for d in self.devices], "rows": rows}
        self.path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1, default=str))
        return rows
