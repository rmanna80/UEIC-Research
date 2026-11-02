"""vLLM adapter: vLLM's OpenAI-compatible server (``vllm serve <model>``, default port 8000).

Per-request prefill/decode durations are not returned by these endpoints, so they are derived on the
client (prefill ~ TTFT, which also contains queueing; decode = t_end - t_first). Server-side queue
depth and batch occupancy can be sampled from the Prometheus ``/metrics`` endpoint with
``ueic.inference.request_tracing.PrometheusSampler``; the gauge names are configurable because they
have changed between vLLM releases.
"""
from __future__ import annotations

from typing import Any

from ._http import get_json
from .openai_compat import OpenAICompatAdapter


class VLLMAdapter(OpenAICompatAdapter):
    engine = "vllm"

    def __init__(self, base_url: str = "http://127.0.0.1:8000", model: str | None = None, api_key: str | None = None):
        super().__init__(base_url, model, api_key)

    def _extra_info(self) -> dict[str, Any]:
        try:
            return {"engine_version": get_json(f"{self.base}/version").get("version")}
        except Exception as e:  # noqa: BLE001 - optional endpoint
            return {"engine_version": None, "engine_version_error": str(e)}
