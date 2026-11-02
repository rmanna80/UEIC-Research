"""Latency and throughput summaries over request traces. Percentiles use numpy's linear interpolation."""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np

from .request_tracing import RequestTrace


def _pct(v: list[float], q: float) -> float | None:
    v = [x for x in v if x is not None and np.isfinite(x)]
    return float(np.percentile(v, q)) if v else None


def summarize_latency(traces: Iterable[RequestTrace]) -> dict[str, Any]:
    tr = list(traces)
    ok = [t for t in tr if t.status == "ok"]
    if not tr:
        return {"n": 0}
    t0 = min(t.t_scheduled for t in tr)
    t1 = max(t.t_end for t in tr)
    span = max(t1 - t0, 1e-9)
    tok_out = sum(t.completion_tokens or 0 for t in ok)
    tok_in = sum(t.prompt_tokens or 0 for t in ok)
    good = [t for t in ok if t.correct and (t.deadline_met is not False)]
    out = {
        "n": len(tr), "n_ok": len(ok), "n_failed": len(tr) - len(ok), "n_retries": sum(t.retries for t in tr),
        "n_deadline_missed": sum(t.deadline_met is False for t in tr),
        "n_scored": sum(t.correct is not None for t in ok), "n_correct": sum(bool(t.correct) for t in ok),
        "n_correct_on_time": len(good),
        "span_s": span, "requests_per_s": len(ok) / span, "goodput_per_s": len(good) / span,
        "output_tokens": tok_out, "prompt_tokens": tok_in, "output_tokens_per_s": tok_out / span,
        "missing_token_counts": sum(t.completion_tokens is None for t in ok),
        "chunks_vs_tokens_mismatch": sum((t.completion_tokens or 0) != t.n_chunks for t in ok),
    }
    for name, key in (("ttft", "ttft_s"), ("e2e", "e2e_s"), ("queue", "queue_s"), ("itl", "itl_mean_s"),
                      ("prefill", "prefill_s"), ("decode", "decode_s")):
        vals = [getattr(t, key) for t in ok]
        out[f"{name}_p50_s"], out[f"{name}_p95_s"], out[f"{name}_p99_s"] = _pct(vals, 50), _pct(vals, 95), _pct(vals, 99)
    out["timing_sources"] = sorted({t.timing_source for t in ok})
    return out
