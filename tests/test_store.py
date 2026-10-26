"""Experiment store integrity: registration, immutability, corrections, tamper detection."""
import sqlite3
import zipfile

import pytest

import ueic.experiment as ex
from ueic.store import Store

SPEC = {
    "key": "T001", "title": "store test", "research_question": "q", "hypothesis": "h",
    "independent_variables": ["policy"], "dependent_variables": ["E_grid_kWh"], "controlled_variables": ["seed"],
    "baseline": "fixed", "configuration": "tiny", "data_collection": "simulator", "evaluation_criteria": "n/a",
    "known_limitations": "test only",
    "design": {"scenarios": ["S1_moderate"], "policies": ["fixed", "joint"], "seeds": [0, 1],
               "scenario_overrides": {"duration_s": 300.0, "load_period_s": 300.0}},
}


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.sqlite")
    yield s
    s.close()


def test_spec_requires_charter_fields(store):
    bad = dict(SPEC)
    del bad["hypothesis"]
    with pytest.raises(ValueError):
        store.register_experiment(bad)


def test_end_to_end_run_and_immutability(store, tmp_path):
    exp_id = ex.run_experiment(SPEC, store, workers=1)
    exp = store.experiment(exp_id)
    assert exp["status"] == "completed"
    runs = store.runs(exp_id)
    assert len(runs) == 4 and all(r["status"] == "completed" for r in runs)
    rid = runs[0]["run_id"]
    with pytest.raises(sqlite3.DatabaseError):
        store.db.execute("UPDATE metrics SET value = 0 WHERE run_id = ?", (rid,))
    with pytest.raises(sqlite3.DatabaseError):
        store.db.execute("DELETE FROM runs WHERE id = ?", (rid,))
    with pytest.raises(sqlite3.DatabaseError):
        store.db.execute("UPDATE runs SET seed = 99 WHERE id = ?", (rid,))
    with pytest.raises(sqlite3.DatabaseError):
        store.db.execute("UPDATE experiments SET spec_json = '{}' WHERE id = ?", (exp_id,))
    with pytest.raises(sqlite3.DatabaseError):
        store.db.execute("INSERT INTO metrics VALUES (?, 'late', 1.0, '-', 'simulator_output')", (rid,))
    ok, msg = store.verify_chain()
    assert ok, msg


def test_corrections_are_new_records_and_originals_survive(store):
    exp_id = ex.run_experiment(SPEC, store, workers=1)
    rid = store.runs(exp_id)[0]["run_id"]
    before = store.runs(exp_id)[0]["metrics"]["E_grid_kWh"]
    store.add_correction("metrics", rid, "E_grid_kWh", before * 1.01, "example correction")
    assert store.runs(exp_id)[0]["metrics"]["E_grid_kWh"] == before
    assert store.db.execute("SELECT COUNT(*) FROM corrections").fetchone()[0] == 1
    with pytest.raises(ValueError):
        store.add_correction("metrics", rid, "x", 1, "")


def test_tampering_is_detected_even_without_triggers(store):
    exp_id = ex.run_experiment(SPEC, store, workers=1)
    rid = store.runs(exp_id)[1]["run_id"]
    store.db.execute("DROP TRIGGER metrics_no_update")
    store.db.execute("UPDATE metrics SET value = value * 0.9 WHERE run_id = ? AND name = 'E_grid_kWh'", (rid,))
    ok, msg = store.verify_chain()
    assert not ok and rid in msg


def test_failed_runs_are_preserved(store, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("injected failure")
    monkeypatch.setattr(ex, "simulate", boom)
    exp_id = ex.run_experiment(SPEC, store, workers=1)
    runs = store.runs(exp_id)
    assert all(r["status"] == "failed" and "injected failure" in r["error"] for r in runs)
    assert store.experiment(exp_id)["status"] == "failed"
    assert store.verify_chain()[0]


def test_exports_and_bundle(store, tmp_path):
    exp_id = ex.run_experiment(SPEC, store, workers=1)
    csv_p = store.export_csv(exp_id, tmp_path / "r.csv")
    json_p = store.export_json(exp_id, tmp_path / "r.json")
    assert csv_p.read_text().count("\n") == 5
    assert '"provenance"' not in csv_p.read_text()  # wide CSV, provenance lives in JSON
    assert "simulator_output" in json_p.read_text()
    b = store.bundle(exp_id, tmp_path / "b.zip")
    names = zipfile.ZipFile(b).namelist()
    for need in ("spec.json", "results.csv", "results.json", "parameter_registry.json", "REPRODUCE.md",
                 "code/ueic/sim.py"):
        assert need in names


def test_invalid_spec_is_rejected_before_registration(store):
    bad = {**SPEC, "design": {**SPEC["design"], "param_overrides": {"eta_pump": 5.0}}}
    with pytest.raises(ValueError):
        ex.run_experiment(bad, store, workers=1)
    assert store.db.execute("SELECT COUNT(*) FROM experiments").fetchone()[0] == 0
