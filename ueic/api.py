"""Phase 2 local research API (FastAPI) and the 3-D lab's static files.

Run:  python -m ueic serve          ->  http://127.0.0.1:8765/lab/

Security model (charter section 13): binds to 127.0.0.1 by default; read endpoints
are side-effect free; the only write endpoint registers and runs a simulation
experiment through the same validated, append-only path as the CLI, with a size cap.
Nothing here can touch hardware.
"""
from __future__ import annotations

import csv
import io
import threading
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from . import physics as ph
from .params import REGISTRY, assumptions_table, make_config
from .store import Store, code_hash, core_hash

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
MAX_CELLS = 2000
PHYSICS_OVERRIDABLE = ("r_cond", "r_conv_ref", "n_conv", "kappa_leak", "p_leak_ref", "p_dyn_max", "v_min_ratio",
                       "eta_pump", "dp_ref", "eta_ii_chiller", "dt_drycooler", "fan_ratio", "eta_conv")


def _clean(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return v if np.isfinite(v) else None
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.ndarray):
        return _clean(x.tolist())
    return x


def coldplate(clock: float, t_sup: float, flow: float, t_amb: float, overrides: dict[str, float] | None = None) -> dict:
    """Steady state of the node with every accelerator busy on compute-bound work.
    Same physics functions the simulator and twin use."""
    cfg = make_config(overrides or {})
    s = float(np.clip(clock, cfg.s_min, 1.0))
    R_cond, R_conv, R_cal = cfg.r_cond, float(ph.r_conv(flow, cfg)), float(ph.r_caloric(flow, cfg))
    R = R_cond + R_conv + R_cal
    A = float(ph.temp_independent_power(s, 1.0, cfg))
    L = cfg.p_leak_ref * float(ph.voltage_ratio(s, cfg))
    Tj, ok = ph.steady_temperature(t_sup, R, A, L, cfg)
    out: dict[str, Any] = {"inputs": {"clock": s, "t_sup": t_sup, "flow": flow, "t_amb": t_amb, "overrides": overrides or {}},
                           "resistances_K_per_W": {"caloric": R_cal, "convection": R_conv, "conduction": R_cond, "total": R},
                           "runaway": not bool(ok), "provenance": "analytical_calculation (UEIC physics module; "
                           "inputs mostly class E/F, see /api/params)"}
    if not ok:
        return _clean(out)
    Tj = float(Tj)
    P = A + L * float(np.exp(cfg.kappa_leak * (Tj - cfg.t_leak_ref)))
    N = cfg.n_accel
    P_pump = float(ph.pump_power(flow, cfg))
    pl = ph.plant(N * P + P_pump, t_sup, flow, t_amb, cfg)
    P_grid = N * P / cfg.eta_conv + P_pump + float(pl["P_fan"]) + float(pl["W_ch"])
    out.update({
        "temperatures_C": {"coolant_in": t_sup, "coolant_mean": t_sup + P * R_cal, "wall": t_sup + P * (R_cal + R_conv),
                           "junction": Tj, "coolant_out": float(pl["T_ret"])},
        "power_W": {"chip": P, "chip_leakage": P - A, "node_it": N * P, "pump": P_pump, "fans": float(pl["P_fan"]),
                    "chiller": float(pl["W_ch"]), "conversion_loss": N * P * (1 / cfg.eta_conv - 1), "grid": P_grid},
        "heat_W": {"free_cooling": float(pl["Q_dc"]), "chiller_evaporator": float(pl["Q_ch"])},
        "flow_L_per_min_per_accelerator": cfg.flow_design_lpm * flow,
        "energy_per_work_J": P_grid / (N * s ** cfg.beta_compute),
        "limits_C": {"target": cfg.t_target, "throttle": cfg.t_throttle},
        "within_target": Tj <= cfg.t_target,
    })
    return _clean(out)


