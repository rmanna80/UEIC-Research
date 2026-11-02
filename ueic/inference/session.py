"""One inference measurement session: warm-up, traced workload, read-only GPU telemetry, summary.

Layout (append-only; a session directory is never rewritten):
    <out>/session.json    engine/model identity, configuration, label, host, code hash, provenance
    <out>/traces.jsonl    one RequestTrace per item (warm-up requests are in warmup.jsonl)
    <out>/telemetry.csv   NVML samples (+ .meta.json) when telemetry is on
    <out>/summary.json    latency, quality, energy per boundary, allocation, guard results

Operating points (GPU clock locks, power limits, OLLAMA_NUM_PARALLEL, vLLM flags) are set by the
operator before the session, never by this code. The session only *checks* them: if a locked SM clock
is declared (``expect_clock_MHz``) and the median clock under load differs by more than ``clock_tol_MHz``,
the session is marked guard_failed and its energy numbers must not be used for that operating point.
"""
from __future__ import annotations

import json
import platform
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .energy_accounting import allocate, useful_metrics, window_energy
from .latency_metrics import summarize_latency
from .quality_evaluation import make_scorer
from .request_tracing import PrometheusSampler, TraceWriter
from .workload_generator import run_closed_loop, run_open_loop


def _code_hash() -> str | None:
    try:
        from ..store import code_hash
        return code_hash()
    except Exception:  # noqa: BLE001
        return None


def clock_guard(rows: list[dict[str, Any]], t0: float, t1: float, expect_MHz: float | None,
                tol_MHz: float = 30.0, min_util_pct: float = 50.0) -> list[str]:
    """Problems with the declared clock lock, from samples under load inside [t0, t1]."""
    if expect_MHz is None:
        return []
    load = [r for r in rows if t0 <= r["t_unix"] <= t1 and (r.get("util_gpu_pct") or 0) >= min_util_pct
            and r.get("sm_clock_MHz") is not None]
    if len(load) < 5:
        return [f"only {len(load)} loaded samples: cannot confirm the {expect_MHz:.0f} MHz lock"]
    med = float(np.median([r["sm_clock_MHz"] for r in load]))
    return [] if abs(med - expect_MHz) <= tol_MHz else [f"median SM clock {med:.0f} MHz under load, declared {expect_MHz:.0f} MHz"]


def measure_idle_power(seconds: float = 60.0, gpu: int = 0, settle_s: float = 10.0, out_csv: str | Path | None = None) -> dict[str, Any]:
    """Median NVML board power with no work submitted (read-only). Run it at the same clocks and fan state."""
    from ..telemetry import Logger
    out_csv = Path(out_csv) if out_csv else Path("data/inference/idle") / datetime.now().strftime("%Y%m%dT%H%M%S") / "telemetry.csv"
    lg = Logger(out_csv, interval_s=0.1, gpus=[gpu], label="idle")
    lg.run(seconds)
    from ..telemetry import read_csv
    rows = read_csv(out_csv)
    t0 = rows[0]["t_unix"] + settle_s if rows else 0
    p = [r["power_W"] for r in rows if r["t_unix"] >= t0 and r.get("power_W") is not None]
    return {"idle_W": float(np.median(p)) if p else float("nan"), "n": len(p), "csv": str(out_csv),
            "provenance": "physical_measurement", "boundary": "GPU board (NVML)"}


