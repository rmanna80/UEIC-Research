"""Phase 4 calibration: run measured workload sessions on a real GPU and fit the
simulator parameters that drive the Phase 1 conclusions.

A *session* is one workload run (compute-bound, memory-bound, or a warm-up from
cold) recorded together with read-only NVML telemetry:

    data/calibration/<session>/telemetry.csv (+ .meta.json)
                              /workload.csv    throughput samples from the workload
                              /session.json    kind, label, device, timing

Fits (all on steady-state windows, each with a standard error):
  beta_compute, beta_memory   log(throughput) = beta * log(f / f_ref) + c
  v_min_ratio                 P = A + P_d * s * v(s)^2,  v linear in s (registry form, s_min = 0.5)
  kappa_leak, leak fraction   P(T) = c + L * exp(kappa * (T - 60 C)) at fixed clock and load

Clock reference. The simulator's s = 1 is the highest clock the accelerator runs at.
NVML's "max SM clock" is the top of the driver's clock table, which many GPUs (laptop
parts especially) never sustain under load: an RTX 4060 Laptop reports 3105 MHz. So
s = f / f_ref with f_ref = the highest steady clock measured among the compute sessions,
and the power fit only uses sessions with s >= s_min, the range the simulator models.

Only dimensionless shape parameters are transferred to the simulated accelerator
directly (class B on the measured device). The leakage *fraction* is transferred by
scaling to the simulated accelerator's power, which is an extrapolation (class E).
"""
from __future__ import annotations

import json
import platform
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
from scipy.optimize import curve_fit

from .telemetry import Logger, Nvml, read_csv

T_REF = 60.0
S_MIN = 0.5   # registry s_min; the v(s) form is anchored here so the fit maps 1:1 onto v_min_ratio
KINDS = ("compute", "memory", "warmup", "probe")
# nvml.h clock-event ("throttle") reasons that mean a limit held the clock down. Values checked
# against nvidia-ml-py's nvmlClocksEventReason* / nvmlClocksThrottleReason* constants.
LIMIT_REASONS = {
    "sw_power_cap": (0x4, "power cap (the driver holds board power at a limit)"),
    "hw_slowdown": (0x8, "hardware slowdown (power-supply or temperature protection)"),
    "sw_thermal": (0x20, "temperature target (the driver holds the GPU at a temperature)"),
    "hw_thermal": (0x40, "hardware thermal protection"),
    "power_brake": (0x80, "external power brake signal"),
    "board_limit": (0x200, "board limit"),
    "reliability": (0x400, "reliability voltage limit"),
}
LIMIT_BITS = sum(bit for bit, _ in LIMIT_REASONS.values())
USER_CLOCKS_BIT = 0x2   # clocks limited by a user setting (application or locked clocks)
CLOCK_HELD_TOL = 0.03          # a locked clock counts as held if the median is within 3%
INSTALL_HINT = ("\n    pip uninstall -y torch"
                "\n    pip install torch --index-url https://download.pytorch.org/whl/cu130"
                "\n  (cu130 suits drivers that report CUDA 13.0 or newer in nvidia-smi; other builds are listed at "
                "https://pytorch.org/get-started/locally/)")


# ----------------------------------------------------------------------------- environment
def torch_status(gpu: int = 0) -> dict[str, Any]:
    """What this interpreter's PyTorch can do. Never raises."""
    st: dict[str, Any] = {"python": sys.executable, "venv_active": sys.prefix != sys.base_prefix,
                          "torch": None, "torch_cuda_build": None, "cuda_available": False, "device": None}
    try:
        import torch
    except ImportError:
        return st
    st["torch"] = str(getattr(torch, "__version__", "?"))
    st["torch_cuda_build"] = getattr(getattr(torch, "version", None), "cuda", None)
    try:
        st["cuda_available"] = bool(torch.cuda.is_available())
        if st["cuda_available"] and gpu < torch.cuda.device_count():
            st["device"] = str(torch.cuda.get_device_name(gpu))
    except Exception:  # noqa: BLE001 - a broken CUDA install should be reported, not crash the check
        st["cuda_available"] = False
    return st


