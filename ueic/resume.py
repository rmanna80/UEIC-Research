"""Time-budgeted execution and resumption of registered experiments.

Why this exists: background jobs in the cloud workspace are stopped after two hours. E021 was
interrupted that way twice. Instead of aborting and re-registering every time, an experiment
that was registered but never finalised can be *continued in its own record*:

* the registered spec, run ids, cells, seeds and configurations are reused unchanged;
* each pending run is executed with the same ``run_cell`` function as the original runner and
  sealed into the same hash chain;
* nothing that is already finalised is touched.

A resumption is refused unless
  1. the experiment is still ``running`` (never completed, failed or aborted);
  2. the simulation-core hash equals the one recorded at registration;
  3. every stored cell, seed and configuration hash is reproduced exactly from the stored spec;
  4. re-simulating ``n_check`` already completed runs reproduces their stored metrics (and time
     series, when recorded) exactly; host wall-clock timings are the only metrics exempt.
Each resumption is written to the research log with both hashes and the runs it reproduced.

``start`` registers an experiment exactly as ``experiment.run_experiment`` /
``facility.experiment.run_facility_experiment`` do (a test checks the stored records and metrics
are identical) and then executes it under a time budget. Runs already in flight when the budget
ends are allowed to finish; no new runs are started.
"""
from __future__ import annotations

import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from typing import Any, Callable

import numpy as np

from .store import Store, canonical, code_hash, core_hash, sha256, timeseries_csv


# Wall-clock timings of the host computer (controller and simulation time) are stored with this provenance.
# They are real measurements of this machine, not simulated quantities, so they are not expected to repeat
# and are excluded from the reproduction check (as in the bitwise reproduction tests).
HOST_TIMING = "physical_measurement"


class ResumeRefused(RuntimeError):
    pass


# ------------------------------------------------------------------------------------ records
def _records(spec: dict[str, Any]) -> tuple[Callable, list[dict[str, Any]]]:
    """(run_cell function, per-cell records) exactly as the original runner would store them."""
    if spec.get("kind") == "facility":
        from .facility import experiment as fx
        from .facility.cluster import from_dict, load
        cells = fx.expand(spec)
        recs = []
        for c in cells:
            cl = from_dict(c["topology"]) if isinstance(c["topology"], dict) else load(c["topology"])
            store_cell = {k: c[k] for k in ("scenario", "variant", "policy", "topology", "jobs", "facility",
                                            "scheduler_kw")}
            store_cell["n_gpus"] = cl.n_gpus
            recs.append({"cell": c, "store_cell": store_cell, "seed": c["seed"],
                         "config": dict(c["params"]), "model_config": dict(c["params"])})
        return fx.run_cell, recs
    if spec.get("kind") == "hardware_protocol":
        raise ValueError(f"{spec['key']} is a hardware protocol; it is executed by the operator, not simulated")
    from . import experiment as ex
    cells = ex.expand_cells(spec)
    recs = []
    for c in cells:
        sc, cfg, model_cfg = ex.build(c)
        store_cell = {k: c[k] for k in ("scenario", "variant", "policy", "scenario_overrides",
                                        "param_overrides", "model_param_overrides")}
        store_cell["scenario_resolved"] = sc.to_dict()
        recs.append({"cell": c, "store_cell": store_cell, "seed": c["seed"],
                     "config": dict(cfg), "model_config": dict(model_cfg)})
    return ex.run_cell, recs


def _validate_facility(spec: dict[str, Any]) -> None:
    """The facility runner's pre-registration check (one short build per condition)."""
    from .facility import experiment as fx
    cells = fx.expand(spec)
    for c in cells[: len(spec["design"]["conditions"])]:
        fx.build({**c, "facility": {**c["facility"], "duration_s": 1.0, "drain_s": 0.0}})


def _record(store: Store, run_id: str, out: dict[str, Any]) -> int:
    if out["ok"]:
        store.finish_run(run_id, out["metrics"], out["warnings"], out["timeseries"])
        return 0
    store.fail_run(run_id, out["error"])
    return 1


# ---------------------------------------------------------------------------------- execution
def _execute(store: Store, fn: Callable, items: list[tuple[str, dict]], workers: int,
             deadline: float | None, progress: Callable[[int, int], None] | None, done: int, total: int) -> int:
    """Run (run_id, cell) items, at most `workers` at a time; start nothing new after `deadline`."""
    n_fail = 0
    it = iter(items)
    expired = lambda: deadline is not None and time.monotonic() >= deadline  # noqa: E731
    if workers <= 1:
        for rid, cell in it:
            if expired():
                break
            n_fail += _record(store, rid, fn(cell))
            done += 1
            if progress:
                progress(done, total)
        return n_fail
    with ProcessPoolExecutor(max_workers=workers) as ex:
        inflight: dict[Any, str] = {}

        def fill():
            while len(inflight) < workers and not expired():
                nxt = next(it, None)
                if nxt is None:
                    return
                inflight[ex.submit(fn, nxt[1])] = nxt[0]
        fill()
        while inflight:
            finished, _ = wait(inflight, return_when=FIRST_COMPLETED)
            for f in finished:
                n_fail += _record(store, inflight.pop(f), f.result())
                done += 1
                if progress:
                    progress(done, total)
            fill()
    return n_fail