def run_session(adapter, items: list[dict], out_dir: str | Path, *, mode: str = "closed", concurrency: int = 1,
                rate_per_s: float | None = None, deadline_s: float | None = None, max_tokens: int = 512,
                timeout_s: float = 300.0, max_retries: int = 1, task_cfg: dict | None = None, warmup: int = 2,
                telemetry: bool = True, gpu: int = 0, interval_s: float = 0.1, idle_W: float | None = None,
                expect_clock_MHz: float | None = None, clock_tol_MHz: float = 30.0, label: str = "",
                facility_factor: float | None = None, facility_factor_source: str | None = None,
                price_per_kWh: float | None = None, metrics_url: str | None = None,
                metrics_names: list[str] | None = None, seed: int = 0, logger_factory=None) -> dict[str, Any]:
    out = Path(out_dir)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} is not empty; sessions are append-only")
    out.mkdir(parents=True, exist_ok=True)
    info = adapter.info()
    synthetic = bool(info.get("synthetic")) or getattr(adapter, "engine", "") == "mock"
    meta = {"kind": "inference_session", "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "provenance": "synthetic (mock engine)" if synthetic else "physical_measurement",
            "engine": info, "label": label, "host": platform.platform(), "code_hash": _code_hash(),
            "config": {"mode": mode, "concurrency": concurrency, "rate_per_s": rate_per_s, "deadline_s": deadline_s,
                       "max_tokens": max_tokens, "timeout_s": timeout_s, "max_retries": max_retries, "warmup": warmup,
                       "task_cfg": task_cfg or {}, "gpu": gpu, "interval_s": interval_s, "idle_W": idle_W,
                       "expect_clock_MHz": expect_clock_MHz, "facility_factor": facility_factor,
                       "facility_factor_source": facility_factor_source, "price_per_kWh": price_per_kWh, "seed": seed},
            "items": [it["id"] for it in items]}
    (out / "session.json").write_text(json.dumps(meta, indent=1))
    scorer = make_scorer(task_cfg)
    if warmup:
        run_closed_loop(adapter, items[:warmup], 1, max_tokens=max_tokens, timeout_s=timeout_s, max_retries=0,
                        writer=TraceWriter(out / "warmup.jsonl"), label="warmup", seed=seed)
    lg = None
    if telemetry:
        if logger_factory is not None:
            lg = logger_factory(out / "telemetry.csv")
        else:
            from ..telemetry import Logger
            lg = Logger(out / "telemetry.csv", interval_s=interval_s, gpus=[gpu], label=label)
        lg.start()
    prom = PrometheusSampler(metrics_url, metrics_names or []).start() if metrics_url else None
    writer = TraceWriter(out / "traces.jsonl")
    common = dict(max_tokens=max_tokens, timeout_s=timeout_s, deadline_s=deadline_s, max_retries=max_retries,
                  scorer=scorer, writer=writer, label=label, seed=seed)
    try:
        if mode == "closed":
            traces = run_closed_loop(adapter, items, concurrency, **common)
        elif mode == "open":
            if not rate_per_s:
                raise ValueError("open-loop mode needs rate_per_s")
            traces = run_open_loop(adapter, items, rate_per_s, max_concurrency=concurrency, **common)
        else:
            raise ValueError(f"unknown mode {mode!r}")
    finally:
        if lg is not None:
            lg.stop()
        prom_samples = prom.stop() if prom else None
    summary: dict[str, Any] = {"provenance": meta["provenance"], "latency": summarize_latency(traces)}
    if prom_samples is not None:
        (out / "server_metrics.json").write_text(json.dumps(prom_samples))
    t0 = min(t.t_scheduled for t in traces) if traces else 0.0
    t1 = max(t.t_end for t in traces) if traces else 0.0
    energy: dict[str, Any] = {}
    guard: list[str] = []
    if telemetry and lg is not None:
        from ..telemetry import read_csv
        rows = [r for r in read_csv(out / "telemetry.csv") if r.get("gpu") in (gpu, str(gpu))]
        ts = [r["t_unix"] for r in rows]
        pw = [r.get("power_W") for r in rows]
        en = [r.get("energy_J") for r in rows]
        win = window_energy(ts, pw, en, t0, t1)
        energy["window"] = win
        guard = clock_guard(rows, t0, t1, expect_clock_MHz, clock_tol_MHz)
        if not win.get("complete"):
            guard.append(f"telemetry incomplete (largest gap {win.get('max_gap_s')} s)")
        bounds = {"gpu_total": win["E_J"]}
        if idle_W is not None and np.isfinite(win["E_J"]):
            bounds["gpu_dynamic"] = win["E_J"] - idle_W * (t1 - t0)
            energy["idle_J"] = idle_W * (t1 - t0)
            energy["allocation"] = {m: {k: v for k, v in allocate(traces, ts, pw, idle_W, m).items() if k != "per_request_J"}
                                    for m in ("equal_inflight", "token_share")
                                    if m == "equal_inflight" or all(t.completion_tokens is not None for t in traces)}
        if facility_factor is not None:
            if not facility_factor_source:
                raise ValueError("a facility overhead factor needs a stated source")
            bounds["facility_est"] = win["E_J"] * facility_factor
        energy["metrics"] = {b: useful_metrics(traces, E, b, price_per_kWh) for b, E in bounds.items()}
        energy["facility_note"] = ("facility_est = gpu_total x factor; estimated, not measured "
                                   f"(source: {facility_factor_source})") if facility_factor is not None else None
    summary["energy"] = energy
    summary["guard_problems"] = guard
    summary["guard_failed"] = bool(guard)
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=float))
    return summary
