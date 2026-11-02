"""M003 attempt 1 (2026-10-27, user's RTX 5070): what the raw telemetry shows.

Physical measurement (NVML board telemetry, not independently calibrated). Reads the ten sessions in
data/calibration/20261027T*, checks each telemetry file against the SHA-256 recorded when it was written, and
summarises the last half of each session (the window `calib leak` uses; for load sessions, only samples
with GPU utilisation >= 90 %, which drops the final second after the load stopped). Prints a Markdown table.

Usage: python experiments/analyze_m003_attempt1.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    print("| Session | Label | SHA-256 | Power W (mean) | Power limit W | SM clock MHz | Fan % | Temp °C | GPU util % |")
    print("|---|---|---|---|---|---|---|---|---|")
    for d in sorted((ROOT / "data" / "calibration").glob("20261027T*")):
        sess = json.loads((d / "session.json").read_text(encoding="utf-8"))
        raw = (d / "telemetry.csv").read_bytes()
        ok = hashlib.sha256(raw).hexdigest() == sess["telemetry_sha256"]
        rows = list(csv.DictReader(raw.decode("utf-8").splitlines()))
        t = [float(r["t_unix"]) for r in rows]
        half = [r for r, ti in zip(rows, t) if ti >= t[0] + (t[-1] - t[0]) / 2]
        if sess["kind"] == "compute":      # drop the last samples after the load stopped (GPU utilisation < 90 %)
            half = [r for r in half if float(r["util_gpu_pct"]) >= 90]
        col = lambda k: [float(r[k]) for r in half]   # noqa: E731
        P, C, F, T, U = col("power_W"), col("sm_clock_MHz"), col("fan_pct"), col("temp_C"), col("util_gpu_pct")
        lim = sorted({r["power_limit_W"] for r in half})
        print(f"| {d.name[:16]} | {sess['label']} | {'match' if ok else 'MISMATCH'} | {st.mean(P):.1f} | {'/'.join(lim)} | "
              f"{min(C):.0f}–{max(C):.0f} | {min(F):.0f}–{max(F):.0f} | {min(T):.0f}–{max(T):.0f} | {st.mean(U):.0f} |")


if __name__ == "__main__":
    main()
