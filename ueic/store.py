"""Persistent, append-only experiment store (SQLite).

Integrity properties:
  * Experiments must be registered (with hypothesis and evaluation criteria)
    before any run is recorded; the registered spec is frozen by triggers.
  * Finalised runs and their metrics cannot be updated or deleted (triggers).
  * Later corrections are new rows in `corrections`, never edits.
  * Every finalised run is linked into a SHA-256 hash chain over its content;
    `verify_chain()` detects tampering even if someone drops the triggers.
  * Every metric carries a provenance label.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import platform
import sqlite3
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from . import __version__

PROVENANCE = ("physical_measurement", "simulator_output", "analytical_calculation",
              "external_research", "user_input", "engineering_assumption")

REQUIRED_SPEC_FIELDS = (
    "key", "title", "research_question", "hypothesis", "independent_variables", "dependent_variables",
    "controlled_variables", "baseline", "configuration", "data_collection", "evaluation_criteria",
    "known_limitations", "design",
)

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS experiments(
  id TEXT PRIMARY KEY,
  key TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  supersedes TEXT REFERENCES experiments(id),
  created_utc TEXT NOT NULL,
  spec_json TEXT NOT NULL,
  spec_sha256 TEXT NOT NULL,
  code_sha256 TEXT NOT NULL,
  software_version TEXT NOT NULL,
  host_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('registered','running','completed','failed')),
  finished_utc TEXT,
  summary_json TEXT
);
CREATE TABLE IF NOT EXISTS runs(
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL REFERENCES experiments(id),
  cell_json TEXT NOT NULL,
  seed INTEGER NOT NULL,
  config_json TEXT NOT NULL,
  config_sha256 TEXT NOT NULL,
  model_config_sha256 TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('running','completed','failed')),
  error TEXT,
  warnings_json TEXT,
  started_utc TEXT NOT NULL,
  finished_utc TEXT,
  timeseries_path TEXT,
  timeseries_sha256 TEXT,
  seq INTEGER UNIQUE,
  chain_hash TEXT
);
CREATE TABLE IF NOT EXISTS metrics(
  run_id TEXT NOT NULL REFERENCES runs(id),
  name TEXT NOT NULL,
  value REAL,
  unit TEXT NOT NULL,
  provenance TEXT NOT NULL CHECK(provenance IN {PROVENANCE!r}),
  PRIMARY KEY(run_id, name)
);
CREATE TABLE IF NOT EXISTS corrections(
  id TEXT PRIMARY KEY,
  created_utc TEXT NOT NULL,
  target_table TEXT NOT NULL,
  target_id TEXT NOT NULL,
  field TEXT NOT NULL,
  new_value TEXT,
  reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  utc TEXT NOT NULL,
  entry TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS exp_spec_frozen BEFORE UPDATE OF key, spec_json, spec_sha256, created_utc, code_sha256 ON experiments
BEGIN SELECT RAISE(ABORT, 'immutable: registered experiment specs cannot change; register a new version'); END;
CREATE TRIGGER IF NOT EXISTS exp_final BEFORE UPDATE ON experiments WHEN OLD.status IN ('completed','failed')
BEGIN SELECT RAISE(ABORT, 'immutable: experiment finalised; record a correction instead'); END;
CREATE TRIGGER IF NOT EXISTS exp_no_delete BEFORE DELETE ON experiments
BEGIN SELECT RAISE(ABORT, 'immutable: experiments cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS runs_final BEFORE UPDATE ON runs WHEN OLD.status IN ('completed','failed')
BEGIN SELECT RAISE(ABORT, 'immutable: run finalised; record a correction instead'); END;
CREATE TRIGGER IF NOT EXISTS runs_no_delete BEFORE DELETE ON runs
BEGIN SELECT RAISE(ABORT, 'immutable: runs cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS metrics_no_update BEFORE UPDATE ON metrics
BEGIN SELECT RAISE(ABORT, 'immutable: metrics cannot be updated'); END;
CREATE TRIGGER IF NOT EXISTS metrics_no_delete BEFORE DELETE ON metrics
BEGIN SELECT RAISE(ABORT, 'immutable: metrics cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS metrics_frozen_run BEFORE INSERT ON metrics
WHEN (SELECT status FROM runs WHERE id = NEW.run_id) IN ('completed','failed')
BEGIN SELECT RAISE(ABORT, 'immutable: run finalised'); END;
CREATE TRIGGER IF NOT EXISTS corrections_no_update BEFORE UPDATE ON corrections
BEGIN SELECT RAISE(ABORT, 'immutable: corrections are append-only'); END;
CREATE TRIGGER IF NOT EXISTS corrections_no_delete BEFORE DELETE ON corrections
BEGIN SELECT RAISE(ABORT, 'immutable: corrections are append-only'); END;
CREATE TRIGGER IF NOT EXISTS log_no_update BEFORE UPDATE ON research_log
BEGIN SELECT RAISE(ABORT, 'immutable: research log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS log_no_delete BEFORE DELETE ON research_log
BEGIN SELECT RAISE(ABORT, 'immutable: research log is append-only'); END;
"""

