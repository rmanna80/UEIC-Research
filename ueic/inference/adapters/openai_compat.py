"""Client for OpenAI-compatible streaming endpoints (used by the vLLM and SGLang adapters).

Endpoints used (both engines document OpenAI compatibility):
  GET  /v1/models                   served model id(s)
  POST /v1/chat/completions         {"model", "messages", "max_tokens", "temperature", "seed", "stream": true,
  POST /v1/completions               "stream_options": {"include_usage": true}}  (completions: "prompt")
Streaming responses are server-sent events: lines ``data: {json}`` ending with ``data: [DONE]``. With
``include_usage`` the last JSON chunk carries ``usage`` (prompt_tokens, completion_tokens) and an empty
``choices`` list. If an engine omits usage, token counts stay None and are reported as missing.
"""
from __future__ import annotations

import json
from typing import Any

from ._http import classify_error, get_json, stream_lines
from .base import Clock, GenRequest, GenResult


class OpenAICompatAdapter:
    engine = "openai_compat"

    def __init__(self, base_url: str, model: str | None = None, api_key: str | None = None):
        self.base = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.model = model or self._first_model()

    def _first_model(self) -> str:
        data = get_json(f"{self.base}/v1/models").get("data") or []
        if not data:
            raise RuntimeError(f"{self.base}/v1/models lists no model")
        return data[0]["id"]

    def _extra_info(self) -> dict[str, Any]:
        return {}

    def info(self) -> dict[str, Any]:
        out: dict[str, Any] = {"engine": self.engine, "base_url": self.base, "model": self.model}
        try:
            models = get_json(f"{self.base}/v1/models").get("data") or []
            m = next((x for x in models if x.get("id") == self.model), None)
            out["model_card"] = m
        except Exception as e:  # noqa: BLE001
            out["model_card_error"] = str(e)
        out.update(self._extra_info())
        return out

    def body(self, req: GenRequest) -> tuple[str, dict]:
        b: dict[str, Any] = {"model": self.model, "max_tokens": req.max_tokens, "temperature": req.temperature,
                             "stream": True, "stream_options": {"include_usage": True}}
        if req.seed is not None:
            b["seed"] = req.seed
        if req.stop:
            b["stop"] = req.stop
        if req.chat:
            msgs = ([{"role": "system", "content": req.system}] if req.system else []) + \
                   [{"role": "user", "content": req.prompt}]
            return "/v1/chat/completions", {**b, "messages": msgs}
        return "/v1/completions", {**b, "prompt": req.prompt}

    def generate(self, req: GenRequest, timeout_s: float = 120.0) -> GenResult:
        path, body = self.body(req)
        clk = Clock()
        res = GenResult(req.request_id, self.engine, self.model, t_submit=clk.now())
        parts: list[str] = []
        try:
            for line in stream_lines(self.base + path, body, timeout_s, self.headers):
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                ev = json.loads(payload)
                if ev.get("usage"):
                    res.prompt_tokens = ev["usage"].get("prompt_tokens")
                    res.completion_tokens = ev["usage"].get("completion_tokens")
                for ch in ev.get("choices") or []:
                    piece = (ch.get("delta") or {}).get("content") if req.chat else ch.get("text")
                    if piece:
                        t = clk.now()
                        if res.t_first is None:
                            res.t_first = t
                        res.chunk_times.append(t)
                        parts.append(piece)
                    if ch.get("finish_reason"):
                        res.finish_reason = ch["finish_reason"]
                if clk.now() - res.t_submit > timeout_s:
                    raise TimeoutError(f"request exceeded {timeout_s} s")
        except Exception as e:  # noqa: BLE001 - recorded, never hidden
            res.status, res.http_status, res.error = classify_error(e)
        res.t_end = clk.now()
        res.text = "".join(parts)
        return res
