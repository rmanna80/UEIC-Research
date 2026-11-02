"""Time-budgeted runs and checked resumption produce the same records as the standard runners."""
import json

import pytest

import ueic.experiment as ex
import ueic.resume as rs
from ueic.facility.experiment import run_facility_experiment
from ueic.store import Store

SPEC = {
    "key": "T101", "title": "resume test", "research_question": "q", "hypothesis": "h",
    "independent_variables": ["policy"], "dependent_variables": ["E_grid_kWh"], "controlled_variables": ["seed"],
    "baseline": "fixed", "configuration": "tiny", "data_collection": "simulator", "evaluation_criteria": "n/a",
    "known_limitations": "test only",
    "design": {"scenarios": ["S1_moderate"], "policies": ["fixed", "joint"], "seeds": [0, 1],
               "scenario_overrides": {"duration_s": 300.0, "load_period_s": 300.0}, "timeseries_seeds": [0]},
}

TOPO = {"name": "t", "description": "test", "accelerator_types": {"A": {}},
        "racks": [{"name": "r0", "nodes": [{"name": "n0", "gpus": ["A", "A", "A", "A"], "chain": 1,
                                            "hydraulic_scale": 1.0}], "power_limit_W": None, "uplink_jobs": 4}]}
FSPEC = {**SPEC, "key": "T102", "kind": "facility",
         "design": {"conditions": [{"label": "c0", "topology": TOPO, "jobs": {},
                                    "facility": {"duration_s": 600.0, "drain_s": 0.0}}],
                    "schedulers": ["least_loaded", "round_robin"], "seeds": [0, 1], "timeseries_seeds": [0]}}


def records(store, exp_id):
    out = []
    for rid, cj, seed, ch, mh, status, tsh in store.db.execute(
            "SELECT id, cell_json, seed, config_sha256, model_config_sha256, status, timeseries_sha256 FROM runs "
            "WHERE experiment_id=? ORDER BY rowid", (exp_id,)):
        ms = sorted((n, None if prov == rs.HOST_TIMING else v, u, prov) for n, v, u, prov in
                    store.db.execute("SELECT name, value, unit, provenance FROM metrics WHERE run_id=?", (rid,)))
        out.append((cj, seed, ch, mh, status, tsh, ms))
    return out


@pytest.fixture
def stores(tmp_path):
    a, b = Store(tmp_path / "a.sqlite"), Store(tmp_path / "b.sqlite")
    yield a, b
    a.close(); b.close()


def test_start_matches_standard_runner(stores):
    a, b = stores
    ea = ex.run_experiment(SPEC, a, workers=1)
    out = rs.start(SPEC, b, workers=2)
    assert out["status"] == "completed" and out["pending"] == 0
    assert records(a, ea) == records(b, out["exp_id"])
    assert b.experiment(out["exp_id"])["summary"] == a.experiment(ea)["summary"]
    assert b.verify_chain()[0]


def test_facility_start_matches_standard_runner(stores):
    a, b = stores
    ea = run_facility_experiment(FSPEC, a, workers=1)
    out = rs.start(FSPEC, b, workers=1)
    assert records(a, ea) == records(b, out["exp_id"])


def test_interrupted_then_resumed_equals_uninterrupted(stores):
    a, b = stores
    ea = ex.run_experiment(SPEC, a, workers=1)
    out = rs.start(SPEC, b, workers=1, max_minutes=0)          # budget already spent: nothing runs
    eid = out["exp_id"]
    assert out["status"] == "running" and out["pending"] == 4
    fn, pending, done = rs.check_resumable(b, eid)
    rs._record(b, pending[0][0], fn(pending[0][1]))           # one run finishes before the "kill"
    res = rs.resume(b, eid, workers=1, n_check=1)
    assert res["status"] == "completed" and res["reproduced"] == [pending[0][0]]
    assert records(a, ea) == records(b, eid)
    assert b.verify_chain()[0]
    assert b.experiment(eid)["summary"] == {"runs": 4, "failed": 0, "resumed_sessions": 1}
    assert any(e.startswith(f"Resumed {eid}: 3 pending of 4") for _, e in b.research_log())


def test_resume_refuses_finalised_experiment(stores):
    a, _ = stores
    eid = ex.run_experiment(SPEC, a, workers=1)
    with pytest.raises(rs.ResumeRefused, match="only unfinished"):
        rs.resume(a, eid)


def test_resume_refuses_changed_core(stores, monkeypatch):
    a, _ = stores
    eid = rs.start(SPEC, a, workers=1, max_minutes=0)["exp_id"]
    monkeypatch.setattr(rs, "core_hash", lambda: "0" * 64)
    with pytest.raises(rs.ResumeRefused, match="core hash changed"):
        rs.resume(a, eid)


def test_resume_refuses_when_completed_run_is_not_reproduced(stores, monkeypatch):
    a, _ = stores
    eid = rs.start(SPEC, a, workers=1, max_minutes=0)["exp_id"]
    fn, pending, _ = rs.check_resumable(a, eid)
    rs._record(a, pending[0][0], fn(pending[0][1]))
    real = ex.run_cell

    def drifted(cell):
        out = real(cell)
        k = next(iter(out["metrics"]))
        v, u, p = out["metrics"][k]
        out["metrics"][k] = (v + 1.0, u, p)
        return out
    monkeypatch.setattr(ex, "run_cell", drifted)
    with pytest.raises(rs.ResumeRefused, match="did not reproduce"):
        rs.resume(a, eid, workers=1)
    assert a.experiment(eid)["status"] == "running"
    assert not any(e.startswith(f"Resumed {eid}") for _, e in a.research_log())


def test_queue_resumes_then_skips(stores, tmp_path):
    a, _ = stores
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(SPEC))
    assert rs.queue([str(p)], a, workers=1, max_minutes=0, log=lambda s: None) is False
    assert rs.queue([str(p)], a, workers=1, log=lambda s: None) is True
    ids = [x["id"] for x in a.experiments()]
    assert len(ids) == 1 and a.experiment(ids[0])["status"] == "completed"
    assert rs.queue([str(p)], a, workers=1, log=lambda s: None) is True     # completed: skipped, nothing new
    assert len(a.experiments()) == 1


def test_queue_supersedes_an_aborted_attempt(stores, tmp_path):
    a, _ = stores
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(SPEC))
    first = rs.start(SPEC, a, workers=1, max_minutes=0)["exp_id"]
    a.abort_experiment(first, "test interruption")
    assert rs.queue([str(p)], a, workers=1, log=lambda s: None) is True
    second = [x for x in a.experiments() if x["id"] != first][0]
    assert second["supersedes"] == first and second["status"] == "completed"
    assert a.experiment(first)["status"] == "failed"
