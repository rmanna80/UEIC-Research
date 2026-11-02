"""Operator procedures and pre-registered analysis for hardware inference experiments (E017).

``plan_e017`` prints a procedure for the operator to review and run; it executes nothing. Clock locks
are applied by the operator (administrator shell) and released afterwards. ``analyze_e017`` applies the
selection rules fixed in the spec to recorded sessions; it was written before any session existed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


def parse_label(label: str) -> dict[str, str]:
    return dict(kv.split("=", 1) for kv in label.split(";") if "=" in kv)


def plan_e017(spec: dict[str, Any], models: list[str], f_sus_MHz: int, f_low_MHz: int | None = None,
              dataset: str = "data/datasets/gsm8k_test_items.jsonl", seed: int = 17) -> str:
    c = spec["configuration"]
    f_low = f_low_MHz or int(round(0.75 * f_sus_MHz))
    clocks = {"default": None, "f_sus": f_sus_MHz, "0.75*f_sus": f_low}
    configs = [(m, ck, n) for m in models for ck in c["clocks"] for n in c["concurrency"]]
    order = np.random.default_rng(seed).permutation(len(configs))
    L = ["# E017 operator procedure (review before running; nothing here runs by itself)",
         "# 1. Convert GSM8K once:",
         "#    python -c \"import json;from ueic.inference.workload_generator import from_gsm8k as f;"
         "rows=[json.loads(l) for l in open('test.jsonl')];open('" + dataset + "','w').write("
         "'\\n'.join(json.dumps(r) for r in f(rows)))\"",
         "# 2. For each block below: set the clock (admin shell), restart Ollama with the concurrency, run.",
         "#    Reset clocks at the end (and if anything goes wrong): nvidia-smi -rgc", ""]
    lo, hi = c["selection_items"]
    for k, i in enumerate(order):
        m, ck, n = configs[i]
        f = clocks[ck]
        lab = f"model={m};clock={ck};conc={n};split=sel;rep=0"
        L.append(f"## selection {k + 1}/{len(configs)}: {lab}")
        L.append("nvidia-smi -rgc" if f is None else f"nvidia-smi -lgc {f},{f}")
        L.append(f"$env:OLLAMA_NUM_PARALLEL={n}; (restart `ollama serve`)")
        L.append(f"python -m ueic infer run --engine ollama --model {m} --items {dataset} --offset {lo} --limit {hi - lo} "
                 f"--concurrency {n} --deadline-s {c['deadline_s']} --max-tokens {c['max_tokens']} "
                 f"--label \"{lab}\"" + (f" --expect-clock {f}" if f else "") +
                 f" --idle-s 60 --out data/inference/E017")
        L.append("")
    L += [f"# 3. Then: python -m ueic infer analyze-e017 data/inference/E017 --larger-model {models[-1]}  "
          "(state the model with more parameters) -> selected arms (B0, B1, B2, J)",
          f"# 4. Holdout: run each selected arm {c['repeats_holdout']} times on items "
          f"{c['holdout_items'][0]}-{c['holdout_items'][1] - 1} in the shuffled order that analyze-e017 prints,",
          "#    with split=hold;rep=<k> in the label. Finish with: nvidia-smi -rgc"]
    return "\n".join(L)


def _sessions(root: str | Path) -> list[dict[str, Any]]:
    out = []
    for sj in sorted(Path(root).rglob("summary.json")):
        d = sj.parent
        meta = json.loads((d / "session.json").read_text(encoding="utf-8"))
        summ = json.loads(sj.read_text(encoding="utf-8"))
        traces = [json.loads(x) for x in (d / "traces.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        out.append({"dir": str(d), "label": parse_label(meta.get("label", "")), "summary": summ, "traces": traces})
    return out


def _config_key(lab: dict[str, str]) -> tuple[str, str, str]:
    return lab.get("model", "?"), lab.get("clock", "?"), lab.get("conc", "?")


def select_arms(sessions: list[dict[str, Any]], spec: dict[str, Any], larger_model: str,
                boundary: str = "gpu_total") -> dict[str, Any]:
    """Apply E017's selection rules to selection-split sessions (guard-failed sessions excluded)."""
    c = spec["configuration"]
    rows = {}
    excluded = []
    for s in sessions:
        if s["label"].get("split") != "sel":
            continue
        if s["summary"].get("guard_failed"):
            excluded.append((s["dir"], s["summary"].get("guard_problems")))
            continue
        lat = s["summary"]["latency"]
        em = (s["summary"].get("energy", {}).get("metrics") or {}).get(boundary, {})
        rows[_config_key(s["label"])] = {
            "accuracy": lat["n_correct"] / max(lat["n"], 1), "miss_rate": lat["n_deadline_missed"] / max(lat["n"], 1),
            "J_per_useful": em.get("J_per_useful_result", float("nan")), "J_per_out_tok": em.get("J_per_output_token", float("nan"))}
    if not rows:
        return {"rows": {}, "excluded": excluded, "arms": {}}
    q_min = c["q_min_factor"] * max(r["accuracy"] for r in rows.values())
    feas = {k: r for k, r in rows.items() if r["accuracy"] >= q_min and r["miss_rate"] <= c["max_deadline_miss"]
            and np.isfinite(r["J_per_useful"])}
    best = lambda ks: min(ks, key=lambda k: feas[k]["J_per_useful"]) if ks else None   # noqa: E731
    larger = larger_model                  # stated by the operator (parameter count), never inferred from names
    arms = {"B0": (larger, "default", "1") if (larger, "default", "1") in rows else None,
            "B1": best([k for k in feas if k[1] == "default"]),
            "B2": best([k for k in feas if k[0] == larger and k[2] == "1"]),
            "J": best(list(feas))}
    tok_best = min(rows, key=lambda k: rows[k]["J_per_out_tok"])
    return {"rows": {"|".join(k): v for k, v in rows.items()}, "q_min": q_min, "excluded": excluded,
            "arms": {a: ("|".join(k) if k else None) for a, k in arms.items()},
            "H3_lowest_J_per_token": "|".join(tok_best), "H3_supported": arms["J"] is not None and tok_best != arms["J"]}


