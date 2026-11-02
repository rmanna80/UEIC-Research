"""Task scoring with documented methods. Correctness is judged against references; a model's own
statement of confidence is never used.

  gsm8k / smoke_arith  final-answer exact match, the scoring used with GSM8K: the reference's number after
                       '####'; the model's number after '####' if present, else its last number; commas
                       removed, compared numerically (|a - b| <= 1e-6).
  multiple_choice      letter extraction ("answer is (X)" / "Answer: X", else the last standalone letter
                       among the options) compared with the reference letter.
  classification       normalised exact match of the first allowed label found in the output.
  summarization        ROUGE-L F1 on lower-cased whitespace tokens (LCS); success = F1 >= threshold set in
                       the experiment spec. ROUGE is a proxy for quality, not a judgement of it.
  humaneval            functional correctness (pass@1 with one sample): the completion plus the dataset's
                       tests run in a separate interpreter with a timeout. Executing model-written code is
                       a risk, so it is OFF unless allow_code_execution=True; when off the item is unscored
                       (None), never counted as correct or incorrect. Use a disposable VM or container.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from typing import Any

_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def _to_float(s: str) -> float | None:
    s = s.replace(",", "").rstrip(".")
    try:
        return float(s)
    except ValueError:
        return None


def extract_final_number(text: str) -> float | None:
    m = re.search(r"####\s*\$?\s*(-?[\d,]*\.?\d+)", text)
    if m:
        return _to_float(m.group(1))
    nums = _NUM.findall(text)
    return _to_float(nums[-1]) if nums else None


def score_numeric(output: str, reference: str) -> tuple[bool | None, float | None, str]:
    ref = extract_final_number(reference)
    if ref is None:
        return None, None, "numeric_exact: reference has no number"
    got = extract_final_number(output)
    ok = got is not None and abs(got - ref) <= 1e-6
    return ok, float(ok), "numeric_exact"


def extract_choice(text: str, options: str = "ABCD") -> str | None:
    m = re.search(rf"answer\s*(?:is|:)?\s*\(?([{options}])\)?\b", text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    letters = re.findall(rf"\b([{options}])\b", text)
    return letters[-1] if letters else None


def score_choice(output: str, reference: str, options: str = "ABCD") -> tuple[bool | None, float | None, str]:
    got = extract_choice(output, options)
    ok = got is not None and got == reference.strip().upper()
    return ok, float(ok), "choice_letter"


def score_label(output: str, reference: str, labels: list[str]) -> tuple[bool | None, float | None, str]:
    low = output.lower()
    pos = [(low.find(l.lower()), l) for l in labels if low.find(l.lower()) >= 0]
    got = min(pos)[1] if pos else None
    ok = got is not None and got.lower() == reference.strip().lower()
    return ok, float(ok), "label_exact"


def rouge_l_f1(candidate: str, reference: str) -> float:
    a, b = candidate.lower().split(), reference.lower().split()
    if not a or not b:
        return 0.0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0] * (len(b) + 1)
        for j, y in enumerate(b, 1):
            cur[j] = prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1])
        prev = cur
    lcs = prev[-1]
    if lcs == 0:
        return 0.0
    p, r = lcs / len(a), lcs / len(b)
    return 2 * p * r / (p + r)


def _extract_code(output: str) -> str:
    m = re.search(r"```(?:python)?\n(.*?)```", output, re.DOTALL)
    return m.group(1) if m else output


def score_humaneval(output: str, item: dict[str, Any], allow_code_execution: bool = False,
                    timeout_s: float = 10.0) -> tuple[bool | None, float | None, str]:
    if not allow_code_execution:
        return None, None, "humaneval: code execution disabled (unscored)"
    code = _extract_code(output)
    if f"def {item['entry_point']}" not in code:
        code = item.get("code_prompt", "") + code
    program = f"{code}\n\n{item['test']}\n\ncheck({item['entry_point']})\n"
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "prog.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(program)
        try:
            r = subprocess.run([sys.executable, "-I", path], cwd=d, capture_output=True, timeout=timeout_s,
                               env={"PATH": os.environ.get("PATH", "")})
            ok = r.returncode == 0
        except subprocess.TimeoutExpired:
            return False, 0.0, "humaneval_pass@1: timeout"
    return ok, float(ok), "humaneval_pass@1"


def make_scorer(task_cfg: dict[str, Any] | None = None):
    """Return scorer(item, output) -> (correct, score, method) dispatching on item['task']."""
    cfg = task_cfg or {}

    def scorer(item: dict[str, Any], output: str):
        t = item["task"]
        if t in ("gsm8k", "smoke_arith"):
            return score_numeric(output, item["reference"])
        if t == "multiple_choice":
            return score_choice(output, item["reference"], item.get("options", "ABCD"))
        if t == "classification":
            return score_label(output, item["reference"], item["labels"])
        if t == "summarization":
            f1 = rouge_l_f1(output, item["reference"])
            return f1 >= cfg.get("rouge_l_threshold", 0.3), f1, "rouge_l_f1"
        if t == "humaneval":
            return score_humaneval(output, item, cfg.get("allow_code_execution", False), cfg.get("code_timeout_s", 10.0))
        return None, None, f"no scorer for task {t!r}"
    return scorer
