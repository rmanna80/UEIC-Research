"""Per-request traces, written append-only as JSON lines, and an optional Prometheus sampler.

A trace is one *attempt chain* for one dataset item: the final attempt's timings plus how many retries
preceded it. Derived fields:
  ttft_s        t_first - t_submit (client view; includes queueing and network)
  e2e_s         t_end - t_submit of the final attempt
  queue_s       t_submit - t_scheduled (open loop: how late the client could issue it)
  prefill_s     server value if the engine reports it, else ttft_s (timing_source says which)
  decode_s      server value if reported, else t_end - t_first
  itl_*         from gaps between streamed chunks (chunk != token in general; n_chunks recorded)
  deadline_met  e2e from the *scheduled* arrival <= deadline (so client-side queueing counts against it)
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .adapters.base import GenResult


@dataclass
class RequestTrace:
    request_id: str
    item_id: str
    task: str
    engine: str
    model: str
    status: str
    t_scheduled: float
    t_submit: float
    t_first: float | None
    t_end: float
    prompt_tokens: int | None
    completion_tokens: int | None
    n_chunks: int
    ttft_s: float | None
    e2e_s: float
    queue_s: float
    prefill_s: float | None
    decode_s: float | None
    timing_source: str
    itl_mean_s: float | None
    itl_p50_s: float | None
    itl_p95_s: float | None
    retries: int
    error: str | None
    deadline_s: float | None
    deadline_met: bool | None
    correct: bool | None = None
    score: float | None = None
    score_method: str | None = None
    concurrency: int | None = None
    label: str = ""
    text: str = ""
    extra: dict = field(default_factory=dict)


def make_trace(res: GenResult, item_id: str, task: str, t_scheduled: float, retries: int,
               deadline_s: float | None, concurrency: int | None = None, label: str = "") -> RequestTrace:
    ok = res.status == "ok"
    ttft = (res.t_first - res.t_submit) if (ok and res.t_first is not None) else None
    gaps = np.diff(res.chunk_times) if len(res.chunk_times) > 1 else np.array([])
    decode = res.server_decode_s if res.server_decode_s is not None else (
        (res.t_end - res.t_first) if (ok and res.t_first is not None) else None)
    prefill = res.server_prefill_s if res.server_prefill_s is not None else ttft
    lat = res.t_end - t_scheduled
    return RequestTrace(
        request_id=res.request_id, item_id=item_id, task=task, engine=res.engine, model=res.model, status=res.status,
        t_scheduled=t_scheduled, t_submit=res.t_submit, t_first=res.t_first, t_end=res.t_end,
        prompt_tokens=res.prompt_tokens, completion_tokens=res.completion_tokens, n_chunks=res.n_chunks,
        ttft_s=ttft, e2e_s=res.t_end - res.t_submit, queue_s=max(0.0, res.t_submit - t_scheduled),
        prefill_s=prefill, decode_s=decode, timing_source=res.timing_source if res.server_prefill_s is not None else "client",
        itl_mean_s=float(gaps.mean()) if gaps.size else None,
        itl_p50_s=float(np.percentile(gaps, 50)) if gaps.size else None,
        itl_p95_s=float(np.percentile(gaps, 95)) if gaps.size else None,
        retries=retries, error=res.error, deadline_s=deadline_s,
        deadline_met=(ok and lat <= deadline_s) if deadline_s is not None else None,
        concurrency=concurrency, label=label, text=res.text)


class TraceWriter:
    """Append-only JSONL writer (thread-safe)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, tr: RequestTrace) -> None:
        line = json.dumps(asdict(tr), default=float)
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def read_traces(path: str | Path) -> list[RequestTrace]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(RequestTrace(**json.loads(line)))
    return out


_PROM = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([-+0-9.eEinfNa]+)")


def parse_prometheus(text: str, names: list[str]) -> dict[str, float]:
    """Sum of samples for each requested metric name (labels ignored). Missing names are absent."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        m = _PROM.match(line.strip())
        if m and m.group(1) in names:
            out[m.group(1)] = out.get(m.group(1), 0.0) + float(m.group(3))
    return out


class PrometheusSampler:
    """Polls a /metrics endpoint for configured gauges (e.g. running/waiting requests) in a thread."""

    def __init__(self, url: str, names: list[str], interval_s: float = 0.5):
        self.url, self.names, self.interval = url, names, interval_s
        self.samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._t: threading.Thread | None = None

    def _run(self):
        while not self._stop.is_set():
            try:
                with urllib.request.urlopen(self.url, timeout=2) as r:
                    vals = parse_prometheus(r.read().decode(), self.names)
                self.samples.append({"t_unix": time.time(), **vals})
            except Exception as e:  # noqa: BLE001
                self.samples.append({"t_unix": time.time(), "error": str(e)})
            self._stop.wait(self.interval)

    def start(self) -> "PrometheusSampler":
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        return self

    def stop(self) -> list[dict[str, Any]]:
        self._stop.set()
        if self._t:
            self._t.join()
        return self.samples
