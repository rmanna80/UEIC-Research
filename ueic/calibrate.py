"""Phase 4 calibration: run measured workload sessions on a real GPU and fit the
simulator parameters that drive the Phase 1 conclusions.

A *session* is one workload run (compute-bound, memory-bound, or a warm-up from
cold) recorded together with read-only NVML telemetry:

    data/calibration/<session>/telemetry.csv (+ .meta.json)
                              /workload.csv    throughput samples from the workload
                              /session.json    kind, label, device, timing

Fits (all on steady-state windows, each with a standard error):
  beta_compute, beta_memory   log(throughput) = beta * log(f / f_max) + c
  v_min_ratio                 P = A + P_d * s * v(s)^2,  v linear in s (registry form, s_min = 0.5)
  kappa_leak, leak fraction   P(T) = c + L * exp(kappa * (T - 60 C)) at fixed clock and load

Only dimensionless shape parameters are transferred to the simulated accelerator
directly (class B on the measured device). The leakage *fraction* is transferred by
scaling to the simulated accelerator's power, which is an extrapolation (class E).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
from scipy.optimize import curve_fit

from .telemetry import Logger, read_csv

T_REF = 60.0
S_MIN = 0.5   # registry s_min; the v(s) form is anchored here so the fit maps 1:1 onto v_min_ratio


# ----------------------------------------------------------------------------- workloads
def torch_workload(kind: str, gpu: int = 0) -> Callable[[float], float]:
    """Return step(budget_s) -> throughput for one burst of work (needs PyTorch with CUDA)."""
    try:
        import torch
    except ImportError as e:  # pragma: no cover - host dependent
        raise RuntimeError("Calibration workloads need PyTorch with CUDA (see docs/09_calibration_protocol.md)") from e
    if not torch.cuda.is_available():  # pragma: no cover
        raise RuntimeError("PyTorch cannot see a CUDA GPU")
    dev = torch.device(f"cuda:{gpu}")
    if kind in ("compute", "warmup"):
        n = 4096
        a = torch.randn(n, n, device=dev, dtype=torch.float16)
        b = torch.randn(n, n, device=dev, dtype=torch.float16)
        flops = 2.0 * n ** 3

        def step(budget):
            t0, k = time.perf_counter(), 0
            while time.perf_counter() - t0 < budget:
                for _ in range(8):
                    a @ b
                torch.cuda.synchronize(dev)
                k += 8
            return k * flops / (time.perf_counter() - t0) / 1e12   # TFLOP/s
    elif kind == "memory":
        n = 128 * 1024 * 1024                                       # 512 MiB per fp32 tensor
        x = torch.ones(n, device=dev, dtype=torch.float32)
        y = torch.zeros(n, device=dev, dtype=torch.float32)
        bytes_per = 3.0 * 4 * n                                     # read x, read y, write y

        def step(budget):
            t0, k = time.perf_counter(), 0
            while time.perf_counter() - t0 < budget:
                for _ in range(4):
                    y.add_(x, alpha=1e-6)
                torch.cuda.synchronize(dev)
                k += 4
            return k * bytes_per / (time.perf_counter() - t0) / 1e9  # GB/s
    else:
        raise ValueError(f"unknown workload kind {kind}")
    return step


def run_session(kind: str, seconds: float, out_root: str | Path, label: str = "", gpu: int = 0,
                interval_s: float = 0.1, idle_before_s: float = 0.0, nvml=None,
                workload: Callable[[float], float] | None = None) -> Path:
    """Record one calibration session. `nvml` and `workload` can be injected for tests."""
    if kind not in ("compute", "memory", "warmup"):
        raise ValueError("kind must be compute, memory or warmup")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    safe = "".join(ch if ch.isalnum() or ch in "-_.=" else "_" for ch in label)[:40]
    d = Path(out_root) / f"{stamp}_{kind}{'_' + safe if safe else ''}"
    d.mkdir(parents=True, exist_ok=False)
    step = workload or torch_workload(kind, gpu)
    log = Logger(d / "telemetry.csv", interval_s=interval_s, gpus=[gpu], nvml=nvml, label="idle").start()
    try:
        if idle_before_s > 0:
            time.sleep(idle_before_s)
        log.set_label(kind)
        rows = []
        t_end = time.time() + seconds
        while time.time() < t_end:
            thr = step(min(0.5, max(0.05, t_end - time.time())))
            rows.append((time.time(), thr))
        log.set_label("done")
        time.sleep(min(1.0, interval_s * 5))
    finally:
        meta = log.stop()
    with open(d / "workload.csv", "w") as f:
        f.write("t_unix,throughput\n")
        for t, v in rows:
            f.write(f"{t:.6f},{v:.6g}\n")
    unit = "TFLOP/s" if kind in ("compute", "warmup") else "GB/s"
    (d / "session.json").write_text(json.dumps({
        "kind": kind, "label": label, "seconds": seconds, "gpu": gpu, "throughput_unit": unit,
        "idle_before_s": idle_before_s, "device": meta["devices"][0], "telemetry_sha256": meta["csv_sha256"],
        "provenance": "physical_measurement"}, indent=1))
    return d


# ------------------------------------------------------------------------------ analysis
@dataclass
class Session:
    path: Path
    kind: str
    label: str
    max_clock: float
    tel: list[dict[str, Any]]
    work: np.ndarray            # (n, 2) t_unix, throughput


def load_session(d: str | Path) -> Session:
    d = Path(d)
    meta = json.loads((d / "session.json").read_text())
    work = np.loadtxt(d / "workload.csv", delimiter=",", skiprows=1, ndmin=2)
    return Session(d, meta["kind"], meta.get("label", ""), float(meta["device"]["max_sm_clock_MHz"] or np.nan),
                   read_csv(d / "telemetry.csv"), work)


def steady(sess: Session, skip_s: float = 10.0) -> tuple[list[dict], np.ndarray]:
    tel = [r for r in sess.tel if r["label"] == sess.kind and r["power_W"] is not None]
    if not tel:
        return [], sess.work[:0]
    t0 = tel[0]["t_unix"] + skip_s
    tel = [r for r in tel if r["t_unix"] >= t0]
    work = sess.work[sess.work[:, 0] >= t0]
    return tel, work


def summarize(sess: Session, skip_s: float = 10.0) -> dict[str, Any]:
    tel, work = steady(sess, skip_s)
    if len(tel) < 5 or len(work) < 3:
        return {"kind": sess.kind, "path": str(sess.path), "ok": False, "reason": "too few steady samples"}
    clk = np.array([r["sm_clock_MHz"] for r in tel], dtype=float)
    pw = np.array([r["power_W"] for r in tel], dtype=float)
    tc = np.array([r["temp_C"] for r in tel], dtype=float)
    return {"kind": sess.kind, "path": str(sess.path), "ok": True, "n": len(tel),
            "clock_MHz": float(np.median(clk)), "clock_cv": float(np.std(clk) / np.mean(clk)),
            "s": float(np.median(clk) / sess.max_clock), "power_W": float(np.median(pw)),
            "temp_C": float(np.median(tc)), "throughput": float(np.median(work[:, 1]))}


def _linfit(x, y):
    A = np.vstack([x, np.ones_like(x)]).T
    coef, res, *_ = np.linalg.lstsq(A, y, rcond=None)
    n = len(x)
    resid = y - A @ coef
    s2 = float(resid @ resid) / max(n - 2, 1)
    cov = s2 * np.linalg.inv(A.T @ A)
    r2 = 1 - float(resid @ resid) / float(((y - y.mean()) ** 2).sum()) if n > 2 else float("nan")
    return coef, np.sqrt(np.diag(cov)), r2


def fit_beta(summaries: list[dict]) -> dict[str, Any]:
    pts = [(s["s"], s["throughput"]) for s in summaries if s.get("ok")]
    if len({round(p[0], 3) for p in pts}) < 2:
        return {"ok": False, "reason": "need sessions at >= 2 different clocks"}
    x = np.log([p[0] for p in pts])
    y = np.log([p[1] for p in pts])
    coef, se, r2 = _linfit(x, y)
    return {"ok": True, "value": float(coef[0]), "se": float(se[0]), "n": len(pts), "r2": r2,
            "method": "log-log least squares of median throughput vs median SM clock / max clock"}


def v_of_s(s, vmin):
    return vmin + (1.0 - vmin) * (np.asarray(s) - S_MIN) / (1.0 - S_MIN)


def _power_model(s, A, Pd, vmin):
    return A + Pd * s * v_of_s(s, vmin) ** 2


def fit_power_clock(summaries: list[dict]) -> dict[str, Any]:
    pts = [(s["s"], s["power_W"]) for s in summaries if s.get("ok")]
    if len({round(p[0], 3) for p in pts}) < 3:
        return {"ok": False, "reason": "need compute sessions at >= 3 different clocks"}
    s = np.array([p[0] for p in pts])
    P = np.array([p[1] for p in pts])
    p0 = (0.3 * P.min(), P.max(), 0.7)
    popt, pcov = curve_fit(_power_model, s, P, p0=p0, bounds=([0, 0, 0.3], [np.inf, np.inf, 1.0]), maxfev=20000)
    se = np.sqrt(np.diag(pcov))
    return {"ok": True, "A_W": float(popt[0]), "P_dyn_W": float(popt[1]), "v_min_ratio": float(popt[2]),
            "v_min_ratio_se": float(se[2]), "n": len(pts),
            "method": "P = A + P_d * s * v(s)^2 with v linear between s_min = 0.5 and 1 (registry form); "
                      "temperature differences between sessions are not removed"}


def _leak_model(T, c, L, kappa):
    return c + L * np.exp(kappa * (np.asarray(T) - T_REF))


def fit_leakage(sess: Session, clock_tol_MHz: float = 15.0) -> dict[str, Any]:
    tel, _ = steady(sess, skip_s=2.0)
    if len(tel) < 30:
        return {"ok": False, "reason": "too few samples in warm-up session"}
    clk = np.array([r["sm_clock_MHz"] for r in tel], dtype=float)
    keep = np.abs(clk - np.median(clk)) <= clock_tol_MHz
    T = np.array([r["temp_C"] for r in tel], dtype=float)[keep]
    P = np.array([r["power_W"] for r in tel], dtype=float)[keep]
    if T.max() - T.min() < 8.0:
        return {"ok": False, "reason": f"temperature rose only {T.max() - T.min():.1f} K at constant clock; "
                                       "need >= 8 K (start from a cold GPU)"}
    p0 = (np.min(P) * 0.8, np.min(P) * 0.2, 0.02)
    popt, pcov = curve_fit(_leak_model, T, P, p0=p0, bounds=([0, 0, 0], [np.inf, np.inf, 0.2]), maxfev=20000)
    se = np.sqrt(np.diag(pcov))
    c, L, k = popt
    resid = P - _leak_model(T, *popt)
    return {"ok": True, "kappa": float(k), "kappa_se": float(se[2]), "L_ref_W": float(L), "L_ref_se": float(se[1]),
            "c_W": float(c), "leak_fraction_at_ref": float(L / (c + L)), "n": int(keep.sum()),
            "T_range_C": [float(T.min()), float(T.max())], "clock_MHz": float(np.median(clk[keep])),
            "resid_std_W": float(resid.std()),
            "method": "P(T) = c + L*exp(kappa*(T-60)) at constant clock and load during warm-up; assumes the "
                      "temperature-dependent part of board power is leakage (fan and VR losses are not separated)"}


def calibrate(session_dirs: Iterable[str | Path], cfg=None) -> dict[str, Any]:
    from .params import make_config
    cfg = cfg or make_config()
    sessions = [load_session(d) for d in session_dirs]
    summ = [summarize(s) for s in sessions]
    by = lambda k: [x for x in summ if x["kind"] == k]
    out: dict[str, Any] = {
        "kind": "ueic_calibration", "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "device": json.loads((sessions[0].path / "session.json").read_text())["device"] if sessions else None,
        "sessions": summ, "fits": {}, "overrides": {}, "notes": [],
    }
    fb_c, fb_m = fit_beta(by("compute")), fit_beta(by("memory"))
    out["fits"]["beta_compute"], out["fits"]["beta_memory"] = fb_c, fb_m
    fp = fit_power_clock(by("compute"))
    out["fits"]["power_vs_clock"] = fp
    warm = [s for s in sessions if s.kind == "warmup"]
    fl = fit_leakage(warm[-1]) if warm else {"ok": False, "reason": "no warm-up session"}
    out["fits"]["leakage"] = fl
    ov = out["overrides"]
    if fb_c["ok"]:
        ov["beta_compute"] = {"value": round(fb_c["value"], 4), "se": fb_c["se"], "evidence": "B"}
    if fb_m["ok"]:
        ov["beta_memory"] = {"value": round(fb_m["value"], 4), "se": fb_m["se"], "evidence": "B"}
    if fp["ok"]:
        ov["v_min_ratio"] = {"value": round(fp["v_min_ratio"], 4), "se": fp["v_min_ratio_se"], "evidence": "B"}
    if fl["ok"]:
        ov["kappa_leak"] = {"value": round(fl["kappa"], 5), "se": fl["kappa_se"], "evidence": "B"}
        f = fl["leak_fraction_at_ref"]
        scaled = f / (1 - f) * (cfg.p_dyn_max + cfg.p_static_other)
        ov["p_leak_ref"] = {"value": round(float(scaled), 2), "se": None, "evidence": "E",
                            "note": f"measured leak fraction {f:.3f} at 60 C scaled to the simulated accelerator"}
    for k, v in list(ov.items()):
        lo, hi = None, None
        from .params import REGISTRY
        if REGISTRY[k].low is not None:
            lo, hi = REGISTRY[k].low, REGISTRY[k].high
            if not lo <= v["value"] <= hi:
                out["notes"].append(f"{k} = {v['value']} lies outside the registry range [{lo}, {hi}] swept in E002")
    # every override must yield a valid configuration
    make_config({k: v["value"] for k, v in ov.items()})
    return out


def apply_calibration(spec: dict[str, Any], calib: dict[str, Any], calib_sha256: str) -> dict[str, Any]:
    """New spec whose every cell uses the calibrated values; provenance travels with the spec."""
    spec = json.loads(json.dumps(spec))
    over = {k: v["value"] for k, v in calib["overrides"].items()}
    spec["design"]["param_overrides"] = {**spec["design"].get("param_overrides", {}), **over}
    spec["key"] = spec["key"] + "C"
    spec["title"] = spec["title"] + " (calibrated)"
    spec["calibration_source"] = {"sha256": calib_sha256, "device": calib.get("device"), "overrides": calib["overrides"]}
    return spec


def ingest(store, calib: dict[str, Any], calib_sha256: str, key: str = "M001") -> str:
    """Record a calibration as a measurement experiment in the append-only store."""
    spec = {
        "key": key, "title": f"GPU calibration measurement ({(calib.get('device') or {}).get('name', 'unknown GPU')})",
        "research_question": "What are the clock-throughput, clock-power and leakage-temperature parameters of a real GPU?",
        "hypothesis": "Measurement, not a test: no hypothesis. Values are compared with the registry ranges.",
        "independent_variables": ["SM clock (set by the user)", "workload kind", "die temperature during warm-up"],
        "dependent_variables": ["throughput", "board power"],
        "controlled_variables": ["workload kernels", "steady-state windows"],
        "baseline": "registry defaults", "configuration": "see sessions in the calibration file",
        "data_collection": "Read-only NVML telemetry at the logged interval plus workload throughput samples.",
        "evaluation_criteria": "Fit standard errors; values outside registry ranges are flagged.",
        "known_limitations": "GPU board power only; one device; laptop GPUs may limit clocks and boost; "
                             "fan and VR losses are not separated from leakage.",
        "design": {"measurement": True}, "calibration_sha256": calib_sha256,
    }
    exp_id = store.register_experiment(spec)
    store.set_experiment_status(exp_id, "running")
    run_id = store.start_run(exp_id, {"kind": "calibration", "variant": "measured", "policy": "-", "scenario": "-"},
                             0, {"calibration": calib}, {})
    metrics = {}
    for k, v in calib["overrides"].items():
        prov = "physical_measurement" if v["evidence"] == "B" else "engineering_assumption"
        metrics[k] = (float(v["value"]), "-", prov)
        if v.get("se") is not None:
            metrics[k + "_se"] = (float(v["se"]), "-", prov)
    store.finish_run(run_id, metrics, calib.get("notes", []), None)
    store.set_experiment_status(exp_id, "completed", {"runs": 1, "failed": 0, "measurement": True})
    return exp_id


def plan_commands(clocks_MHz: list[int], gpu: int = 0, seconds: int = 60) -> str:
    """Commands for the USER to review and run. UEIC never executes clock changes itself."""
    lines = ["# Review before running. Clock locking needs an elevated (Administrator) PowerShell and is",
             "# not supported on every GPU (many laptop GPUs refuse it). UEIC only records; it never changes clocks.",
             f"nvidia-smi -i {gpu} -q -d SUPPORTED_CLOCKS | more    # pick clocks from this list", ""]
    mid = sorted(clocks_MHz)[len(clocks_MHz) // 2]
    lines += ["# 1) Leakage warm-up at one locked clock: 5 min idle to cool down, then 10 min of steady load.",
              f"nvidia-smi -i {gpu} -lgc {mid},{mid}",
              f"python -m ueic calib run --kind warmup --seconds 600 --idle-before 300 --gpu {gpu} --label clk={mid}",
              "# 2) Clock sweep: compute-bound and memory-bound kernels at each clock."]
    for c in clocks_MHz:
        lines += [f"nvidia-smi -i {gpu} -lgc {c},{c}",
                  f"python -m ueic calib run --kind compute --seconds {seconds} --gpu {gpu} --label clk={c}",
                  f"python -m ueic calib run --kind memory --seconds {seconds} --gpu {gpu} --label clk={c}"]
    lines += [f"nvidia-smi -i {gpu} -rgc    # reset clocks to default", "",
              "python -m ueic calib fit data\\calibration\\* --out data\\calibration\\calibration.json"]
    return "\n".join(lines)
