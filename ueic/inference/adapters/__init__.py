"""Serving-engine adapters. ``make_adapter("vllm" | "sglang" | "ollama" | "mock", ...)``."""
from __future__ import annotations

from .base import GenRequest, GenResult, ServingAdapter


def make_adapter(engine: str, url: str | None = None, model: str | None = None, **kw) -> ServingAdapter:
    if engine == "vllm":
        from .vllm_adapter import VLLMAdapter
        return VLLMAdapter(url or "http://127.0.0.1:8000", model, **kw)
    if engine == "sglang":
        from .sglang_adapter import SGLangAdapter
        return SGLangAdapter(url or "http://127.0.0.1:30000", model, **kw)
    if engine == "ollama":
        from .ollama_adapter import OllamaAdapter
        return OllamaAdapter(url or "http://127.0.0.1:11434", model or "", **kw)
    if engine == "mock":
        from .mock_adapter import MockAdapter
        return MockAdapter(model or "mock-1", **kw)
    raise ValueError(f"unknown engine {engine!r}")


__all__ = ["GenRequest", "GenResult", "ServingAdapter", "make_adapter"]
