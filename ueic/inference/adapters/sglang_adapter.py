"""SGLang adapter through its OpenAI-compatible endpoints (default port 30000).

Only the OpenAI-compatible routes are used. SGLang's native routes are deliberately not used here,
because this adapter has not yet been exercised against a live SGLang server (status: untested
against a real engine; covered by the shared OpenAI-compatible client tests).
"""
from __future__ import annotations

from .openai_compat import OpenAICompatAdapter


class SGLangAdapter(OpenAICompatAdapter):
    engine = "sglang"

    def __init__(self, base_url: str = "http://127.0.0.1:30000", model: str | None = None, api_key: str | None = None):
        super().__init__(base_url, model, api_key)
