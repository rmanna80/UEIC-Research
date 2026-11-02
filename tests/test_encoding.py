"""Every text read or write in the project names its encoding.

Without ``encoding=``, Python uses the locale's encoding: UTF-8 on Linux and macOS, usually cp1252 on Windows.
The reports and specs contain characters such as '→' and '°C', so ``ueic report`` crashed on Windows
(UnicodeEncodeError writing docs/RESULTS.md), and a spec read there would be decoded into different text than
on Linux. This test fails if any text-mode ``open``, ``read_text`` or ``write_text`` call omits the encoding.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRS = ("ueic", "experiments", "tests")


def _text_io_without_encoding(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
        if name not in ("open", "read_text", "write_text") or any(k.arg == "encoding" for k in n.keywords):
            continue
        if name == "open":
            mode = n.args[1].value if len(n.args) >= 2 and isinstance(n.args[1], ast.Constant) else None
            mode = next((k.value.value for k in n.keywords if k.arg == "mode" and isinstance(k.value, ast.Constant)), mode)
            is_gzip = isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "gzip"
            binary = (mode is not None and "b" in str(mode)) or (is_gzip and (mode is None or "t" not in str(mode)))
            if binary or (mode is not None and not isinstance(mode, str)):
                continue
        out.append(f"{path.relative_to(ROOT)}:{n.lineno} {name}")
    return out


def test_all_text_io_names_its_encoding():
    files = [p for d in DIRS for p in sorted((ROOT / d).rglob("*.py")) if "__pycache__" not in p.parts]
    assert len(files) > 50
    missing = [s for p in files for s in _text_io_without_encoding(p)]
    assert not missing, "text I/O without encoding= (breaks on Windows):\n" + "\n".join(missing)


def test_detector_catches_a_missing_encoding(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text('from pathlib import Path\nPath("x").write_text("→")\nopen("y", "w")\nopen("z", "rb")\n',
                   encoding="utf-8")
    global ROOT
    old, ROOT = ROOT, tmp_path
    try:
        found = _text_io_without_encoding(bad)
    finally:
        ROOT = old
    assert found == ["bad.py:2 write_text", "bad.py:3 open"]
