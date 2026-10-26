"""Phase 2 API: values served to the 3-D lab must equal what the simulator's own
physics and store say, and the write path must keep the store's integrity rules."""
import time
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ueic import physics as ph  # noqa: E402
from ueic import twin  # noqa: E402
from ueic.api import create_app  # noqa: E402
from ueic.experiment import run_experiment  # noqa: E402
from ueic.params import make_config  # noqa: E402
from ueic.store import Store  # noqa: E402

SPEC = {
    "key": "T100", "title": "api test", "research_question": "q", "hypothesis": "h",
    "independent_variables": ["policy"], "dependent_variables": ["E_grid_kWh"], "controlled_variables": ["seed"],
    "baseline": "fixed", "configuration": "tiny", "data_collection": "simulator", "evaluation_criteria": "n/a",
    "known_limitations": "test only",
    "design": {"scenarios": ["S1_moderate"], "policies": ["fixed", "joint"], "seeds": [0],
               "scenario_overrides": {"duration_s": 600.0, "load_period_s": 600.0}, "timeseries_seeds": [0]},
}


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "api.sqlite"
    st = Store(db)
    run_experiment(SPEC, st, workers=1)
    st.close()
    return TestClient(create_app(db, workers=1))


def test_health_and_chain(client):
    h = client.get("/api/health").json()
    assert h["chain_ok"] and len(h["core_sha256"]) == 64


def test_coldplate_matches_twin(client):
    r = client.get("/api/physics/coldplate", params=dict(clock=1.0, t_sup=25, flow=1.0, t_amb=20)).json()
    cfg = make_config()
    pred = twin.evaluate(cfg, np.array([cfg.n_accel, 0.0]), 1.0, 1.0, 25.0, 1.0, 20.0)
    assert r["temperatures_C"]["junction"] == pytest.approx(float(pred["T_c"]), abs=1e-6)
    assert r["power_W"]["grid"] == pytest.approx(float(pred["P_grid"]), rel=1e-9)
    R = r["resistances_K_per_W"]
    assert R["total"] == pytest.approx(R["caloric"] + R["convection"] + R["conduction"])
    T = r["temperatures_C"]
    assert T["coolant_in"] < T["coolant_mean"] < T["wall"] < T["junction"]


def test_coldplate_reports_runaway_and_rejects_bad_input(client):
    params = dict(clock=1.0, t_sup=45, flow=0.5, t_amb=20, kappa_leak=0.04, p_leak_ref=900, r_cond=0.06)
    cfg = make_config({"kappa_leak": 0.04, "p_leak_ref": 900, "r_cond": 0.06})
    R = float(ph.r_total(0.5, cfg))
    exists = ph.leakage_steady_state_exists(45.0, R, float(ph.temp_independent_power(1.0, 1.0, cfg)), cfg.p_leak_ref, cfg)
    r = client.get("/api/physics/coldplate", params=params).json()
    assert r["runaway"] == (not bool(exists))
    assert client.get("/api/physics/coldplate", params=dict(r_cond=-1.0)).status_code == 422
    assert client.get("/api/physics/coldplate", params=dict(clock=2.0)).status_code == 422


def test_runs_timeseries_and_energyflow(client):
    exp = client.get("/api/experiments").json()[0]
    runs = client.get(f"/api/experiments/{exp['id']}/runs").json()
    assert len(runs) == 2
    rid = runs[0]["run_id"]
    ts = client.get(f"/api/runs/{rid}/timeseries").json()
    assert "Tj0" in ts and len(ts["t"]) == len(ts["P_grid"])
    f = client.get(f"/api/runs/{rid}/energyflow").json()
    grid_out = sum(l["kWh"] for l in f["links"] if l["source"] == "Grid")
    assert grid_out == pytest.approx(f["grid_kWh"], rel=1e-9)
    assert abs(f["balance_check_kWh"]) < 1e-9
    assert not any(l["source"] == "Reusable heat" for l in f["links"])   # never a source
    csv = client.get(f"/api/experiments/{exp['id']}/export.csv").text
    assert csv.count("\n") == 3


def test_post_experiment_validates_then_runs(client):
    bad = {**SPEC, "design": {**SPEC["design"], "param_overrides": {"eta_pump": 9}}}
    assert client.post("/api/experiments", json=bad).status_code == 400
    missing = {k: v for k, v in SPEC.items() if k != "hypothesis"}
    assert client.post("/api/experiments", json=missing).status_code == 400
    j = client.post("/api/experiments", json={**SPEC, "key": "T101"}).json()
    for _ in range(300):
        s = client.get(f"/api/jobs/{j['job_id']}").json()
        if s["status"] != "running":
            break
        time.sleep(0.1)
    assert s["status"] == "completed"
    keys = [x["key"] for x in client.get("/api/experiments").json()]
    assert "T101" in keys
    assert client.get("/api/verify").json()["ok"]


def test_lab_static_files_are_served(client):
    r = client.get("/lab/")
    assert r.status_code == 200 and "UEIC 3-D Lab" in r.text
    assert client.get("/lab/vendor/three/three.module.min.js").status_code == 200
    assert client.get("/lab/lab.js").status_code == 200
