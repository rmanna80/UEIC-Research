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
  python -m ueic calib check               # read-only preflight: Python/venv, PyTorch+CUDA, NVML
  python -m ueic calib probe               # sustained clock at default settings -> suggested sweep clocks
  python -m ueic calib show [SESSION]      # summarise a session (default: latest), incl. which limit applied
  python -m ueic calib plan --clocks <from probe>   # print a procedure to review and run
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


def _print_summary(r: dict) -> None:
    print(f"GPU: {r['device']}, NVML max SM clock {r['nvml_max_clock_MHz']:.0f} MHz")
    lim = r.get("power_limit_W")
    print(f"sustained SM clock {r['clock_MHz']:.0f} MHz (variation {100 * r['clock_cv']:.1f}%), "
          f"power {r['power_W']:.1f} W median / {r['power_p95_W']:.1f} W 95th percentile"
          + (f" (reported limit {lim:.0f} W)" if lim else "") + f", {r['temp_C']:.0f} C")
    if r.get("limited_frac") is None:
        print("limit reasons: not reported by this GPU")
    elif not r["interpretation"]:
        print("no power or thermal limit was active")
    for line in r["interpretation"]:
        print("  - " + line)


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
    ck = csub.add_parser("check", help="read-only preflight: Python, venv, PyTorch/CUDA, NVML")
    ck.add_argument("--gpu", type=int, default=0)
    pb = csub.add_parser("probe", help="measure the clock the GPU sustains at default settings; suggests sweep clocks")
    pb.add_argument("--seconds", type=float, default=60); pb.add_argument("--gpu", type=int, default=0)
    pb.add_argument("--out", default=str(ROOT / "data" / "calibration"))
    sh = csub.add_parser("show", help="summarise a recorded session, including which limit held the clock down")
    sh.add_argument("session", nargs="?", default=None, help="session folder (default: the most recent one)")
    sh.add_argument("--root", default=str(ROOT / "data" / "calibration"))
    cp = csub.add_parser("plan"); cp.add_argument("--clocks", required=True, help="comma-separated MHz, e.g. 900,1200,1500")
    cp.add_argument("--gpu", type=int, default=0); cp.add_argument("--seconds", type=int, default=60)
    cr = csub.add_parser("run"); cr.add_argument("--kind", choices=["compute", "memory", "warmup"], required=True)
    cr.add_argument("--seconds", type=float, default=60); cr.add_argument("--gpu", type=int, default=0)
    cr.add_argument("--label", default=""); cr.add_argument("--idle-before", type=float, default=0.0)
    cr.add_argument("--out", default=str(ROOT / "data" / "calibration"))
    cf = csub.add_parser("fit"); cf.add_argument("sessions", nargs="+"); cf.add_argument("--out", required=True)
    cf.add_argument("--device", default=None, help="part of the GPU name or UUID, when sessions from several GPUs are present")
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
    if a.cmd == "calib" and a.ccmd in ("check", "probe", "show", "plan", "run", "fit"):
        from . import calibrate as cal
        if a.ccmd == "check":
            res = cal.check(a.gpu)
            for status, msg in res:
                print(f"[{status.upper():>4}] {msg}")
            bad = any(s == "fail" for s, _ in res)
            print("Not ready: fix the FAIL lines above, then run this check again." if bad else
                  "Ready to calibrate.")
            return 1 if bad else 0
        if a.ccmd == "plan":
            print(cal.plan_commands([int(x) for x in a.clocks.split(",")], a.gpu, a.seconds))
            return 0
        if a.ccmd == "show":
            d = Path(a.session) if a.session else cal.latest_session(a.root)
            if d is None or not (d / "session.json").exists():
                print(f"no session found ({a.session or a.root})")
                return 1
            r = cal.show_session(d)
            print(f"{d.name}  [{r['kind']}]")
            if not r["ok"]:
                print(f"  {r['reason']}")
                return 1
            _print_summary(r)
            devs = cal.devices_in(d.parent)
            if len(devs) > 1:
                print(f"note: {d.parent} holds sessions from {len(devs)} GPUs; `calib fit` needs --device:")
                for lab, n in devs.items():
                    print(f"  {lab}: {n} sessions")
            return 0
        try:
            if a.ccmd == "probe":
                print(f"Running the compute kernel for {a.seconds:g} s at the GPU's current clock settings ...")
                r = cal.probe(a.seconds, a.gpu, a.out)
                if not r["ok"]:
                    print(f"probe failed: {r['reason']} ({r['path']})")
                    return 1
                _print_summary(r)
                if r["user_clocks_frac"] is None:
                    print("If clocks were still locked from an earlier step, this measured the locked clock: run "
                          f"`nvidia-smi -i {a.gpu} -rgc` and probe again.")
                print("Suggested sweep:\n  python -m ueic calib plan --clocks " + ",".join(map(str, r["suggested_clocks"])))
                if r.get("at_power_limit"):
                    print("The top suggested clock is where this GPU reaches its own power limit under this kernel. "
                          "That is normal for a desktop card at full load; the sweep is fine, and locks near the top "
                          "may run a few MHz low, which the fit handles by using the measured clock.")
                elif (r["limited_frac"] or 0) > 0.5:
                    print("These clocks fit the limited range. If you can lift the limit, probe again first: the "
                          "sweep should reach the clock the GPU holds without a limit. Otherwise they are usable; "
                          "the fit will record that its top clock was set by a limit.")
                return 0
            if a.ccmd == "run":
                print(cal.run_session(a.kind, a.seconds, a.out, a.label, a.gpu, idle_before_s=a.idle_before))
                return 0
        except RuntimeError as e:
            print(f"error: {e}\n(nothing was recorded; `python -m ueic calib check` diagnoses the environment)")
            return 2
        if a.ccmd == "fit":
            import glob, hashlib, json as _json
            dirs = sorted({d for pat in a.sessions for d in glob.glob(pat) if Path(d, "session.json").exists()})
            try:
                out = cal.calibrate(dirs, device=a.device)
            except ValueError as e:
                print(f"error: {e}")
                return 2
            Path(a.out).write_text(_json.dumps(out, indent=1))
            print(f"{len(dirs)} sessions -> {a.out}")
            cr = out["clock_reference"]
            if cr["f_ref_MHz"]:
                print(f"  clock reference s = 1 at {cr['f_ref_MHz']:.0f} MHz (highest steady compute clock; "
                      f"NVML table max {cr['nvml_max_sm_clock_MHz']:.0f} MHz)")
            fp = out["fits"].get("power_vs_clock", {})
            fl = out["fits"].get("leakage", {})
            if fp.get("ok"):
                print(f"  power vs clock: R^2 {fp['r2']:.4f}, rms residual {fp['rms_resid_W']:.1f} W over {fp['n']} clocks")
            if fl.get("ok"):
                print(f"  leakage warm-up: {fl['T_range_C'][0]:.0f}-{fl['T_range_C'][1]:.0f} C, power "
                      f"{fl['P_range_W'][0]:.0f}-{fl['P_range_W'][1]:.0f} W, R^2 {fl['r2']:.3f}")
            fmt = lambda v: f"{v['value']}" + (f" +/- {1.96 * v['se']:.2g} (95% CI)" if v.get("se") else "")
            print("  accepted (transferred to calibrated experiments):" if out["overrides"] else
                  "  accepted: none")
            for k, v in out["overrides"].items():
                print(f"    {k} = {fmt(v)}  class {v['evidence']}" +
                      (f"  [{v['status']}: measured {v['measured']}]" if "measured" in v else ""))
            if out.get("rejected"):
                print("  rejected (kept in the record, not transferred):")
                for k, v in out["rejected"].items():
                    print(f"    {k} = {v['value']}: {v['reason']}")
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