GENESIS = "0" * 64


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(obj: Any) -> str:
    def default(o):
        if isinstance(o, (np.floating, np.integer)):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(type(o))
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=default)


def sha256(s: str | bytes) -> str:
    return hashlib.sha256(s.encode() if isinstance(s, str) else s).hexdigest()


def code_hash(pkg_dir: Path | None = None) -> str:
    pkg_dir = pkg_dir or Path(__file__).resolve().parent
    h = hashlib.sha256()
    for p in sorted(pkg_dir.glob("*.py")):
        h.update(p.name.encode())
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


CORE_MODULES = ("params.py", "physics.py", "workload.py", "twin.py", "policies.py", "sim.py", "experiment.py")


def core_hash(pkg_dir: Path | None = None) -> str:
    """Hash of only the modules that can change simulator outputs (not reporting/dashboard code)."""
    pkg_dir = pkg_dir or Path(__file__).resolve().parent
    h = hashlib.sha256()
    for name in CORE_MODULES:
        h.update(name.encode())
        h.update((pkg_dir / name).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def host_info() -> dict[str, Any]:
    import os
    return {"platform": platform.platform(), "python": sys.version.split()[0], "numpy": np.__version__,
            "machine": platform.machine(), "cpu_count": os.cpu_count(), "core_sha256": core_hash()}


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ts_dir = self.path.parent / "timeseries"
        self.ts_dir.mkdir(exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self):
        self.db.close()

    # ------------------------------------------------------------ research log
    def log(self, entry: str) -> None:
        with self.db:
            self.db.execute("INSERT INTO research_log(utc, entry) VALUES (?, ?)", (utcnow(), entry))

    def research_log(self) -> list[tuple[str, str]]:
        return list(self.db.execute("SELECT utc, entry FROM research_log ORDER BY id"))

    # ------------------------------------------------------------- experiments
    def register_experiment(self, spec: dict[str, Any], supersedes: str | None = None) -> str:
        missing = [k for k in REQUIRED_SPEC_FIELDS if not spec.get(k)]
        if missing:
            raise ValueError(f"Experiment spec missing required fields: {missing}")
        version = 1
        if supersedes:
            row = self.db.execute("SELECT version FROM experiments WHERE id=?", (supersedes,)).fetchone()
            if row is None:
                raise KeyError(supersedes)
            version = row[0] + 1
        exp_id = f"{spec['key']}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
        sj = canonical(spec)
        with self.db:
            self.db.execute(
                "INSERT INTO experiments(id,key,version,supersedes,created_utc,spec_json,spec_sha256,code_sha256,"
                "software_version,host_json,status) VALUES (?,?,?,?,?,?,?,?,?,?, 'registered')",
                (exp_id, spec["key"], version, supersedes, utcnow(), sj, sha256(sj), code_hash(),
                 __version__, canonical(host_info())))
        self.log(f"Registered {exp_id}: {spec['title']} | H: {spec['hypothesis']}")
        return exp_id

    def set_experiment_status(self, exp_id: str, status: str, summary: dict | None = None) -> None:
        with self.db:
            if status in ("completed", "failed"):
                self.db.execute("UPDATE experiments SET status=?, finished_utc=?, summary_json=? WHERE id=?",
                                (status, utcnow(), canonical(summary or {}), exp_id))
            else:
                self.db.execute("UPDATE experiments SET status=? WHERE id=?", (status, exp_id))

    def abort_experiment(self, exp_id: str, reason: str) -> int:
        """Finalise an interrupted experiment: unfinished runs become 'failed' (preserved, never deleted)."""
        ids = [r[0] for r in self.db.execute("SELECT id FROM runs WHERE experiment_id=? AND status='running'", (exp_id,))]
        for rid in ids:
            self.fail_run(rid, f"aborted: {reason}")
        self.set_experiment_status(exp_id, "failed", {"aborted": reason, "unfinished_runs": len(ids)})
        self.log(f"Aborted {exp_id}: {reason} ({len(ids)} unfinished runs marked failed)")
        return len(ids)

    def experiment(self, exp_id: str) -> dict[str, Any]:
        r = self.db.execute("SELECT id,key,version,supersedes,created_utc,spec_json,spec_sha256,code_sha256,"
                            "software_version,host_json,status,finished_utc,summary_json FROM experiments WHERE id=?",
                            (exp_id,)).fetchone()
        if r is None:
            raise KeyError(exp_id)
        keys = ["id", "key", "version", "supersedes", "created_utc", "spec", "spec_sha256", "code_sha256",
                "software_version", "host", "status", "finished_utc", "summary"]
        d = dict(zip(keys, r))
        for k in ("spec", "host", "summary"):
            d[k] = json.loads(d[k]) if d[k] else None
        return d

    def latest_experiment(self, key: str, status: str = "completed") -> str | None:
        r = self.db.execute("SELECT id FROM experiments WHERE key=? AND status=? ORDER BY created_utc DESC, rowid DESC LIMIT 1",
                            (key, status)).fetchone()
        return r[0] if r else None

    def experiments(self) -> list[dict[str, Any]]:
        ids = [r[0] for r in self.db.execute("SELECT id FROM experiments ORDER BY created_utc, rowid")]
        return [self.experiment(i) for i in ids]

    # -------------------------------------------------------------------- runs
    def start_run(self, exp_id: str, cell: dict, seed: int, config: dict, model_config: dict) -> str:
        run_id = uuid.uuid4().hex
        cj = canonical(config)
        with self.db:
            self.db.execute(
                "INSERT INTO runs(id,experiment_id,cell_json,seed,config_json,config_sha256,model_config_sha256,status,started_utc)"
                " VALUES (?,?,?,?,?,?,?,'running',?)",
                (run_id, exp_id, canonical(cell), int(seed), cj, sha256(cj), sha256(canonical(model_config)), utcnow()))
        return run_id

    def _write_timeseries(self, run_id: str, ts: dict[str, list[float]]) -> tuple[str | None, str | None]:
        if not ts or not ts.get("t"):
            return None, None
        buf = io.StringIO()
        w = csv.writer(buf)
        keys = list(ts.keys())
        w.writerow(keys)
        for row in zip(*(ts[k] for k in keys)):
            w.writerow([f"{v:.6g}" for v in row])
        raw = buf.getvalue().encode()
        p = self.ts_dir / f"{run_id}.csv.gz"
        with gzip.GzipFile(p, "wb", mtime=0) as f:
            f.write(raw)
        return str(p.relative_to(self.path.parent)), sha256(raw)

    def _last_chain(self) -> tuple[int, str]:
        r = self.db.execute("SELECT seq, chain_hash FROM runs WHERE seq IS NOT NULL ORDER BY seq DESC LIMIT 1").fetchone()
        return (r[0], r[1]) if r else (0, GENESIS)

    def _content(self, run_id: str) -> str:
        """Canonical content of a run (everything except seal fields) plus its metrics."""
        r = self.db.execute("SELECT id,experiment_id,cell_json,seed,config_sha256,model_config_sha256,error,"
                            "warnings_json,timeseries_sha256 FROM runs WHERE id=?", (run_id,)).fetchone()
        ms = list(self.db.execute("SELECT name, value, unit, provenance FROM metrics WHERE run_id=? ORDER BY name", (run_id,)))
        return canonical({"run": list(r), "metrics": [list(m) for m in ms]})

    def finish_run(self, run_id: str, metrics: dict[str, tuple[float, str, str]], warnings: list[str],
                   timeseries: dict[str, list[float]] | None = None) -> None:
        ts_path, ts_hash = self._write_timeseries(run_id, timeseries or {})
        with self.db:
            for name, (val, unit, prov) in metrics.items():
                v = None if val is None or (isinstance(val, float) and np.isnan(val)) else float(val)
                self.db.execute("INSERT INTO metrics(run_id,name,value,unit,provenance) VALUES (?,?,?,?,?)",
                                (run_id, name, v, unit, prov))
            self.db.execute("UPDATE runs SET warnings_json=?, timeseries_path=?, timeseries_sha256=? WHERE id=?",
                            (canonical(warnings), ts_path, ts_hash, run_id))
            self._seal(run_id, "completed")

    def fail_run(self, run_id: str, error: str) -> None:
        with self.db:
            self.db.execute("UPDATE runs SET error=? WHERE id=?", (error[-4000:], run_id))
            self._seal(run_id, "failed")

    def _seal(self, run_id: str, status: str) -> None:
        seq, prev = self._last_chain()
        chain = sha256(prev + sha256(self._content(run_id) + status))
        self.db.execute("UPDATE runs SET status=?, finished_utc=?, seq=?, chain_hash=? WHERE id=?",
                        (status, utcnow(), seq + 1, chain, run_id))

    def verify_chain(self) -> tuple[bool, str]:
        prev = GENESIS
        rows = list(self.db.execute("SELECT id, seq, status, chain_hash, timeseries_path, timeseries_sha256 "
                                    "FROM runs WHERE seq IS NOT NULL ORDER BY seq"))
        for i, (rid, seq, status, chain, tsp, tsh) in enumerate(rows, start=1):
            if seq != i:
                return False, f"sequence gap at {rid} (seq {seq}, expected {i})"
            if sha256(prev + sha256(self._content(rid) + status)) != chain:
                return False, f"hash mismatch at run {rid} (seq {seq})"
            prev = chain
            if tsp:
                p = self.path.parent / tsp
                if not p.exists():
                    return False, f"missing timeseries file for run {rid}"
                with gzip.open(p, "rb") as f:
                    if sha256(f.read()) != tsh:
                        return False, f"timeseries content changed for run {rid}"
        return True, f"{len(rows)} finalised runs verified"

    def add_correction(self, target_table: str, target_id: str, field: str, new_value: Any, reason: str) -> str:
        if not reason:
            raise ValueError("A correction needs a reason")
        cid = uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO corrections VALUES (?,?,?,?,?,?,?)",
                            (cid, utcnow(), target_table, target_id, field, canonical(new_value), reason))
        self.log(f"Correction {cid} on {target_table}:{target_id}.{field}: {reason}")
        return cid

    # ---------------------------------------------------------------- queries
    def runs(self, exp_id: str, include_failed: bool = True) -> list[dict[str, Any]]:
        q = ("SELECT id, cell_json, seed, status, error, warnings_json, timeseries_path, config_sha256 FROM runs "
             "WHERE experiment_id=? " + ("" if include_failed else "AND status='completed' ") + "ORDER BY seq")
        out = []
        for rid, cell, seed, status, err, warn, tsp, csha in self.db.execute(q, (exp_id,)):
            m = {n: v for n, v in self.db.execute("SELECT name, value FROM metrics WHERE run_id=?", (rid,))}
            out.append({"run_id": rid, **json.loads(cell), "seed": seed, "status": status, "error": err,
                        "warnings": json.loads(warn) if warn else [], "timeseries_path": tsp,
                        "config_sha256": csha, "metrics": m})
        return out

    def metric_meta(self, exp_id: str) -> dict[str, tuple[str, str]]:
        return {n: (u, p) for n, u, p in self.db.execute(
            "SELECT DISTINCT m.name, m.unit, m.provenance FROM metrics m JOIN runs r ON r.id=m.run_id WHERE r.experiment_id=?",
            (exp_id,))}

    def load_timeseries(self, run_id: str) -> dict[str, list[float]]:
        r = self.db.execute("SELECT timeseries_path FROM runs WHERE id=?", (run_id,)).fetchone()
        if not r or not r[0]:
            return {}
        with gzip.open(self.path.parent / r[0], "rt") as f:
            rows = list(csv.reader(f))
        keys = rows[0]
        cols = list(zip(*rows[1:])) if len(rows) > 1 else [[] for _ in keys]
        return {k: [float(v) for v in col] for k, col in zip(keys, cols)}

    # ---------------------------------------------------------------- exports
    def export_csv(self, exp_id: str, path: str | Path) -> Path:
        runs = self.runs(exp_id)
        names = sorted({n for r in runs for n in r["metrics"]})
        cell_keys = sorted({k for r in runs for k in r if k not in ("metrics", "warnings")})
        path = Path(path)
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(cell_keys + names)
            for r in runs:
                w.writerow([r.get(k) if not isinstance(r.get(k), dict) else canonical(r.get(k)) for k in cell_keys]
                           + [r["metrics"].get(n) for n in names])
        return path

    def export_json(self, exp_id: str, path: str | Path) -> Path:
        meta = self.metric_meta(exp_id)
        doc = {"experiment": self.experiment(exp_id), "metric_units_provenance": meta, "runs": self.runs(exp_id),
               "corrections": [dict(zip(["id", "utc", "table", "target", "field", "new_value", "reason"], r))
                               for r in self.db.execute("SELECT * FROM corrections")]}
        path = Path(path)
        path.write_text(json.dumps(doc, indent=1, default=str))
        return path

    def bundle(self, exp_id: str, path: str | Path, include_timeseries: bool = True) -> Path:
        """Reproducible bundle: frozen spec, code snapshot, parameter registry, results."""
        from .params import assumptions_table
        exp = self.experiment(exp_id)
        path = Path(path)
        tmp_csv = path.with_suffix(".tmp.csv")
        tmp_json = path.with_suffix(".tmp.json")
        self.export_csv(exp_id, tmp_csv)
        self.export_json(exp_id, tmp_json)
        pkg = Path(__file__).resolve().parent
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("spec.json", json.dumps(exp["spec"], indent=1))
            z.write(tmp_csv, "results.csv")
            z.write(tmp_json, "results.json")
            z.writestr("parameter_registry.json", json.dumps(assumptions_table(), indent=1))
            for p in sorted(pkg.glob("*.py")):
                z.write(p, f"code/ueic/{p.name}")
            if include_timeseries:
                for r in self.runs(exp_id):
                    if r["timeseries_path"]:
                        z.write(self.path.parent / r["timeseries_path"], r["timeseries_path"])
            z.writestr("REPRODUCE.md", (
                f"# Reproduce {exp_id}\n\n"
                f"Code SHA-256 at registration (all package files): `{exp['code_sha256']}`\n"
                f"Simulation-core SHA-256 at registration: `{(exp['host'] or {}).get('core_sha256', 'not recorded (pre-0.1.1)')}`\n"
                f"Simulation-core SHA-256 of the bundled code: `{core_hash()}`\n"
                f"Software version: {exp['software_version']}\n"
                f"Host: {json.dumps(exp['host'])}\n\n"
                "1. Install the code snapshot in `code/` (or a checkout whose `python -m ueic hash` matches).\n"
                "2. Run: `python -m ueic run spec.json --db fresh.sqlite`\n"
                "3. Compare `results.csv` with the new export. Simulator outputs are deterministic for a given\n"
                "   seed, code hash, and NumPy version; wall-clock metrics (provenance physical_measurement) will differ.\n"))
        tmp_csv.unlink()
        tmp_json.unlink()
        return path
