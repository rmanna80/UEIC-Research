"""Ollama adapter (``ollama serve``, default port 11434).

Endpoints:
  GET  /api/version   {"version"}
  GET  /api/tags      local models: name, digest, size, details (family, parameter_size, quantization_level)
  POST /api/chat      {"model", "messages", "stream": true, "options": {"num_predict", "temperature", "seed"}}
  POST /api/generate  {"model", "prompt", ...}
The stream is newline-delimited JSON; the final object (``done: true``) carries prompt_eval_count,
prompt_eval_duration, eval_count, eval_duration, load_duration and total_duration, all durations in
nanoseconds. These give *server-side* prefill and decode times. ``prompt_eval_duration`` covers only
prompt tokens that were not cached, so with prompt caching it can understate prefill.
Concurrency is set on the server (OLLAMA_NUM_PARALLEL), not per request; record it in the session label.
"""
from __future__ import annotations

import json
from typing import Any

from ._http import classify_error, get_json, stream_lines
from .base import Clock, GenRequest, GenResult

NS = 1e-9


class OllamaAdapter:
    engine = "ollama"

    def __init__(self, base_url: str = "http://127.0.0.1:11434", model: str = "", keep_alive: str | None = "30m"):
        if not model:
            raise ValueError("Ollama needs an explicit model name (e.g. from `ollama list`)")
        self.base, self.model, self.keep_alive = base_url.rstrip("/"), model, keep_alive

    def info(self) -> dict[str, Any]:
        out: dict[str, Any] = {"engine": self.engine, "base_url": self.base, "model": self.model}
        try:
            out["engine_version"] = get_json(f"{self.base}/api/version").get("version")
        except Exception as e:  # noqa: BLE001
            out["engine_version_error"] = str(e)
        try:
            tags = get_json(f"{self.base}/api/tags").get("models") or []
            out["model_card"] = next((m for m in tags if m.get("name") == self.model or m.get("model") == self.model), None)
        except Exception as e:  # noqa: BLE001
            out["model_card_error"] = str(e)
        return out

    def body(self, req: GenRequest) -> tuple[str, dict]:
        opts: dict[str, Any] = {"num_predict": req.max_tokens, "temperature": req.temperature}
        if req.seed is not None:
            opts["seed"] = req.seed
        if req.stop:
            opts["stop"] = req.stop
        b: dict[str, Any] = {"model": self.model, "stream": True, "options": opts}
        if self.keep_alive:
            b["keep_alive"] = self.keep_alive
        if req.chat:
            msgs = ([{"role": "system", "content": req.system}] if req.system else []) + \
                   [{"role": "user", "content": req.prompt}]
            return "/api/chat", {**b, "messages": msgs}
        return "/api/generate", {**b, "prompt": req.prompt}

    def generate(self, req: GenRequest, timeout_s: float = 120.0) -> GenResult:
        path, body = self.body(req)
        clk = Clock()
        res = GenResult(req.request_id, self.engine, self.model, t_submit=clk.now(), timing_source="server")
        parts: list[str] = []
        try:
            for line in stream_lines(self.base + path, body, timeout_s):
                ev = json.loads(line)
                if ev.get("error"):
                    raise RuntimeError(ev["error"])
                piece = (ev.get("message") or {}).get("content") if req.chat else ev.get("response")
                if piece:
                    t = clk.now()
                    if res.t_first is None:
                        res.t_first = t
                    res.chunk_times.append(t)
                    parts.append(piece)
                if ev.get("done"):
                    res.prompt_tokens = ev.get("prompt_eval_count")
                    res.completion_tokens = ev.get("eval_count")
                    g = lambda k: None if ev.get(k) is None else ev[k] * NS   # noqa: E731
                    res.server_prefill_s, res.server_decode_s, res.server_load_s = (
                        g("prompt_eval_duration"), g("eval_duration"), g("load_duration"))
                    res.finish_reason = ev.get("done_reason")
                    break
                if clk.now() - res.t_submit > timeout_s:
                    raise TimeoutError(f"request exceeded {timeout_s} s")
        except Exception as e:  # noqa: BLE001
            res.status, res.http_status, res.error = classify_error(e)
        res.t_end = clk.now()
        res.text = "".join(parts)
        if res.server_prefill_s is None:
            res.timing_source = "client"
        return res
