"""Datasets and request drivers for inference experiments.

Datasets are JSON lines with at least {"id", "task", "prompt", "reference"}; task-specific fields
(e.g. HumanEval's "test" and "entry_point") are kept. Benchmarks are NOT bundled: download them from
their official sources and convert with ``from_gsm8k`` / ``from_humaneval``. ``smoke_items`` builds a
tiny arithmetic set for checking the pipeline; it is labelled "smoke" and is not a benchmark.

Drivers
  open loop   requests are issued at pre-drawn arrival times (Poisson by default), up to a client-side
              concurrency cap; lateness caused by the cap is recorded as queue time and counts against
              the deadline.
  closed loop a fixed number of clients each issue the next request when the previous one finishes.
Retries: an attempt that ends in "error" or "timeout" is retried up to ``max_retries`` times after
``retry_backoff_s``; the trace keeps the last attempt and the retry count.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from .adapters.base import GenRequest, ServingAdapter
from .request_tracing import RequestTrace, TraceWriter, make_trace

GSM8K_INSTRUCTION = ("Solve the problem. Reason step by step, then give the final answer on the last line "
                     "as '#### <number>'.\n\n")
HUMANEVAL_INSTRUCTION = "Complete the following Python function. Return only the code of the full function.\n\n"


def load_items(path: str | Path, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
    rows = [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
    for r in rows:
        missing = {"id", "task", "prompt", "reference"} - set(r)
        if missing:
            raise ValueError(f"item {r.get('id')} lacks {sorted(missing)}")
    rows = rows[offset:]
    return rows[:limit] if limit else rows


def from_gsm8k(rows: Iterable[dict[str, Any]], prefix: str = "gsm8k") -> list[dict[str, Any]]:
    """Official GSM8K JSONL rows {"question", "answer"} -> items; reference keeps the '#### N' answer."""
    return [{"id": f"{prefix}-{i}", "task": "gsm8k", "prompt": GSM8K_INSTRUCTION + r["question"], "reference": r["answer"]}
            for i, r in enumerate(rows)]


def from_humaneval(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Official HumanEval rows {"task_id", "prompt", "test", "entry_point"} -> items."""
    return [{"id": r["task_id"], "task": "humaneval", "prompt": HUMANEVAL_INSTRUCTION + r["prompt"],
             "reference": r.get("canonical_solution", ""), "code_prompt": r["prompt"], "test": r["test"],
             "entry_point": r["entry_point"]} for r in rows]


def smoke_items(n: int = 20, seed: int = 0) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        a, b = (int(x) for x in rng.integers(1, 1000, 2))
        out.append({"id": f"smoke-{i}", "task": "smoke_arith", "prompt": f"What is {a} + {b}? End with '#### <number>'.",
                    "reference": f"#### {a + b}"})
    return out


def arrival_times(n: int, rate_per_s: float, seed: int = 0, process: str = "poisson") -> np.ndarray:
    """Arrival offsets (s) from the start; 'poisson' (exponential gaps) or 'uniform' (constant gaps)."""
    if rate_per_s <= 0:
        raise ValueError("rate must be positive")
    if process == "poisson":
        gaps = np.random.default_rng(seed).exponential(1.0 / rate_per_s, n)
    elif process == "uniform":
        gaps = np.full(n, 1.0 / rate_per_s)
    else:
        raise ValueError(f"unknown arrival process {process!r}")
    return np.concatenate([[0.0], np.cumsum(gaps[:-1])]) if n else np.array([])


def _attempt(adapter: ServingAdapter, item: dict, max_tokens: int, timeout_s: float, max_retries: int,
             retry_backoff_s: float, seed: int | None, request_id: str):
    retries = 0
    while True:
        req = GenRequest(request_id=f"{request_id}.{retries}", prompt=item["prompt"], max_tokens=max_tokens, seed=seed,
                         stop=item.get("stop"))
        res = adapter.generate(req, timeout_s=timeout_s)
        if res.status == "ok" or retries >= max_retries:
            return res, retries
        retries += 1
        time.sleep(retry_backoff_s)


def run_open_loop(adapter: ServingAdapter, items: list[dict], rate_per_s: float, *, seed: int = 0,
                  process: str = "poisson", max_concurrency: int = 8, max_tokens: int = 256,
                  timeout_s: float = 120.0, deadline_s: float | None = None, max_retries: int = 1,
                  retry_backoff_s: float = 1.0, scorer: Callable[[dict, str], tuple[bool | None, float | None, str]] | None = None,
                  writer: TraceWriter | None = None, label: str = "") -> list[RequestTrace]:
    offs = arrival_times(len(items), rate_per_s, seed, process)
    sem = threading.Semaphore(max_concurrency)
    traces: list[RequestTrace] = []
    lock = threading.Lock()
    t0 = time.time() + 0.05

    def work(i: int, item: dict):
        t_sched = t0 + float(offs[i])
        try:
            res, retries = _attempt(adapter, item, max_tokens, timeout_s, max_retries, retry_backoff_s, seed, f"r{i}")
            tr = make_trace(res, item["id"], item["task"], t_sched, retries, deadline_s, max_concurrency, label)
            if scorer and tr.status == "ok":
                tr.correct, tr.score, tr.score_method = scorer(item, res.text)
            with lock:
                traces.append(tr)
            if writer:
                writer.write(tr)
        finally:
            sem.release()

    with ThreadPoolExecutor(max_workers=max_concurrency) as ex:
        for i, item in enumerate(items):
            delay = t0 + float(offs[i]) - time.time()
            if delay > 0:
                time.sleep(delay)
            sem.acquire()                       # client-side cap: lateness becomes queue time
            ex.submit(work, i, item)
    return sorted(traces, key=lambda t: t.t_scheduled)


def run_closed_loop(adapter: ServingAdapter, items: list[dict], concurrency: int, **kw) -> list[RequestTrace]:
    """``concurrency`` clients, each issuing its next item immediately after the previous finishes."""
    kw = {**kw}
    scorer, writer, label = kw.pop("scorer", None), kw.pop("writer", None), kw.pop("label", "")
    deadline_s = kw.pop("deadline_s", None)
    max_tokens, timeout_s = kw.pop("max_tokens", 256), kw.pop("timeout_s", 120.0)
    max_retries, backoff, seed = kw.pop("max_retries", 1), kw.pop("retry_backoff_s", 1.0), kw.pop("seed", 0)
    if kw:
        raise TypeError(f"unexpected arguments {sorted(kw)}")
    queue = list(enumerate(items))
    qlock, lock = threading.Lock(), threading.Lock()
    traces: list[RequestTrace] = []

    def client():
        while True:
            with qlock:
                if not queue:
                    return
                i, item = queue.pop(0)
            t_sched = time.time()
            res, retries = _attempt(adapter, item, max_tokens, timeout_s, max_retries, backoff, seed, f"r{i}")
            tr = make_trace(res, item["id"], item["task"], t_sched, retries, deadline_s, concurrency, label)
            if scorer and tr.status == "ok":
                tr.correct, tr.score, tr.score_method = scorer(item, res.text)
            with lock:
                traces.append(tr)
            if writer:
                writer.write(tr)

    threads = [threading.Thread(target=client) for _ in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return sorted(traces, key=lambda t: t.t_scheduled)
