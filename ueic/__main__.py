"""Command-line interface.

  python -m ueic run experiments/E001_policy_benchmark.json [--workers 2] [--db results/ueic.sqlite]
  python -m ueic abort EXP_ID "reason"     # finalise an interrupted experiment (runs kept as failed)
  python -m ueic list                      # experiments in the store
  python -m ueic verify                    # check the tamper-evident hash chain
  python -m ueic export E001 [--out results/exports]
  python -m ueic report                    # regenerate docs/RESULTS.md + figures from the store
  python -m ueic dashboard                 # regenerate results/dashboard.html from the store
  python -m ueic params                    # print the assumptions register
  python -m ueic log "message"             # append to the research log
  python -m ueic hash                      # code SHA-256 (compare with a bundle's REPRODUCE.md)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "results" / "ueic.sqlite"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ueic")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("spec"); r.add_argument("--workers", type=int, default=None)
    r.add_argument("--supersedes", default=None, help="experiment id this run replaces (old record is kept)")
    ab = sub.add_parser("abort"); ab.add_argument("exp_id"); ab.add_argument("reason")
    sub.add_parser("list")
    sub.add_parser("verify")
    e = sub.add_parser("export"); e.add_argument("key"); e.add_argument("--out", default=str(ROOT / "results" / "exports"))
    sub.add_parser("report")
    sub.add_parser("dashboard")
    sub.add_parser("params")
    lg = sub.add_parser("log"); lg.add_argument("message")
    sub.add_parser("hash")
    a = ap.parse_args(argv)

    from .store import Store, code_hash, core_hash
    if a.cmd == "hash":
        print(f"all package files: {code_hash()}")
        print(f"simulation core:   {core_hash()}")
        return 0
    if a.cmd == "params":
        from .params import assumptions_table
        for p in assumptions_table():
            rng = f"[{p['low']}, {p['high']}]" if p["low"] is not None else ""
            print(f"{p['evidence']}  {p['name']:<22} {p['value']:<12g} {p['unit']:<22} {rng:<18} {p['source']}")
        return 0

    store = Store(a.db)
    try:
        if a.cmd == "run":
            from .experiment import load_spec, run_experiment
            spec = load_spec(a.spec)

            def prog(done, total):
                if done == total or done % max(1, total // 20) == 0:
                    print(f"  {done}/{total} runs", flush=True)
            exp_id = run_experiment(spec, store, workers=a.workers, progress=prog, supersedes=a.supersedes)
            exp = store.experiment(exp_id)
            print(f"{exp_id}: {exp['status']} {exp['summary']}")
        elif a.cmd == "abort":
            print(f"{store.abort_experiment(a.exp_id, a.reason)} unfinished runs marked failed")
        elif a.cmd == "list":
            for x in store.experiments():
                print(f"{x['id']:<40} {x['status']:<10} {x['summary']}  {x['spec']['title']}")
        elif a.cmd == "verify":
            ok, msg = store.verify_chain()
            print(("OK: " if ok else "FAILED: ") + msg)
            return 0 if ok else 1
        elif a.cmd == "export":
            exp_id = store.latest_experiment(a.key) or a.key
            out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
            print(store.export_csv(exp_id, out / f"{exp_id}.csv"))
            print(store.export_json(exp_id, out / f"{exp_id}.json"))
            print(store.bundle(exp_id, out / f"{exp_id}_bundle.zip"))
        elif a.cmd == "report":
            from .report import build_report
            print(build_report(store, ROOT))
        elif a.cmd == "dashboard":
            from .dashboard import build_dashboard
            print(build_dashboard(store, ROOT))
        elif a.cmd == "log":
            store.log(a.message)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