def torch_problem(st: dict[str, Any], gpu: int = 0) -> str | None:
    """Plain-language reason the calibration workload cannot run, or None if it can."""
    where = (f"this Python is {st['python']} "
             f"(virtual environment {'active' if st['venv_active'] else 'NOT active'})")
    venv = "" if st["venv_active"] else ("\n  If PyTorch with CUDA is installed in the project venv, activate it in "
                                         "this window first:\n    .\\.venv\\Scripts\\Activate.ps1")
    if st["torch"] is None:
        return f"PyTorch is not installed for this Python; {where}.{venv}\n  Otherwise install it:{INSTALL_HINT}"
    if st["torch_cuda_build"] is None:
        return (f"PyTorch {st['torch']} is a CPU-only build, so it cannot run work on the GPU; {where}.{venv}"
                f"\n  Otherwise replace it with a CUDA build:{INSTALL_HINT}")
    if not st["cuda_available"]:
        return (f"PyTorch {st['torch']} is built for CUDA {st['torch_cuda_build']} but sees no CUDA GPU; {where}. "
                f"Check that `nvidia-smi` reports CUDA {st['torch_cuda_build']} or newer and that the GPU is enabled.")
    if st["device"] is None:
        return f"PyTorch sees CUDA but has no GPU with index {gpu}; {where}."
    return None


def check(gpu: int = 0, nvml=None) -> list[tuple[str, str]]:
    """Read-only preflight: (status, message) with status in ok / warn / fail / info."""
    st = torch_status(gpu)
    out = [("info", f"Python {platform.python_version()} at {st['python']}")]
    out.append(("ok", "virtual environment active") if st["venv_active"] else
               ("warn", "no virtual environment active in this window (.\\.venv\\Scripts\\Activate.ps1)"))
    prob = torch_problem(st, gpu)
    out.append(("fail", prob) if prob else
               ("ok", f"PyTorch {st['torch']} (CUDA {st['torch_cuda_build']}) can use {st['device']}"))
    try:
        nv = Nvml(nvml)
        try:
            dev = next((d for d in nv.devices() if d.index == gpu), None)
            if dev is None:
                out.append(("fail", f"NVML found no GPU with index {gpu}"))
            else:
                now = nv.sample(dev)
                out.append(("ok", f"NVML: [{gpu}] {dev.name}, driver {nv.driver}, power limit {dev.power_limit_W} W, "
                                  f"now {now['sm_clock_MHz']} MHz SM / {now['temp_C']} C / {now['power_W']} W"))
        finally:
            nv.close()
    except Exception as e:  # noqa: BLE001
        out.append(("fail", f"NVML telemetry unavailable: {e}"))
    return out


