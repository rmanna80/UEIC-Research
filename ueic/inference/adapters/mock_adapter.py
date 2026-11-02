"""Deterministic in-process stand-in for a serving engine, for tests and dry runs of the pipeline.

Output is SYNTHETIC: it is labelled engine "mock" in every trace and must never be reported as a
measurement. It answers prompts of the form "What is A + B?" (the built-in smoke set) correctly with
probability ``accuracy`` and otherwise answers wrong, after sleeping for a modelled prefill and decode
time. It has no GPU and draws no power.
"""
from __future__ import annotations

import re
import time
from typing import Any

import numpy as np

from .base import Clock, GenRequest, GenResult


class MockAdapter:
    engine = "mock"

    def __init__(self, model: str = "mock-1", accuracy: float = 0.8, prefill_s_per_tok: float = 2e-4,
                 decode_s_per_tok: float = 2e-3, out_tokens: int = 12, seed: int = 0, fail_every: int = 0):
        self.model, self.accuracy = model, accuracy
        self.pf, self.dc, self.out_tokens = prefill_s_per_tok, decode_s_per_tok, out_tokens
        self.rng = np.random.default_rng(seed)
        self.fail_every, self.n = fail_every, 0

    def info(self) -> dict[str, Any]:
        return {"engine": self.engine, "model": self.model, "synthetic": True}

    def generate(self, req: GenRequest, timeout_s: float = 120.0) -> GenResult:
        clk = Clock()
        res = GenResult(req.request_id, self.engine, self.model, t_submit=clk.now(), timing_source="server")
        self.n += 1
        if self.fail_every and self.n % self.fail_every == 0:
            res.status, res.error, res.t_end = "error", "injected failure", clk.now()
            return res
        n_in = max(1, len(req.prompt.split()))
        time.sleep(self.pf * n_in)
        m = re.search(r"(-?\d+)\s*\+\s*(-?\d+)", req.prompt)
        ans = int(m.group(1)) + int(m.group(2)) if m else 0
        if self.rng.random() >= self.accuracy:
            ans += 1
        words = f"The answer is {ans}".split()
        n_out = min(req.max_tokens, self.out_tokens)
        for i in range(n_out):
            time.sleep(self.dc)
            t = clk.now()
            res.t_first = res.t_first or t
            res.chunk_times.append(t)
        res.text = " ".join(words)
        res.prompt_tokens, res.completion_tokens = n_in, n_out
        res.server_prefill_s, res.server_decode_s = self.pf * n_in, self.dc * n_out
        res.finish_reason = "stop"
        res.t_end = clk.now()
        return res