def _finalise_if_done(store: Store, exp_id: str) -> dict[str, Any]:
    counts = dict(store.db.execute("SELECT status, count(*) FROM runs WHERE experiment_id=? GROUP BY status", (exp_id,)))
    total = sum(counts.values())
    pending = counts.get("running", 0)
    if pending:
        return {"exp_id": exp_id, "status": "running", "runs": total, "pending": pending,
                "failed": counts.get("failed", 0)}
    n_fail = counts.get("failed", 0)
    sessions = store.db.execute("SELECT count(*) FROM research_log WHERE entry LIKE ?",
                                (f"Resumed {exp_id}:%",)).fetchone()[0]
    summary = {"runs": total, "failed": n_fail}
    if sessions:
        summary["resumed_sessions"] = sessions
    status = "completed" if n_fail < total else "failed"
    store.set_experiment_status(exp_id, status, summary)
    store.log(f"Finished {exp_id}: {total} runs, {n_fail} failed")
    return {"exp_id": exp_id, "status": status, "runs": total, "pending": 0, "failed": n_fail}


# ------------------------------------------------------------------------------- public API
def start(spec: dict[str, Any], store: Store, workers: int | None = None, max_minutes: float | None = None,
          supersedes: str | None = None, progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    """Register `spec` exactly as the standard runners do, then execute it within `max_minutes`."""
    import os
    t0 = time.monotonic()
    if spec.get("kind") == "facility":
        _validate_facility(spec)
    fn, recs = _records(spec)                  # builds every configuration: invalid specs fail before registration
    exp_id = store.register_experiment(spec, supersedes=supersedes)
    store.set_experiment_status(exp_id, "running")
    items = [(store.start_run(exp_id, r["store_cell"], r["seed"], r["config"], r["model_config"]), r["cell"])
             for r in recs]
    deadline = None if max_minutes is None else t0 + 60.0 * max_minutes
    _execute(store, fn, items, workers or max(1, os.cpu_count() or 1), deadline, progress, 0, len(items))
    return _finalise_if_done(store, exp_id)


def check_resumable(store: Store, exp_id: str) -> tuple[Callable, list[tuple[str, dict]], list[tuple[str, dict]]]:
    """Checks 1-3 of the module docstring. Returns (run_cell, pending items, completed items)."""
    exp = store.experiment(exp_id)
    if exp["status"] != "running":
        raise ResumeRefused(f"{exp_id} is '{exp['status']}'; only unfinished ('running') experiments can be resumed")
    reg_core = (exp["host"] or {}).get("core_sha256")
    now_core = core_hash()
    if reg_core != now_core:
        raise ResumeRefused(f"simulation-core hash changed since registration ({str(reg_core)[:12]} -> {now_core[:12]}); "
                            "abort the experiment and re-run it as a superseding version")
    fn, recs = _records(exp["spec"])
    rows = list(store.db.execute("SELECT id, cell_json, seed, config_sha256, model_config_sha256, status "
                                 "FROM runs WHERE experiment_id=? ORDER BY rowid", (exp_id,)))
    if len(rows) != len(recs):
        raise ResumeRefused(f"{len(rows)} stored runs but the registered spec expands to {len(recs)} cells")
    pending, completed = [], []
    for (rid, cj, seed, cfg_h, mcfg_h, status), r in zip(rows, recs):
        if (cj != canonical(r["store_cell"]) or seed != int(r["seed"]) or cfg_h != sha256(canonical(r["config"]))
                or mcfg_h != sha256(canonical(r["model_config"]))):
            raise ResumeRefused(f"stored run {rid} does not match the cell the registered spec produces")
        if status == "running":
            pending.append((rid, r["cell"]))
        elif status == "completed":
            completed.append((rid, r["cell"]))
    return fn, pending, completed


def _same(store: Store, rid: str, out: dict[str, Any]) -> str | None:
    """None if `out` reproduces stored run `rid` exactly, else a description of the first difference."""
    if not out["ok"]:
        return "re-simulation failed: " + out["error"].strip().splitlines()[-1]
    rows = list(store.db.execute("SELECT name, value, provenance FROM metrics WHERE run_id=?", (rid,)))
    stored = {n: v for n, v, _ in rows}
    host_timing = {n for n, _, prov in rows if prov == HOST_TIMING}
    new = {}
    for n, (v, _u, _p) in out["metrics"].items():
        new[n] = None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
    if stored.keys() != new.keys():
        return f"metric names differ: {sorted(stored.keys() ^ new.keys())[:5]}"
    for n in sorted(stored.keys() - host_timing):
        if stored[n] != new[n]:
            return f"metric {n}: stored {stored[n]!r}, re-simulated {new[n]!r}"
    ts_h = store.db.execute("SELECT timeseries_sha256 FROM runs WHERE id=?", (rid,)).fetchone()[0]
    raw = timeseries_csv(out.get("timeseries") or {})
    if (sha256(raw) if raw else None) != ts_h:
        return "time series differs"
    return None


def resume(store: Store, exp_id: str, workers: int | None = None, max_minutes: float | None = None,
           n_check: int = 1, progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    """Continue an unfinished experiment in its own record (see the module docstring for the checks)."""
    import os
    t0 = time.monotonic()
    workers = workers or max(1, os.cpu_count() or 1)
    fn, pending, completed = check_resumable(store, exp_id)
    checked = []
    if n_check and completed:
        # deterministic choice: evenly spaced over the completed runs, first and last included
        k = min(n_check, len(completed))
        idx = sorted({round(i * (len(completed) - 1) / max(1, k - 1)) for i in range(k)})
        sample = [completed[i] for i in idx]
        if workers > 1 and len(sample) > 1:
            with ProcessPoolExecutor(max_workers=min(workers, len(sample))) as ex:
                outs = list(ex.map(fn, [c for _, c in sample]))
        else:
            outs = [fn(c) for _, c in sample]
        for (rid, _), out in zip(sample, outs):
            diff = _same(store, rid, out)
            if diff:
                raise ResumeRefused(f"re-simulating completed run {rid} did not reproduce it ({diff}); not resuming")
            checked.append(rid)
    exp = store.experiment(exp_id)
    store.log(f"Resumed {exp_id}: {len(pending)} pending of {len(pending) + len(completed)} runs; "
              f"core hash {core_hash()[:12]} matches registration; reproduced {len(checked)} completed run(s) exactly "
              f"({', '.join(r[:8] for r in checked) or 'none available'}); package code hash {code_hash()[:12]} "
              f"(registered {exp['code_sha256'][:12]})")
    done = store.db.execute("SELECT count(*) FROM runs WHERE experiment_id=? AND status!='running'",
                            (exp_id,)).fetchone()[0]
    total = done + len(pending)
    deadline = None if max_minutes is None else t0 + 60.0 * max_minutes
    _execute(store, fn, pending, workers, deadline, progress, done, total)
    out = _finalise_if_done(store, exp_id)
    out["reproduced"] = checked
    return out


def queue(paths: list[str], store: Store, workers: int | None = None, max_minutes: float | None = None,
          n_check: int = 1, log: Callable[[str], None] = print) -> bool:
    """Run specs in order within one time budget, continuing any registered-but-unfinished experiment whose
    stored spec is byte-identical to the file. Specs with a completed experiment of identical spec are
    skipped. Returns True when every spec is completed (or not simulable)."""
    from .experiment import load_spec
    t_end = None if max_minutes is None else time.monotonic() + 60.0 * max_minutes

    def left() -> float | None:
        return None if t_end is None else max(0.0, (t_end - time.monotonic()) / 60.0)

    def prog(d, n):
        if d == n or d % max(1, n // 20) == 0:
            log(f"  {d}/{n} runs")

    for p in paths:
        spec = load_spec(p)
        if spec.get("kind") == "hardware_protocol":
            log(f"{spec['key']}: hardware protocol, not simulated (skipped)")
            continue
        sh = sha256(canonical(spec))
        rows = list(store.db.execute("SELECT id, status FROM experiments WHERE key=? AND spec_sha256=? "
                                     "ORDER BY created_utc, rowid", (spec["key"], sh)))
        if any(s == "completed" for _, s in rows):
            log(f"{spec['key']}: completed ({[i for i, s in rows if s == 'completed'][-1]}), skipped")
            continue
        if left() is not None and left() <= 0:
            return False
        running = [i for i, s in rows if s == "running"]
        if len(running) > 1:
            raise ResumeRefused(f"{spec['key']}: several unfinished experiments with this spec: {running}")
        if running:
            log(f"{spec['key']}: resuming {running[0]}")
            out = resume(store, running[0], workers, left(), n_check, prog)
        else:
            sup = None
            failed = [i for i, s in rows if s == "failed"]
            if failed:
                sup = failed[-1]           # an aborted attempt of the same spec is superseded, never deleted
            log(f"{spec['key']}: starting" + (f" (supersedes {sup})" if sup else ""))
            out = start(spec, store, workers, left(), sup, prog)
        log(f"{spec['key']}: {out}")
        if out["status"] == "running":
            return False
    return True
