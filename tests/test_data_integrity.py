"""Every recorded measurement file still has the SHA-256 written next to it when it was recorded.

The telemetry recorder stores the CSV's hash in ``*.meta.json`` (and the session's ``session.json``). If git, an
editor or a copy changes a single byte, including line endings, this test fails. ``.gitattributes`` marks
``data/`` as binary-safe (``-text``) so git on Windows does not convert CRLF to LF on commit.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _metas():
    return sorted((ROOT / "data").rglob("*.meta.json"))


def test_measurement_files_match_their_recorded_sha256():
    metas = _metas()
    assert metas, "no recorded telemetry found under data/"
    bad = []
    for meta in metas:
        m = json.loads(meta.read_text(encoding="utf-8"))
        csv_path = meta.parent / m["csv"]
        if hashlib.sha256(csv_path.read_bytes()).hexdigest() != m["csv_sha256"]:
            bad.append(str(csv_path.relative_to(ROOT)))
    assert not bad, "measurement files changed since recording:\n" + "\n".join(bad)


def test_session_records_point_at_the_same_telemetry():
    for sess_path in sorted((ROOT / "data").rglob("session.json")):
        sess = json.loads(sess_path.read_text(encoding="utf-8"))
        meta_path = sess_path.parent / "telemetry.meta.json"
        if "telemetry_sha256" in sess and meta_path.exists():
            assert sess["telemetry_sha256"] == json.loads(meta_path.read_text(encoding="utf-8"))["csv_sha256"], sess_path
