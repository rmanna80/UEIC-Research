"""Experiment runner: pre-registered spec -> paired simulation runs -> store.

A spec must contain the charter's required fields (research question, hypothesis,
independent/dependent/controlled variables, baseline, evaluation criteria, ...)
and a `design` block:

  "design": {
    "scenarios": ["S1_moderate", ...],
    "policies":  ["fixed", "joint", ...],
    "seeds":     [0, 1, 2],
    "scenario_overrides": {"duration_s": 7200},      # optional, applied to every cell
    "param_overrides": {"dt": 0.5},                    # optional, true plant AND controller model
    "timeseries_seeds": [0],                           # optional
    "variants": [                                       # optional factor
      {"label": "kappa=low", "param_overrides": {"kappa_leak": 0.005}},
      {"label": "model kappa wrong", "model_param_overrides": {"kappa_leak": 0.01}},
      {"label": "routing", "scenario_overrides": {"routing": true}}
    ]
  }
"""
from __future__ import annotations

import json
import os
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from .params import make_config
from .policies import POLICIES
from .sim import simulate
from .store import Store
from .workload import SCENARIOS


def load_spec(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def expand_cells(spec: dict[str, Any]) -> list[dict[str, Any]]:
    d = spec["design"]
    variants = d.get("variants") or [{"label": "default"}]
    ts_seeds = set(d.get("timeseries_seeds", d["seeds"][:1]))
    for name in d["scenarios"]:
        if name not in SCENARIOS:
            raise KeyError(f"Unknown scenario {name}")
    for p in {q for v in variants for q in v.get("policies", d["policies"])}:
        if p not in POLICIES:
            raise KeyError(f"Unknown policy {p}")
    cells = []
    for sc in d["scenarios"]:
        for v in variants:
            for pol in v.get("policies", d["policies"]):     # a variant may run a subset of policies (E013)
                for seed in d["seeds"]:
                    cells.append({
                        "scenario": sc, "variant": v.get("label", "default"), "policy": pol, "seed": int(seed),
                        "scenario_overrides": {**d.get("scenario_overrides", {}), **v.get("scenario_overrides", {})},
                        "param_overrides": {**d.get("param_overrides", {}), **v.get("param_overrides", {})},
                        "model_param_overrides": v.get("model_param_overrides", {}),
                        "record_timeseries": int(seed) in ts_seeds,
                    })
    return cells


def build(cell: dict[str, Any]):
    sc = SCENARIOS[cell["scenario"]]
    if cell["scenario_overrides"]:
        sc = replace(sc, **cell["scenario_overrides"])
    true_over = {**sc.param_overrides, **cell["param_overrides"]}
    cfg = make_config(true_over)
    model_cfg = make_config({**true_over, **cell["model_param_overrides"]})
    return sc, cfg, model_cfg


def run_cell(cell: dict[str, Any]) -> dict[str, Any]:
    """Executed in a worker process. Never raises: failures are returned and recorded."""
    try:
        sc, cfg, model_cfg = build(cell)
        policy = POLICIES[cell["policy"]](model_cfg)
        res = simulate(cfg, sc, policy, cell["seed"], record_timeseries=cell["record_timeseries"])
        return {"ok": True, "metrics": res.metrics, "warnings": res.warnings, "timeseries": res.timeseries}
    except Exception:  # noqa: BLE001 - preserve failed runs
        return {"ok": False, "error": traceback.format_exc()}


def run_experiment(spec: dict[str, Any], store: Store, workers: int | None = None,
                   progress: Callable[[int, int], None] | None = None, supersedes: str | None = None) -> str:
    cells = expand_cells(spec)
    built = [build(c) for c in cells]          # validate every configuration before registering
    exp_id = store.register_experiment(spec, supersedes=supersedes)
    store.set_experiment_status(exp_id, "running")
    run_ids: dict[int, str] = {}
    for i, cell in enumerate(cells):
        sc, cfg, model_cfg = built[i]
        store_cell = {k: cell[k] for k in ("scenario", "variant", "policy", "scenario_overrides",
                                           "param_overrides", "model_param_overrides")}
        store_cell["scenario_resolved"] = sc.to_dict()
        run_ids[i] = store.start_run(exp_id, store_cell, cell["seed"], dict(cfg), dict(model_cfg))
    workers = workers or max(1, (os.cpu_count() or 1))
    n_fail = 0
    done = 0
    if workers == 1:
        results = ((i, run_cell(c)) for i, c in enumerate(cells))
        for i, out in results:
            n_fail += _record(store, run_ids[i], out)
            done += 1
            if progress:
                progress(done, len(cells))
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(run_cell, c): i for i, c in enumerate(cells)}
            for fut in as_completed(futs):
                n_fail += _record(store, run_ids[futs[fut]], fut.result())
                done += 1
                if progress:
                    progress(done, len(cells))
    summary = {"runs": len(cells), "failed": n_fail}
    store.set_experiment_status(exp_id, "completed" if n_fail < len(cells) else "failed", summary)
    store.log(f"Finished {exp_id}: {len(cells)} runs, {n_fail} failed")
    return exp_id


def _record(store: Store, run_id: str, out: dict[str, Any]) -> int:
    if out["ok"]:
        store.finish_run(run_id, out["metrics"], out["warnings"], out["timeseries"])
        return 0
    store.fail_run(run_id, out["error"])
    return 1