def energy_flow(metrics: dict[str, float]) -> dict:
    """Sankey-ready energy accounting for one run. Recovered heat is a subset of rejected
    heat and is never added as a source."""
    g = lambda k: float(metrics.get(k) or 0.0)
    it, conv, pump, fan, ch = g("E_it_kWh"), g("E_conv_loss_kWh"), g("E_pump_kWh"), g("E_fan_kWh"), g("E_chiller_kWh")
    q_dc, q_ch, loop = g("Q_free_cooling_kWh"), g("Q_chiller_kWh"), g("E_loop_storage_kWh")
    grid = g("E_grid_kWh")
    links = [
        ("Grid", "Power conversion loss", conv), ("Grid", "Accelerators (IT)", it), ("Grid", "Pump", pump),
        ("Grid", "Heat-rejection fans", fan), ("Grid", "Chiller compressor", ch),
        ("Accelerators (IT)", "Heat in coolant", it), ("Pump", "Heat in coolant", pump),
        ("Heat in coolant", "Dry cooler (free cooling)", q_dc), ("Heat in coolant", "Chiller evaporator", q_ch),
        ("Dry cooler (free cooling)", "Ambient", q_dc), ("Chiller evaporator", "Ambient", q_ch),
        ("Chiller compressor", "Ambient", ch), ("Heat-rejection fans", "Ambient", fan),
        ("Power conversion loss", "Room heat (not modelled)", conv),
    ]
    stored = it + pump - q_dc - q_ch   # chip + loop storage change over the run (small)
    if abs(stored) > 1e-12:
        links.append(("Heat in coolant", "Stored in chips and loop", stored) if stored > 0
                     else ("Stored in chips and loop", "Heat in coolant", -stored))
    return _clean({"grid_kWh": grid, "links": [{"source": a, "target": b, "kWh": v} for a, b, v in links if v > 1e-12],
                   "reusable_heat_kWh": g("Q_reusable_kWh"), "reusable_exergy_kWh": g("Ex_rejected_kWh"),
                   "loop_storage_kWh": loop,
                   "balance_check_kWh": grid - (conv + it + pump + fan + ch),
                   "note": "Reusable heat (return water >= 45 C) is part of the heat rejected to ambient, shown "
                           "separately; it is not counted as new energy."})


class Jobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs: dict[str, dict[str, Any]] = {}

    def start(self, db: Path, spec: dict, workers: int | None) -> str:
        jid = uuid.uuid4().hex[:12]
        with self.lock:
            self.jobs[jid] = {"status": "running", "done": 0, "total": None, "exp_id": None, "error": None}

        def work():
            from .experiment import run_experiment
            st = Store(db)
            try:
                def prog(done, total):
                    with self.lock:
                        self.jobs[jid].update(done=done, total=total)
                exp_id = run_experiment(spec, st, workers=workers, progress=prog)
                with self.lock:
                    self.jobs[jid].update(status="completed", exp_id=exp_id)
            except Exception as e:  # noqa: BLE001
                with self.lock:
                    self.jobs[jid].update(status="failed", error=str(e))
            finally:
                st.close()
        threading.Thread(target=work, daemon=True).start()
        return jid

    def get(self, jid: str) -> dict[str, Any]:
        with self.lock:
            if jid not in self.jobs:
                raise KeyError(jid)
            return dict(self.jobs[jid])