# ----------------------------------------------------------------------------- workloads
def torch_workload(kind: str, gpu: int = 0) -> Callable[[float], float]:
    """Return step(budget_s) -> throughput for one burst of work (needs PyTorch with CUDA)."""
    prob = torch_problem(torch_status(gpu), gpu)
    if prob:
        raise RuntimeError(prob)
    import torch
    dev = torch.device(f"cuda:{gpu}")
    if kind in ("compute", "warmup", "probe"):
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
    """Record one calibration session. `nvml` and `workload` can be injected for tests.
    Everything that can fail before measuring (PyTorch, NVML) is checked before the session
    folder exists, so a failed start leaves nothing behind."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    safe = "".join(ch if ch.isalnum() or ch in "-_.=" else "_" for ch in label)[:40]
    d = Path(out_root) / f"{stamp}_{kind}{'_' + safe if safe else ''}"
    if d.exists():
        raise FileExistsError(d)
    step = workload or torch_workload(kind, gpu)
    try:
        log = Logger(d / "telemetry.csv", interval_s=interval_s, gpus=[gpu], nvml=nvml, label="idle")
    except Exception:
        if d.exists() and not any(d.iterdir()):
            d.rmdir()
        raise
    log.start()
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
    unit = "GB/s" if kind == "memory" else "TFLOP/s"
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
    power_limit_W: float | None = None   # enforced limit when the session started
    device: dict[str, Any] | None = None  # NVML identity recorded in session.json


def device_key(dev: dict[str, Any] | None) -> str:
    """Identity used to keep one calibration to one GPU: UUID when recorded, else the name."""
    dev = dev or {}
    return str(dev.get("uuid") or dev.get("name") or "unknown GPU")


def device_label(dev: dict[str, Any] | None) -> str:
    dev = dev or {}
    u = dev.get("uuid")
    return f"{dev.get('name', 'unknown GPU')}" + (f" ({u})" if u else "")


def load_session(d: str | Path) -> Session:
    d = Path(d)
    meta = json.loads((d / "session.json").read_text())
    work = np.loadtxt(d / "workload.csv", delimiter=",", skiprows=1, ndmin=2)
    return Session(d, meta["kind"], meta.get("label", ""), float(meta["device"]["max_sm_clock_MHz"] or np.nan),
                   read_csv(d / "telemetry.csv"), work, meta["device"].get("power_limit_W"), meta["device"])


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
    reasons = [r.get("clock_event_reasons") for r in tel]
    known = [int(x) for x in reasons if x is not None]
    m = re.search(r"clk=(\d+)", sess.label or "")
    return {"kind": sess.kind, "path": str(sess.path), "name": sess.path.name, "ok": True, "n": len(tel),
            "clock_MHz": float(np.median(clk)), "clock_cv": float(np.std(clk) / np.mean(clk)),
            "label_clock_MHz": float(m.group(1)) if m else None,
            "s_nvml": float(np.median(clk) / sess.max_clock), "power_W": float(np.median(pw)),
            "temp_C": float(np.median(tc)), "throughput": float(np.median(work[:, 1])),
            "limited_frac": float(np.mean([(x & LIMIT_BITS) != 0 for x in known])) if known else None,
            "limit_reasons": {k: float(np.mean([(x & bit) != 0 for x in known]))
                              for k, (bit, _) in LIMIT_REASONS.items() if any(x & bit for x in known)},
            "user_clocks_frac": float(np.mean([(x & USER_CLOCKS_BIT) != 0 for x in known])) if known else None,
            "power_p95_W": float(np.percentile(pw, 95)),
            "power_limit_W": (lim_w := _median_or(tel, "power_limit_W", sess.power_limit_W)),
            "at_power_limit": bool(lim_w and float(np.median(pw)) >= 0.98 * lim_w),
            "device": device_label(sess.device), "device_key": device_key(sess.device),
            "nvml_max_clock_MHz": sess.max_clock}


def _median_or(rows: list[dict], key: str, default):
    v = [r.get(key) for r in rows if r.get(key) is not None]
    return float(np.median(v)) if v else default


def interpret_limits(sm: dict[str, Any]) -> list[str]:
    """Plain-language reading of which limit held the clock down. Inferences are worded as such."""
    out = []
    reasons = sm.get("limit_reasons") or {}
    for k, frac in sorted(reasons.items(), key=lambda kv: -kv[1]):
        out.append(f"{100 * frac:.0f}% of samples: {LIMIT_REASONS[k][1]}")
    if (sm.get("user_clocks_frac") or 0) > 0.5:
        out.append("the driver reports user-set clocks (a clock lock is active): run `nvidia-smi -i 0 -rgc` "
                   "and probe again")
    lim, p = sm.get("power_limit_W"), sm.get("power_p95_W")
    if reasons.get("sw_power_cap", 0) > 0.5 and lim and p and p < 0.8 * lim:
        out.append(f"likely cause: power stayed at or below {p:.0f} W although the GPU reports a {lim:.0f} W limit, "
                   "so a lower budget was set outside the GPU. On laptops that usually means running on battery, "
                   "a quiet or balanced power mode, or the CPU and GPU sharing one power budget. Plug in, choose "
                   "the performance mode (Windows and the laptop maker's app), and probe again")
    if lim and p and sm.get("power_W", 0) >= 0.98 * lim and reasons.get("sw_power_cap", 0) <= 0.5:
        out.append(f"power is at the GPU's reported limit ({sm['power_W']:.1f} of {lim:.0f} W) although the driver "
                   "flagged no power cap, so this clock is probably set by the power limit. Cross-check with "
                   "`nvidia-smi -q -d POWER,PERFORMANCE` while a load runs")
    if (reasons.get("sw_thermal", 0) > 0.5 or reasons.get("hw_thermal", 0) > 0.1):
        out.append(f"likely cause: temperature ({sm.get('temp_C', float('nan')):.0f} C median). Clear the vents, "
                   "raise the laptop for airflow, let it cool, and probe again")
    return out


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


def fit_power_clock(summaries: list[dict], s_floor: float = S_MIN - 0.02) -> dict[str, Any]:
    """Only sessions with s >= s_min are used: below it the registry's linear v(s) would be
    extrapolated (real GPUs hold a voltage floor there), which would bias v_min_ratio."""
    ok = [s for s in summaries if s.get("ok")]
    excluded = sorted(round(s["s"], 3) for s in ok if s["s"] < s_floor)
    pts = [(s["s"], s["power_W"]) for s in ok if s["s"] >= s_floor]
    if len({round(p[0], 3) for p in pts}) < 4:   # 3 parameters: a 4th clock is needed for a standard error
        return {"ok": False, "excluded_s": excluded,
                "reason": f"need compute sessions at >= 4 different clocks between {S_MIN:g} x and 1 x the "
                          f"highest measured clock ({len(pts)} usable, {len(excluded)} below that range)"}
    s = np.array([p[0] for p in pts])
    P = np.array([p[1] for p in pts])
    p0 = (0.3 * P.min(), P.max(), 0.7)
    popt, pcov = curve_fit(_power_model, s, P, p0=p0, bounds=([0, 0, 0.3], [np.inf, np.inf, 1.0]), maxfev=20000)
    se = np.sqrt(np.diag(pcov))
    return {"ok": True, "A_W": float(popt[0]), "P_dyn_W": float(popt[1]), "v_min_ratio": float(popt[2]),
            "v_min_ratio_se": float(se[2]), "n": len(pts), "excluded_s": excluded,
            "s_range": [float(s.min()), float(s.max())],
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
            "fan_pct_range": _range_or_none([r.get("fan_pct") for r, k in zip(tel, keep) if k]),
            "method": "P(T) = c + L*exp(kappa*(T-60)) at constant clock and load during warm-up; assumes the "
                      "temperature-dependent part of board power is leakage (fan and VR losses are not separated)"}


def select_device(sessions: list[Session], device: str | None = None) -> tuple[list[Session], list[str]]:
    """A calibration describes one GPU. Refuse to mix measurement sessions from different GPUs;
    `device` (part of the name or UUID) chooses one when several are present. Probe sessions never
    enter a fit, so probes from other GPUs are dropped with a note instead of blocking."""
    notes: list[str] = []
    if device:
        sessions = [s for s in sessions if device.lower() in device_label(s.device).lower()]
        if not sessions:
            raise ValueError(f"no session matches --device {device!r}")
    groups: dict[str, list[Session]] = {}
    for s in sessions:
        if s.kind != "probe":
            groups.setdefault(device_key(s.device), []).append(s)
    if len(groups) > 1:
        listing = "; ".join(f"{device_label(g[0].device)}: {len(g)} sessions" for g in groups.values())
        raise ValueError(f"sessions come from {len(groups)} different GPUs ({listing}). A calibration describes one "
                         "GPU: pass --device with part of its name or UUID")
    if groups:
        key = next(iter(groups))
        other = [s for s in sessions if device_key(s.device) != key]
        if other:
            notes.append(f"left out {len(other)} probe session(s) from other GPUs: "
                         + ", ".join(sorted({device_label(s.device) for s in other})))
        sessions = [s for s in sessions if device_key(s.device) == key]
    return sessions, notes


def devices_in(root: str | Path) -> dict[str, int]:
    """Session counts per GPU in a calibration folder."""
    out: dict[str, int] = {}
    for d in Path(root).glob("*"):
        if (d / "session.json").exists():
            lab = device_label(json.loads((d / "session.json").read_text()).get("device"))
            out[lab] = out.get(lab, 0) + 1
    return out


def _range_or_none(v: list) -> list[float] | None:
    v = [float(x) for x in v if x is not None]
    return [min(v), max(v)] if v else None


def calibrate(session_dirs: Iterable[str | Path], cfg=None, device: str | None = None) -> dict[str, Any]:
    from .params import make_config
    cfg = cfg or make_config()
    sessions, device_notes = select_device([load_session(d) for d in session_dirs], device)
    summ = [summarize(s) for s in sessions]
    by = lambda k: [x for x in summ if x["kind"] == k]
    out: dict[str, Any] = {
        "kind": "ueic_calibration", "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "device": json.loads((sessions[0].path / "session.json").read_text())["device"] if sessions else None,
        "sessions": summ, "fits": {}, "overrides": {}, "notes": [],
    }
    notes = out["notes"]
    notes.extend(device_notes)
    # clock reference: highest steady clock among compute sessions (see module docstring)
    comp = [x for x in by("compute") if x["ok"]]
    f_ref = max(x["clock_MHz"] for x in comp) if comp else None
    out["clock_reference"] = {
        "f_ref_MHz": f_ref, "nvml_max_sm_clock_MHz": sessions[0].max_clock if sessions else None,
        "method": "s = median SM clock / f_ref, f_ref = highest steady median SM clock among compute sessions"}
    for x in summ:
        if x["ok"] and f_ref:
            x["s"] = x["clock_MHz"] / f_ref
    # sessions whose locked clock was not held, or that ran into power or thermal limits
    for x in summ:
        if not x["ok"]:
            notes.append(f"{x['path']}: skipped ({x['reason']})")
            continue
        lc = x.get("label_clock_MHz")
        if lc and abs(x["clock_MHz"] - lc) / lc > CLOCK_HELD_TOL:
            notes.append(f"{x['name']}: locked at {lc:.0f} MHz but ran at {x['clock_MHz']:.0f} MHz (median); the "
                         "lock was not held. Fits use the measured clock")
        if x.get("limited_frac") is not None and x["limited_frac"] > 0.10:
            which = ", ".join(f"{LIMIT_REASONS[k][1].split(' (')[0]} {100 * v:.0f}%"
                              for k, v in sorted(x["limit_reasons"].items(), key=lambda kv: -kv[1]))
            notes.append(f"{x['name']}: clock held down by a limit in {100 * x['limited_frac']:.0f}% of samples "
                         f"({which})")
    probes = [x for x in by("probe") if x["ok"]]
    if probes and f_ref and f_ref < 0.9 * probes[-1]["clock_MHz"]:
        notes.append(f"highest swept clock {f_ref:.0f} MHz is below the clock the GPU sustains at default settings "
                     f"({probes[-1]['clock_MHz']:.0f} MHz, probe); v_min_ratio then describes only the lower part "
                     "of the voltage-frequency range")
    if comp and f_ref and min(x["s"] for x in comp) > S_MIN + 0.1:
        notes.append(f"lowest swept clock is {min(x['s'] for x in comp):.2f} x the highest; v_min_ratio (voltage at "
                     f"{S_MIN:g} x) is extrapolated. Add a clock near {S_MIN * f_ref:.0f} MHz")
    fb_c, fb_m = fit_beta(by("compute")), fit_beta(by("memory"))
    out["fits"]["beta_compute"], out["fits"]["beta_memory"] = fb_c, fb_m
    fp = fit_power_clock(by("compute"))
    out["fits"]["power_vs_clock"] = fp
    if fp.get("excluded_s"):
        notes.append(f"power-vs-clock fit left out compute sessions at s = {fp['excluded_s']} (below s_min = "
                     f"{S_MIN:g}, outside the simulator's clock range); they still count for beta_compute")
    warm = [s for s in sessions if s.kind == "warmup"]
    fl = fit_leakage(warm[-1]) if warm else {"ok": False, "reason": "no warm-up session"}
    out["fits"]["leakage"] = fl
    fr = fl.get("fan_pct_range") if fl.get("ok") else None
    if fr and fr[1] - fr[0] > 15:
        notes.append(f"fan speed rose from {fr[0]:.0f}% to {fr[1]:.0f}% during the warm-up. On desktop cards the fans "
                     "draw from the board power NVML reports, so part of the power rise is fan power and kappa_leak "
                     "is an upper bound. A fixed fan speed during the warm-up removes this")
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


def suggest_clocks(f_sustained: float, supported: list[int] | None = None, n: int = 5,
                   lo_frac: float = S_MIN) -> list[int]:
    """n lockable clocks from lo_frac x to 1 x the sustained clock. The top one never exceeds the
    sustained clock (a lock above it would not be held); the others snap to the nearest supported
    clock, or to the 15 MHz grid NVIDIA uses when the supported list is unavailable."""
    grid = sorted({int(c) for c in supported}) if supported else None

    def snap(x, down=False):
        if grid:
            cand = [c for c in grid if c <= x] if down else grid
            cand = cand or grid
            return min(cand, key=lambda c: abs(c - x))
        return int(15 * (np.floor(x / 15) if down else np.round(x / 15)))
    targets = np.linspace(lo_frac * f_sustained, f_sustained, n)
    out = [snap(t) for t in targets[:-1]] + [snap(targets[-1], down=True)]
    return sorted(set(out))


def probe(seconds: float = 60, gpu: int = 0, out_root: str | Path = "data/calibration", nvml=None,
          workload: Callable[[float], float] | None = None, skip_s: float = 10.0,
          interval_s: float = 0.1) -> dict[str, Any]:
    """Run the compute kernel at whatever clocks the GPU is currently using (expected: driver
    defaults, after `nvidia-smi -rgc`) and suggest sweep clocks from the clock it sustains.
    Probe sessions are kept as evidence but are not used in any fit."""
    d = run_session("probe", seconds, out_root, label="default-clocks", gpu=gpu, nvml=nvml, workload=workload,
                    interval_s=interval_s)
    sm = summarize(load_session(d), skip_s=skip_s)
    if not sm["ok"]:
        return {"ok": False, "path": str(d), "reason": sm["reason"]}
    supported = None
    try:
        nv = Nvml(nvml)
        try:
            dev = next((x for x in nv.devices() if x.index == gpu), None)
            supported = nv.supported_sm_clocks(dev) if dev else None
        finally:
            nv.close()
    except Exception:  # noqa: BLE001 - suggestion falls back to the 15 MHz grid
        supported = None
    return {**sm, "ok": True, "path": str(d), "suggested_clocks": suggest_clocks(sm["clock_MHz"], supported),
            "interpretation": interpret_limits(sm)}


def latest_session(root: str | Path) -> Path | None:
    """Most recent session folder (names start with a UTC timestamp)."""
    ds = sorted(p for p in Path(root).glob("*") if (p / "session.json").exists())
    return ds[-1] if ds else None


def show_session(d: str | Path, skip_s: float = 10.0) -> dict[str, Any]:
    sess = load_session(d)
    sm = summarize(sess, skip_s)
    if sm["ok"]:
        sm["interpretation"] = interpret_limits(sm)
        sm["label"] = sess.label
    return sm


def plan_commands(clocks_MHz: list[int], gpu: int = 0, seconds: int = 60) -> str:
    """Commands for the USER to review and run. UEIC never executes clock changes itself."""
    lines = ["# Review before running. Use ONE Administrator PowerShell for everything below (clock locking",
             "# needs it), with the project virtual environment active in that window: .\\.venv\\Scripts\\Activate.ps1",
             "# Some GPUs refuse clock locking. UEIC only records; it never changes clocks.",
             f"# If you stop partway, restore default clocks with: nvidia-smi -i {gpu} -rgc",
             f"python -m ueic calib check --gpu {gpu}     # must report PyTorch with CUDA and your GPU before you start",
             "# Clocks should come from `python -m ueic calib probe` (run at default clocks), which suggests them.", ""]
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
