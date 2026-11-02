"""M003 leakage sweep: per-session summary of the raw telemetry (physical measurement, NVML board telemetry,
not independently calibrated). Checks every telemetry file against the SHA-256 recorded when it was written and
summarises the last half of each session (the window `calib leak` uses; for load sessions only samples with GPU
utilisation >= 90 %). Adds what the leakage fit needs to be comparable across steps: P-state, memory clock and
workload throughput.

Usage: python experiments/analyze_m003.py [GLOB]      (default: data/calibration/20261102T*, attempt 2)
"""
from __future__ import annotations

import csv
import hashlib
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(pattern: str = "data/calibration/20261102T*") -> None:
    print("| Session | Label | SHA-256 | Power W | SM clock MHz | Memory MHz | P-state | Throughput | Fan % | Temp °C |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for d in sorted(ROOT.glob(pattern)):
        sess = json.loads((d / "session.json").read_text(encoding="utf-8"))
        raw = (d / "telemetry.csv").read_bytes()
        ok = hashlib.sha256(raw).hexdigest() == sess["telemetry_sha256"]
        rows = list(csv.DictReader(raw.decode("utf-8").splitlines()))
        t = [float(r["t_unix"]) for r in rows]
        mid = t[0] + (t[-1] - t[0]) / 2
        half = [r for r, ti in zip(rows, t) if ti >= mid]
        if sess["kind"] == "compute":
            half = [r for r in half if float(r["util_gpu_pct"]) >= 90] or half
        col = lambda k: [float(r[k]) for r in half]   # noqa: E731
        work = [float(w["throughput"]) for w in csv.DictReader((d / "workload.csv").read_text(encoding="utf-8").splitlines())
                if float(w["t_unix"]) >= mid] if sess["kind"] == "compute" else []
        P, C, M, F, T = col("power_W"), col("sm_clock_MHz"), col("mem_clock_MHz"), col("fan_pct"), col("temp_C")
        ps = "/".join(sorted({f"P{r['pstate']}" for r in half}))
        thr = f"{st.median(work):.1f}" if work else "–"
        stop = " (stopped by guard)" if sess.get("guard_failed") else ""
        print(f"| {d.name[:16]} | {sess['label']}{stop} | {'match' if ok else 'MISMATCH'} | {st.mean(P):.1f} | "
              f"{min(C):.0f}–{max(C):.0f} | {st.median(M):.0f} | {ps} | {thr} | {min(F):.0f}–{max(F):.0f} | {min(T):.0f}–{max(T):.0f} |")


if __name__ == "__main__":
    main(*sys.argv[1:2])
