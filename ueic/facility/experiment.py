"""Runner for facility experiments (``"kind": "facility"`` specs) on the same append-only store.

Cells = conditions x schedulers x seeds. A cell is stored with scenario = variant = condition label and
policy = scheduler name, so the store's integrity chain, exports and the paired-analysis helpers apply
unchanged. Jobs are generated from (condition, seed) only, so every scheduler sees the same workload
realisation (paired design).
"""
from __future__ import annotations

import os
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Callable

from ..sim import PROV_SIM
from ..store import Store
from .cluster import from_dict, load
from .facility_simulator import FacilityConfig, FacilitySim
from .jobs import JobSpec, generate

UNITS = {"jobs_arrived": "count", "jobs_completed": "count", "jobs_on_time": "count", "on_time_frac": "-",
         "jobs_unfinished": "count", "work_done_gpu_s": "GPU*s", "mean_wait_s": "s", "p95_wait_s": "s",
         "E_grid_kWh": "kWh", "E_it_kWh": "kWh", "E_pump_kWh": "kWh", "E_fan_kWh": "kWh", "E_chiller_kWh": "kWh",
         "E_per_job_kJ": "kJ", "E_per_work_kJ": "kJ/(GPU*s)", "E_per_on_time_job_kJ": "kJ",
         "chip_s_over_target": "chip*s", "throttle_gpu_s": "GPU*s", "T_max_C": "degC", "T_sup_mean_C": "degC",
         "cap_steps": "count", "P_grid_peak_kW": "kW", "utilisation": "-", "energy_balance_rel": "-", "n_gpus": "count",
         "cost": "currency (illustrative tariff)", "co2_kg": "kg (illustrative intensity)", "deferrals": "count",
         "E_event_kWh": "kWh", "E_above_cap_kWh": "kWh", "max_exceed_kW": "kW", "t_over_cap_s": "s",
         "work_in_event_gpu_s": "GPU*s", "storage_used_kWh_th": "kWh_th", "storage_charge_kWh_el": "kWh"}


def expand(spec: dict[str, Any]) -> list[dict[str, Any]]:
    d = spec["design"]
    from ..scheduling.placement import SCHEDULERS
    cells = []
    for c in d["conditions"]:
        for s in c.get("schedulers", d["schedulers"]):
            if s not in SCHEDULERS:
                raise KeyError(f"unknown scheduler {s}")
            for seed in d["seeds"]:
                cells.append({"scenario": c["label"], "variant": c["label"], "policy": s, "seed": int(seed),
                              "topology": c["topology"], "jobs": c.get("jobs", {}), "facility": c.get("facility", {}),
                              "params": c.get("params", {}), "scheduler_kw": d.get("scheduler_kw", {}).get(s, {}),
                              "record_timeseries": int(seed) in d.get("timeseries_seeds", d["seeds"][:1])})
    return cells


def build(cell: dict[str, Any]):
    from ..scheduling.placement import make_scheduler
    topo = cell["topology"]
    cl = from_dict(topo) if isinstance(topo, dict) else load(topo)
    fac = dict(cell["facility"])
    for k in ("grid_caps", "storage_charge"):
        if k in fac:
            fac[k] = tuple(tuple(x) for x in fac[k])
    fc = FacilityConfig(**fac)
    js = JobSpec(**{k: tuple(tuple(x) for x in v) if k == "bursts" else (tuple(v) if isinstance(v, list) else v)
                    for k, v in cell["jobs"].items()})
    jobs = generate(js, cl.n_gpus, fc.duration_s, cell["seed"])
    return FacilitySim(cl, make_scheduler(cell["policy"], **cell["scheduler_kw"]), jobs, fc, cell["params"])


def run_cell(cell: dict[str, Any]) -> dict[str, Any]:
    try:
        sim = build(cell)
        out = sim.run()
        m = {k: (float(v), UNITS.get(k, "-"), PROV_SIM) for k, v in out["metrics"].items()}
        dec = getattr(sim.sched, "decisions", None)
        if dec:
            for k, v in dec.items():
                m[f"decisions_{k}"] = (float(v), "count", PROV_SIM)
        warn = []
        if abs(out["metrics"]["energy_balance_rel"]) > 1e-9:
            warn.append(f"energy balance residual {out['metrics']['energy_balance_rel']:.2e}")
        return {"ok": True, "metrics": m, "warnings": warn,
                "timeseries": out["timeseries"] if cell["record_timeseries"] else None}
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": traceback.format_exc()}


def run_facility_experiment(spec: dict[str, Any], store: Store, workers: int | None = None,
                            progress: Callable[[int, int], None] | None = None) -> str:
    cells = expand(spec)
    for c in cells[: len(spec["design"]["conditions"])]:
        build({**c, "facility": {**c["facility"], "duration_s": 1.0, "drain_s": 0.0}})   # validate before registering
    exp_id = store.register_experiment(spec)
    store.set_experiment_status(exp_id, "running")
    from .cluster import from_dict as _fd
    ids = {}
    for i, c in enumerate(cells):
        cl = _fd(c["topology"]) if isinstance(c["topology"], dict) else load(c["topology"])
        store_cell = {k: c[k] for k in ("scenario", "variant", "policy", "topology", "jobs", "facility", "scheduler_kw")}
        store_cell["n_gpus"] = cl.n_gpus
        ids[i] = store.start_run(exp_id, store_cell, c["seed"], dict(c["params"]), dict(c["params"]))
    n_fail = done = 0
    with ProcessPoolExecutor(max_workers=workers or max(1, os.cpu_count() or 1)) as ex:
        futs = {ex.submit(run_cell, c): i for i, c in enumerate(cells)}
        for fut in as_completed(futs):
            out = fut.result()
            if out["ok"]:
                store.finish_run(ids[futs[fut]], out["metrics"], out["warnings"], out["timeseries"])
            else:
                store.fail_run(ids[futs[fut]], out["error"]); n_fail += 1
            done += 1
            if progress:
                progress(done, len(cells))
    store.set_experiment_status(exp_id, "completed" if n_fail < len(cells) else "failed",
                                {"runs": len(cells), "failed": n_fail})
    store.log(f"Finished {exp_id}: {len(cells)} runs, {n_fail} failed")
    return exp_id