def holdout_ratio(sessions: list[dict[str, Any]], arm_a: str, arm_b: str, boundary: str = "gpu_total",
                  n_boot: int = 2000, seed: int = 0) -> dict[str, Any]:
    """Energy per useful result of arm A over arm B on holdout sessions, with a two-level bootstrap
    (sessions, then items within a session; session energy is spread equally over its items)."""
    def arm(name):
        out = []
        for s in sessions:
            if s["label"].get("split") == "hold" and "|".join(_config_key(s["label"])) == name and not s["summary"].get("guard_failed"):
                E = (s["summary"]["energy"]["metrics"][boundary])["E_J"]
                tr = s["traces"]
                useful = np.array([bool(t["correct"]) and t["deadline_met"] is not False and t["status"] == "ok" for t in tr])
                out.append((E / max(len(tr), 1), useful))
        return out
    A, B = arm(arm_a), arm(arm_b)
    if not A or not B:
        return {"ratio": None, "reason": "missing holdout sessions"}
    rng = np.random.default_rng(seed)
    def epu(S, boot):
        e = u = 0.0
        idx = rng.integers(0, len(S), len(S)) if boot else range(len(S))
        for i in idx:
            per_item, useful = S[i]
            j = rng.integers(0, useful.size, useful.size) if boot else np.arange(useful.size)
            e += per_item * j.size
            u += useful[j].sum()
        return e / u if u else np.inf
    point = epu(A, False) / epu(B, False) - 1
    draws = np.array([epu(A, True) / epu(B, True) - 1 for _ in range(n_boot)])
    lo, hi = np.percentile(draws[np.isfinite(draws)], [2.5, 97.5])
    return {"ratio": float(point), "lo": float(lo), "hi": float(hi), "n_sessions": (len(A), len(B))}
