"""Minimal streaming HTTP helpers on the standard library (no client dependency to pin)."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Iterator


def get_json(url: str, timeout_s: float = 5.0) -> Any:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}),
                                timeout=timeout_s) as r:
        return json.loads(r.read().decode())


def post_json(url: str, body: dict, timeout_s: float = 5.0) -> Any:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        return json.loads(r.read().decode())


def stream_lines(url: str, body: dict, timeout_s: float, headers: dict | None = None) -> Iterator[str]:
    """POST ``body`` and yield decoded, non-empty response lines as they arrive.
    ``timeout_s`` bounds each socket read, not the whole request (callers enforce the total)."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        for raw in r:
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                yield line


def classify_error(e: BaseException) -> tuple[str, int | None, str]:
    if isinstance(e, urllib.error.HTTPError):
        try:
            detail = e.read().decode()[:300]
        except Exception:  # noqa: BLE001
            detail = ""
        return "error", e.code, f"HTTP {e.code}: {detail}"
    if isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in str(e):
        return "timeout", None, str(e) or "timed out"
    return "error", None, f"{type(e).__name__}: {e}"