def create_app(db: str | Path | None = None, workers: int | None = None) -> FastAPI:
    db = Path(db) if db else ROOT / "results" / "ueic.sqlite"
    app = FastAPI(title="UEIC research API", version=__version__,
                  description="Local, read-mostly API over the UEIC experiment store and physics models.")
    jobs = Jobs()

    def store() -> Store:
        return Store(db)

    @app.get("/api/health")
    def health():
        st = store()
        try:
            ok, msg = st.verify_chain()
        finally:
            st.close()
        return {"version": __version__, "code_sha256": code_hash(), "core_sha256": core_hash(),
                "chain_ok": ok, "chain_msg": msg, "db": db.name}

    @app.get("/api/params")
    def params():
        return _clean(assumptions_table())

    @app.get("/api/experiments")
    def experiments():
        st = store()
        try:
            return _clean([{"id": x["id"], "key": x["key"], "version": x["version"], "supersedes": x["supersedes"],
                            "status": x["status"], "title": x["spec"]["title"], "hypothesis": x["spec"]["hypothesis"],
                            "summary": x["summary"], "created": x["created_utc"],
                            "measurement": bool(x["spec"].get("design", {}).get("measurement"))}
                           for x in st.experiments()])
        finally:
            st.close()

    @app.get("/api/experiments/{exp_id}")
    def experiment(exp_id: str):
        st = store()
        try:
            return _clean(st.experiment(exp_id))
        except KeyError:
            raise HTTPException(404, f"no experiment {exp_id}")
        finally:
            st.close()

    @app.get("/api/experiments/{exp_id}/runs")
    def runs(exp_id: str, metrics: str | None = Query(None, description="comma-separated metric names to include")):
        st = store()
        try:
            st.experiment(exp_id)
            rs = st.runs(exp_id)
        except KeyError:
            raise HTTPException(404, f"no experiment {exp_id}")
        finally:
            st.close()
        keep = set(metrics.split(",")) if metrics else None
        for r in rs:
            if keep is not None:
                r["metrics"] = {k: v for k, v in r["metrics"].items() if k in keep}
            r.pop("scenario_resolved", None)
        return _clean(rs)

    @app.get("/api/runs/{run_id}/timeseries")
    def timeseries(run_id: str):
        st = store()
        try:
            ts = st.load_timeseries(run_id)
        finally:
            st.close()
        if not ts:
            raise HTTPException(404, "no time series stored for this run")
        return _clean(ts)

    @app.get("/api/runs/{run_id}/energyflow")
    def energyflow(run_id: str):
        st = store()
        try:
            r = st.db.execute("SELECT name, value FROM metrics WHERE run_id=?", (run_id,)).fetchall()
        finally:
            st.close()
        if not r:
            raise HTTPException(404, f"no run {run_id}")
        return energy_flow(dict(r))

    @app.get("/api/physics/coldplate")
    def api_coldplate(clock: float = Query(1.0, ge=0.5, le=1.0), t_sup: float = Query(25.0, ge=5, le=60),
                      flow: float = Query(1.0, ge=0.25, le=3.0), t_amb: float = Query(20.0, ge=-20, le=50),
                      r_cond: float | None = None, r_conv_ref: float | None = None, kappa_leak: float | None = None,
                      p_leak_ref: float | None = None):
        over = {k: v for k, v in dict(r_cond=r_cond, r_conv_ref=r_conv_ref, kappa_leak=kappa_leak,
                                      p_leak_ref=p_leak_ref).items() if v is not None}
        try:
            return coldplate(clock, t_sup, flow, t_amb, over)
        except (ValueError, KeyError) as e:
            raise HTTPException(422, str(e))

    @app.get("/api/verify")
    def verify():
        st = store()
        try:
            ok, msg = st.verify_chain()
        finally:
            st.close()
        return {"ok": ok, "message": msg}

    @app.get("/api/experiments/{exp_id}/export.csv", response_class=PlainTextResponse)
    def export_csv(exp_id: str):
        st = store()
        try:
            st.experiment(exp_id)
            tmp = io.StringIO()
            rs = st.runs(exp_id)
        except KeyError:
            raise HTTPException(404, f"no experiment {exp_id}")
        finally:
            st.close()
        names = sorted({n for r in rs for n in r["metrics"]})
        w = csv.writer(tmp)
        w.writerow(["run_id", "scenario", "variant", "policy", "seed", "status"] + names)
        for r in rs:
            w.writerow([r["run_id"], r.get("scenario"), r.get("variant"), r.get("policy"), r["seed"], r["status"]]
                       + [r["metrics"].get(n) for n in names])
        return PlainTextResponse(tmp.getvalue(), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{exp_id}.csv"'})

    @app.post("/api/experiments", status_code=202)
    def create_experiment(spec: dict = Body(...)):
        from .experiment import build, expand_cells
        try:
            cells = expand_cells(spec)
            if len(cells) > MAX_CELLS:
                raise ValueError(f"{len(cells)} runs requested; the API limit is {MAX_CELLS} (use the CLI for more)")
            for c in cells:
                build(c)
            from .store import REQUIRED_SPEC_FIELDS
            missing = [k for k in REQUIRED_SPEC_FIELDS if not spec.get(k)]
            if missing:
                raise ValueError(f"missing required fields: {missing}")
        except (KeyError, ValueError, TypeError) as e:
            raise HTTPException(400, str(e))
        return {"job_id": jobs.start(db, spec, workers), "runs": len(cells)}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        try:
            return jobs.get(job_id)
        except KeyError:
            raise HTTPException(404, "no such job")

    @app.get("/api/scenarios")
    def scenarios():
        from .policies import POLICIES
        from .workload import SCENARIOS
        return {"scenarios": {k: v.to_dict() for k, v in SCENARIOS.items()}, "policies": list(POLICIES),
                "physics_overridable": list(PHYSICS_OVERRIDABLE),
                "params": {k: REGISTRY[k].to_dict() for k in REGISTRY}}

    @app.get("/")
    def root():
        return RedirectResponse("/lab/")

    if WEB.exists():
        app.mount("/lab", StaticFiles(directory=WEB, html=True), name="lab")
    dash = ROOT / "results"
    if dash.exists():
        app.mount("/results", StaticFiles(directory=dash), name="results")
    return app


def serve(host: str = "127.0.0.1", port: int = 8765, db: str | None = None, workers: int | None = None):
    import uvicorn
    uvicorn.run(create_app(db, workers), host=host, port=port, log_level="info")
