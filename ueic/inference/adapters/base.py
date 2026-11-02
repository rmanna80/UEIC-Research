"""Serving-engine adapter interface (Stage 4).

An adapter turns one generation request into one ``GenResult`` with client-side timestamps. All
timestamps are on the host's wall clock (``time.time()``, the same clock as the NVML telemetry in
``ueic.telemetry``) and derived from one ``time.monotonic()`` reference per request, so intervals are
monotonic even if the wall clock is adjusted mid-run.

What the client can and cannot observe
  * time to first token (TTFT): submit -> first streamed chunk with content. Includes queueing, network
    and prefill. It is *not* the server's prefill time.
  * inter-chunk latency: gaps between streamed chunks. Engines usually send one token per chunk, but
    that is not guaranteed; ``n_chunks`` and ``completion_tokens`` are both recorded so the difference
    is visible.
  * server-side prefill/decode durations only when the engine reports them (Ollama does; the
    OpenAI-compatible endpoints of vLLM and SGLang do not report them per request).
Adapters never change GPU clocks, power limits or fans.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class GenRequest:
    request_id: str
    prompt: str
    max_tokens: int = 256
    temperature: float = 0.0
    seed: int | None = 0
    chat: bool = True                 # chat template (messages) vs raw completion
    stop: list[str] | None = None
    system: str | None = None


@dataclass
class GenResult:
    request_id: str
    engine: str
    model: str
    status: str = "ok"               # ok | error | timeout
    error: str | None = None
    http_status: int | None = None
    text: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    t_submit: float = float("nan")   # unix seconds
    t_first: float | None = None
    t_end: float = float("nan")
    chunk_times: list[float] = field(default_factory=list)
    server_prefill_s: float | None = None
    server_decode_s: float | None = None
    server_load_s: float | None = None
    finish_reason: str | None = None
    timing_source: str = "client"    # where prefill/decode come from: client (TTFT split) or server

    @property
    def n_chunks(self) -> int:
        return len(self.chunk_times)


class Clock:
    """Wall-clock timestamps derived from a single monotonic reference."""

    def __init__(self):
        self.w0, self.m0 = time.time(), time.monotonic()

    def now(self) -> float:
        return self.w0 + (time.monotonic() - self.m0)


class ServingAdapter(Protocol):
    engine: str
    model: str

    def info(self) -> dict[str, Any]: ...

    def generate(self, req: GenRequest, timeout_s: float = 120.0) -> GenResult: ...
