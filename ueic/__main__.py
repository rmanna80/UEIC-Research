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
  python -m ueic serve                     # Phase 2: API + 3-D lab at http://127.0.0.1:8765/lab/
  python -m ueic telemetry devices         # Phase 4: list NVIDIA GPUs (read-only)
  python -m ueic calib plan --clocks 900,1200,1500   # print a calibration procedure to review and run
  python -m ueic calib run --kind compute --seconds 60 --label clk=1200
  python -m ueic calib fit data/calibration/* --out data/calibration/calibration.json
  python -m ueic calib ingest data/calibration/calibration.json
  python -m ueic run experiments/E001_policy_benchmark.json --calibration data/calibration/calibration.json
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
    r.add_argument("--calibration", default=None, help="calibration JSON from `ueic calib fit`; creates a <KEY>C spec")
    tm = sub.add_parser("telemetry", help="read-only NVML telemetry")
    tsub = tm.add_subparsers(dest="tcmd", required=True)
    tsub.add_parser("devices")
    tl = tsub.add_parser("log"); tl.add_argument("--out", required=True); tl.add_argument("--seconds", type=float, required=True)
    tl.add_argument("--interval", type=float, default=0.1); tl.add_argument("--gpu", type=int, default=None); tl.add_argument("--label", default="")
    cb = sub.add_parser("calib", help="Phase 4 calibration on a real GPU")
    csub = cb.add_subparsers(dest="ccmd", required=True)
    cp = csub.add_parser("plan"); cp.add_argument("--clocks", required=True, help="comma-separated MHz, e.g. 900,1200,1500")
    cp.add_argument("--gpu", type=int, default=0); cp.add_argument("--seconds", type=int, default=60)
    cr = csub.add_parser("run"); cr.add_argument("--kind", choices=["compute", "memory", "warmup"], required=True)
    cr.add_argument("--seconds", type=float, default=60); cr.add_argument("--gpu", type=int, default=0)
    cr.add_argument("--label", default=""); cr.add_argument("--idle-before", type=float, default=0.0)
    cr.add_argument("--out", default=str(ROOT / "data" / "calibration"))
    cf = csub.add_parser("fit"); cf.add_argument("sessions", nargs="+"); cf.add_argument("--out", required=True)
    ci = csub.add_parser("ingest"); ci.add_argument("calibration"); ci.add_argument("--key", default="M001")
    sv = sub.add_parser("serve", help="Phase 2: local API + 3-D lab at http://127.0.0.1:8765/lab/")
    sv.add_argument("--host", default="127.0.0.1"); sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--workers", type=int, default=None)
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

    if a.cmd == "serve":
        from .api import serve
        if a.host not in ("127.0.0.1", "localhost", "::1"):
            print("warning: serving beyond localhost exposes the experiment API to your network")
        serve(a.host, a.port, a.db, a.workers)
        return 0
    if a.cmd == "telemetry":
        from .telemetry import Logger, Nvml
        if a.tcmd == "devices":
            nv = Nvml()
            print(f"driver {nv.driver}")
            for d in nv.devices():
                print(f"  [{d.index}] {d.name}  max SM {d.max_sm_clock_MHz} MHz  power limit {d.power_limit_W} W")
            nv.close()
        else:
            meta = Logger(a.out, interval_s=a.interval, gpus=None if a.gpu is None else [a.gpu], label=a.label).run(a.seconds)
            print(f"{meta['n_samples']} samples -> {a.out} (sha256 {meta['csv_sha256'][:12]})")
        return 0
    if a.cmd == "calib" and a.ccmd in ("plan", "run", "fit"):
        from . import calibrate as cal
        if a.ccmd == "plan":
            print(cal.plan_commands([int(x) for x in a.clocks.split(",")], a.gpu, a.seconds))
        elif a.ccmd == "run":
            print(cal.run_session(a.kind, a.seconds, a.out, a.label, a.gpu, idle_before_s=a.idle_before))
        else:
            import glob, hashlib, json as _json
            dirs = sorted({d for pat in a.sessions for d in glob.glob(pat) if Path(d, "session.json").exists()})
            out = cal.calibrate(dirs)
            Path(a.out).write_text(_json.dumps(out, indent=1))
            print(f"{len(dirs)} sessions -> {a.out}")
            for k, v in out["overrides"].items():
                print(f"  {k} = {v['value']}  (se {v['se']}, class {v['evidence']})")
            for n in out["notes"]:
                print("  note:", n)
        return 0

    store = Store(a.db)
    try:
        if a.cmd == "run":
            from .experiment import load_spec, run_experiment
            spec = load_spec(a.spec)
            if a.calibration:
                import hashlib, json as _json
                from .calibrate import apply_calibration
                raw = Path(a.calibration).read_bytes()
                spec = apply_calibration(spec, _json.loads(raw), hashlib.sha256(raw).hexdigest())

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
        elif a.cmd == "calib" and a.ccmd == "ingest":
            import hashlib, json as _json
            from .calibrate import ingest
            raw = Path(a.calibration).read_bytes()
            print(ingest(store, _json.loads(raw), hashlib.sha256(raw).hexdigest(), a.key))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
