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
KINDS = ("compute", "memory", "warmup", "probe", "idle")
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


def idle_workload() -> Callable[[float], float]:
    """No GPU work: the idle sessions of the fan sweep measure board power at each fan setting."""
    def step(budget):
        time.sleep(budget)
        return 0.0
    return step


class GuardError(RuntimeError):
    """A run stopped itself early because the GPU was not in the state its label promises."""

    def __init__(self, path: Path, reasons: list[str]):
        self.path, self.reasons = path, reasons
        super().__init__("; ".join(reasons))


FAN_TOL_PCT = 8.0


def guard_problems(rows: list[dict], label: str, kind: str) -> list[str]:
    """Compare recent telemetry with what the session label promises (read-only check).

    clk=N  -> the SM clock must be within CLOCK_HELD_TOL of N (is the lock active?)
    fan=N  -> the reported fan speed must be within FAN_TOL_PCT of N (did the fan tool apply it?);
              for load sessions of a fan sweep, power must also stay below the GPU's limit, since
              at the limit power is held constant and cannot rise with temperature."""
    probs: list[str] = []
    m_clk, m_fan = re.search(r"clk=(\d+)", label or ""), _FAN_RE.search(label or "")
    rows = [r for r in rows if r.get("power_W") is not None]
    if not rows:
        return probs
    med = lambda k: (float(np.median(v)) if (v := [r[k] for r in rows if r.get(k) is not None]) else None)
    clk, fan, pw, lim = med("sm_clock_MHz"), med("fan_pct"), med("power_W"), med("power_limit_W")
    if m_clk and kind != "idle" and clk is not None:
        want = float(m_clk.group(1))
        if abs(clk - want) / want > CLOCK_HELD_TOL:
            probs.append(f"the label says clk={want:.0f} but the GPU is running at {clk:.0f} MHz: the clock lock is "
                         f"not active. In an Administrator PowerShell run: nvidia-smi -i 0 -lgc {want:.0f},{want:.0f}")
    if m_fan and fan is not None:
        want = float(m_fan.group(1))
        if abs(fan - want) > FAN_TOL_PCT:
            probs.append(f"the label says fan={want:.0f} but the GPU reports {fan:.0f}%: the fan speed was not applied "
                         "(set a fixed speed in your fan tool and wait until it shows it)")
    if m_fan and kind != "idle" and pw is not None and lim and pw >= 0.98 * lim:
        probs.append(f"power is at the GPU's limit ({pw:.0f} of {lim:.0f} W): at the limit power cannot rise with "
                     "temperature, so this point cannot measure leakage. Lock a lower clock")
    return probs


def run_session(kind: str, seconds: float, out_root: str | Path, label: str = "", gpu: int = 0,
                interval_s: float = 0.1, idle_before_s: float = 0.0, nvml=None,
                workload: Callable[[float], float] | None = None, guard: bool = True,
                guard_after_s: float = 30.0) -> Path:
    """Record one calibration session. `nvml` and `workload` can be injected for tests.
    Everything that can fail before measuring (PyTorch, NVML) is checked before the session
    folder exists, so a failed start leaves nothing behind.

    Guard (on by default): `guard_after_s` into the run, recent telemetry is compared with the label
    (clk=, fan=; see guard_problems). If the GPU is not in the promised state the run stops at once,
    the session is kept and marked incomplete (session.json "guard_failed"), and GuardError is raised,
    so a mistake costs half a minute instead of the whole procedure. Read-only: nothing is changed."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    safe = "".join(ch if ch.isalnum() or ch in "-_.=" else "_" for ch in label)[:40]
    d = Path(out_root) / f"{stamp}_{kind}{'_' + safe if safe else ''}"
    if d.exists():
        raise FileExistsError(d)
    step = workload or (idle_workload() if kind == "idle" else torch_workload(kind, gpu))
    try:
        log = Logger(d / "telemetry.csv", interval_s=interval_s, gpus=[gpu], nvml=nvml, label="idle")
    except Exception:
        if d.exists() and not any(d.iterdir()):
            d.rmdir()
        raise
    problems: list[str] = []
    log.start()
    try:
        if idle_before_s > 0:
            time.sleep(idle_before_s)
        log.set_label(kind)
        rows = []
        t0 = time.time()
        t_end = t0 + seconds
        checked = not guard
        while time.time() < t_end:
            thr = step(min(0.5, max(0.05, t_end - time.time())))
            rows.append((time.time(), thr))
            if not checked and time.time() - t0 >= min(guard_after_s, 0.5 * seconds):
                checked = True
                recent = [r for r in list(log.recent) if r.get("label") == kind][-50:]
                problems = guard_problems(recent, label, kind)
                if problems:
                    break
        log.set_label("done")
        time.sleep(min(1.0, interval_s * 5))
    finally:
        meta = log.stop()
    with open(d / "workload.csv", "w") as f:
        f.write("t_unix,throughput\n")
        for t, v in rows:
            f.write(f"{t:.6f},{v:.6g}\n")
    unit = {"memory": "GB/s", "idle": "-"}.get(kind, "TFLOP/s")
    failed = problems or None
    (d / "session.json").write_text(json.dumps({
        "kind": kind, "label": label, "seconds": seconds, "gpu": gpu, "throughput_unit": unit,
        "idle_before_s": idle_before_s, "device": meta["devices"][0], "telemetry_sha256": meta["csv_sha256"],
        "provenance": "physical_measurement", **({"guard_failed": failed} if failed else {})}, indent=1))
    if failed:
        raise GuardError(d, failed)
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
    guard_failed: list[str] | None = None  # set when the run stopped itself early (incomplete session)


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
                   read_csv(d / "telemetry.csv"), work, meta["device"].get("power_limit_W"), meta["device"],
                   meta.get("guard_failed"))


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
            "energy_per_work": float(np.median(pw) / np.median(work[:, 1])) if np.median(work[:, 1]) > 0 else None,
            "power_limit_W": (lim_w := _median_or(tel, "power_limit_W", sess.power_limit_W)),
            "at_power_limit": bool(lim_w and float(np.median(pw)) >= 0.98 * lim_w),
            "device": device_label(sess.device), "device_key": device_key(sess.device),
            "nvml_max_clock_MHz": sess.max_clock}


def _median_or(rows: list[dict], key: str, default):
    v = [r.get(key) for r in rows if r.get(key) is not None]
    return float(np.median(v)) if v else default


def flag_without_limit(sm: dict[str, Any]) -> bool:
    """True when the driver set a limit flag but the measurements show no limit: the locked clock
    held (within CLOCK_HELD_TOL) and power stayed below 90% of the limit. Seen on an RTX 5070,
    2026-10-26: the power-cap flag at 87 W of 250 W at every locked clock below 2.4 GHz, and no
    flag while the card actually sat at its 250 W limit."""
    lc, lim, p95 = sm.get("label_clock_MHz"), sm.get("power_limit_W"), sm.get("power_p95_W")
    return bool(lc and lim and p95 and abs(sm["clock_MHz"] - lc) / lc <= CLOCK_HELD_TOL and p95 < 0.9 * lim)


def interpret_limits(sm: dict[str, Any]) -> list[str]:
    """Plain-language reading of which limit held the clock down. Inferences are worded as such."""
    out = []
    reasons = sm.get("limit_reasons") or {}
    if reasons and flag_without_limit(sm):
        return [f"driver flags set ({', '.join(reasons)}) although the locked clock held and power stayed at "
                f"{100 * sm['power_p95_W'] / sm['power_limit_W']:.0f}% of the limit: not a limit. On some GPUs the "
                "power-cap flag is set whenever clocks are locked"]
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


def _at_bounds(popt, lo, hi, names, scale) -> list[str]:
    """Parameters that ended within 0.1% of a bound of the allowed range (span, or `scale` if open)."""
    out = []
    for p_, l_, h_, n_ in zip(popt, lo, hi, names):
        span = (h_ - l_) if np.isfinite(h_) else scale
        if p_ - l_ <= 1e-3 * span or (np.isfinite(h_) and h_ - p_ <= 1e-3 * span):
            out.append(n_)
    return out


def _r2(y, yhat) -> float:
    y = np.asarray(y, float)
    ss = float(((y - y.mean()) ** 2).sum())
    return 1.0 - float(((y - yhat) ** 2).sum()) / ss if ss > 0 else float("nan")


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
    lo, hi = [0, 0, 0.3], [np.inf, np.inf, 1.0]
    popt, pcov = curve_fit(_power_model, s, P, p0=p0, bounds=(lo, hi), maxfev=20000)
    se = np.sqrt(np.diag(pcov))
    fit = _power_model(s, *popt)
    order = np.argsort(s)
    return {"ok": True, "A_W": float(popt[0]), "P_dyn_W": float(popt[1]), "v_min_ratio": float(popt[2]),
            "v_min_ratio_se": float(se[2]), "n": len(pts), "excluded_s": excluded,
            "s_range": [float(s.min()), float(s.max())],
            "at_bound": _at_bounds(popt, lo, hi, ["A_W", "P_dyn_W", "v_min_ratio"], float(P.max())),
            "r2": _r2(P, fit), "rms_resid_W": float(np.sqrt(np.mean((P - fit) ** 2))),
            "points": [{"s": float(s[i]), "P_W": float(P[i]), "fit_W": float(fit[i])} for i in order],
            "method": "P = A + P_d * s * v(s)^2 with v linear between s_min = 0.5 and 1 (registry form); "
                      "temperature differences between sessions are not removed"}


def _leak_model(T, c, L, kappa):
    return c + L * np.exp(kappa * (np.asarray(T) - T_REF))


def _slope(T, P) -> dict[str, Any] | None:
    if len(T) < 30 or T.max() - T.min() < 2.0:
        return None
    (b, a), se, _ = _linfit(T, P)
    return {"dPdT_W_per_K": float(b), "se": float(se[0]), "T_range_C": [float(T.min()), float(T.max())],
            "P_mean_W": float(P.mean()), "rel_per_K": float(b / P.mean()), "n": int(len(T))}


def fit_leakage(sess: Session, clock_tol_MHz: float = 3.0, load_tol: float = 0.02) -> dict[str, Any]:
    """Leakage from a warm-up at constant clock, load and (where recorded) fan speed.

    Samples are kept only at ONE reported clock step (within clock_tol_MHz of the most common clock;
    both RTX 5070 warm-ups dropped one 7-8 MHz step as they warmed, with a 4 W power step) and while
    workload throughput is within load_tol of its median (rule added after the first desktop warm-up
    showed a 4-10% throughput drop). The exponential model needs a wide temperature range to separate
    leakage power from its temperature coefficient; over a few kelvin only the local slope dP/dT is
    identified, so the slope is always reported, also with the fan held at its most common speed."""
    tel, work = steady(sess, skip_s=2.0)
    if len(tel) < 30:
        return {"ok": False, "reason": "too few samples in warm-up session"}
    clk = np.array([r["sm_clock_MHz"] for r in tel], dtype=float)
    vals, counts = np.unique(np.round(clk), return_counts=True)
    clk_mode = float(vals[np.argmax(counts)])
    keep = np.abs(clk - clk_mode) <= clock_tol_MHz
    n_clock_excluded = int((~keep).sum())
    n_load_excluded = 0
    if len(work) >= 3:
        ts = np.array([r["t_unix"] for r in tel])
        idx = np.clip(np.searchsorted(work[:, 0], ts), 0, len(work) - 1)
        rel = work[idx, 1] / np.median(work[:, 1]) - 1.0
        steady_load = np.abs(rel) <= load_tol
        n_load_excluded = int((keep & ~steady_load).sum())
        keep &= steady_load
    T = np.array([r["temp_C"] for r in tel], dtype=float)[keep]
    P = np.array([r["power_W"] for r in tel], dtype=float)[keep]
    F = np.array([np.nan if r.get("fan_pct") is None else r["fan_pct"] for r in tel], dtype=float)[keep]
    base = {"clock_MHz": clk_mode, "n_clock_excluded": n_clock_excluded, "n_load_excluded": n_load_excluded,
            "temp_resolution_C": 1.0 if len(T) and np.all(T == np.round(T)) else None,
            "slope": _slope(T, P), "fan_pct_range": _range_or_none(list(F[np.isfinite(F)])) if len(F) else None}
    if np.isfinite(F).any():
        fv, fc = np.unique(F[np.isfinite(F)], return_counts=True)
        fm = np.abs(F - fv[np.argmax(fc)]) <= 1.0
        base["slope_const_fan"] = _slope(T[fm], P[fm])
    if len(T) < 30:
        return {**base, "ok": False, "reason": f"too few samples at constant clock and load ({len(T)})"}
    if T.max() - T.min() < 8.0:
        return {**base, "ok": False, "reason": f"temperature rose only {T.max() - T.min():.1f} K at constant clock "
                                               "and load; need >= 8 K, and far more to separate leakage from its "
                                               "temperature coefficient"}
    p0 = (np.min(P) * 0.8, np.min(P) * 0.2, 0.02)
    lo, hi = [0, 0, 0], [np.inf, np.inf, 0.2]
    popt, pcov = curve_fit(_leak_model, T, P, p0=p0, bounds=(lo, hi), maxfev=20000)
    se = np.sqrt(np.diag(pcov))
    c, L, k = popt
    resid = P - _leak_model(T, *popt)
    at_bound = _at_bounds(popt, lo, hi, ["c_W", "L_ref_W", "kappa"], float(P.max()))
    sl = base["slope"] or {"dPdT_W_per_K": float("nan"), "se": float("nan")}
    return {**base, "ok": True, "kappa": float(k), "kappa_se": float(se[2]), "L_ref_W": float(L),
            "L_ref_se": float(se[1]), "c_W": float(c), "leak_fraction_at_ref": float(L / (c + L)), "n": int(len(T)),
            "T_range_C": [float(T.min()), float(T.max())], "P_range_W": [float(P.min()), float(P.max())],
            "resid_std_W": float(resid.std()), "at_bound": at_bound, "r2": _r2(P, _leak_model(T, *popt)),
            "dPdT_W_per_K": sl["dPdT_W_per_K"], "dPdT_se": sl["se"],
            "method": "P(T) = c + L*exp(kappa*(T-60)) at one clock step and constant load during warm-up; assumes "
                      "the temperature-dependent part of board power is leakage (fan and VR losses not separated)"}


# ------------------------------------------------------------------- M003: fan-sweep leakage
THERMAL_BITS = LIMIT_REASONS["sw_thermal"][0] | LIMIT_REASONS["hw_thermal"][0] | LIMIT_REASONS["hw_slowdown"][0]
_FAN_RE = re.compile(r"fan=(\d+)")


def sweep_point(sess: Session, settle_frac: float = 0.5, clock_tol_MHz: float = 3.0,
                load_tol: float = 0.02) -> dict[str, Any]:
    """Steady state of one fan-sweep session: the last `settle_frac` of the run, at one clock step and
    (for load sessions) steady throughput. Temperature drift over that window is reported; the fit
    leaves a point out if the window was not settled (drift > 1 K across it) or a thermal limit acted."""
    tel, work = steady(sess, skip_s=0.0)
    lab_fan = _FAN_RE.search(sess.label or "")
    base = {"name": sess.path.name, "kind": sess.kind, "label": sess.label,
            "label_fan_pct": float(lab_fan.group(1)) if lab_fan else None}
    if len(tel) < 30:
        return {**base, "ok": False, "reason": "too few samples"}
    t_all = np.array([r["t_unix"] for r in tel])
    tc = t_all[0] + (1.0 - settle_frac) * (t_all[-1] - t_all[0])
    tel = [r for r in tel if r["t_unix"] >= tc]
    work = work[work[:, 0] >= tc] if len(work) else work
    t = np.array([r["t_unix"] for r in tel])
    clk = np.array([r["sm_clock_MHz"] for r in tel], dtype=float)
    keep = np.ones(len(tel), dtype=bool)
    if sess.kind != "idle":
        vals, counts = np.unique(np.round(clk), return_counts=True)
        keep &= np.abs(clk - float(vals[np.argmax(counts)])) <= clock_tol_MHz
        if len(work) >= 3:
            idx = np.clip(np.searchsorted(work[:, 0], t), 0, len(work) - 1)
            keep &= np.abs(work[idx, 1] / np.median(work[:, 1]) - 1.0) <= load_tol
    if keep.sum() < 20:
        return {**base, "ok": False, "reason": f"only {int(keep.sum())} samples at one clock step and steady load"}
    P = np.array([r["power_W"] for r in tel], dtype=float)[keep]
    T = np.array([r["temp_C"] for r in tel], dtype=float)[keep]
    F = np.array([np.nan if r.get("fan_pct") is None else r["fan_pct"] for r in tel], dtype=float)[keep]
    reasons = [int(r["clock_event_reasons"]) for r, k in zip(tel, keep) if k and r.get("clock_event_reasons") is not None]
    tk = t[keep]
    drift = float(np.polyfit((tk - tk[0]) / 60.0, T, 1)[0]) if np.ptp(T) > 0 else 0.0   # K/min; flat at 1 C resolution
    window_min = float((tk[-1] - tk[0]) / 60.0)
    fan = float(np.nanmedian(F)) if np.isfinite(F).any() else base["label_fan_pct"]
    lim = [r.get("power_limit_W") for r in tel if r.get("power_limit_W") is not None] or \
        ([sess.power_limit_W] if sess.power_limit_W else [])
    lim_W = float(np.median(lim)) if lim else None
    return {**base, "ok": True, "n": int(keep.sum()), "clock_MHz": float(np.median(clk[keep])),
            "power_limit_W": lim_W, "at_power_limit": bool(lim_W and float(np.median(P)) >= 0.98 * lim_W),
            "guard_failed": sess.guard_failed,
            "fan_pct": fan, "fan_source": "telemetry" if np.isfinite(F).any() else ("label" if fan is not None else None),
            "P_W": float(P.mean()), "P_se": float(P.std(ddof=1) / np.sqrt(len(P))),
            "T_C": float(T.mean()), "T_drift_K_per_min": float(drift), "window_min": window_min,
            "settled": bool(abs(drift) * window_min <= 1.0),
            "thermal_flag_frac": float(np.mean([(x & THERMAL_BITS) != 0 for x in reasons])) if reasons else None}


def _ols(x, y) -> dict[str, Any]:
    from scipy import stats
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    b, a = np.polyfit(x, y, 1)
    out = {"slope_W_per_K": float(b), "intercept_W": float(a), "n": n, "T_range_C": [float(x.min()), float(x.max())],
           "P_mean_W": float(y.mean()), "rel_per_K": float(b / y.mean())}
    if n >= 3:
        resid = y - (a + b * x)
        se = float(np.sqrt(resid @ resid / (n - 2) / ((x - x.mean()) @ (x - x.mean()))))
        tq = float(stats.t.ppf(0.975, n - 2))
        out.update({"se": se, "ci95": [float(b - tq * se), float(b + tq * se)],
                    "rel_ci95": [float((b - tq * se) / y.mean()), float((b + tq * se) / y.mean())]})
    return out


def fit_leakage_sweep(session_dirs: Iterable[str | Path], device: str | None = None) -> dict[str, Any]:
    """Leakage slope dP/dT from steady states at several FIXED fan speeds, one locked clock, constant load
    (M003). Changing the fan moves the die temperature by tens of kelvin at constant clock and work, a much
    wider window than one warm-up (M002: 4 K). Board power includes the fans, and faster fans mean cooler
    chips, so fan power biases the raw slope downward. Idle sessions at the same fan settings measure that
    power: P_corr = P_load - (P_idle(fan) - P_idle(lowest load fan)). The idle sessions' own leakage change
    with temperature is folded into the correction (a slight over-correction, reported as the idle
    temperature range). Only sessions whose label contains "fan=" take part."""
    sessions = [load_session(d) for d in session_dirs]
    sessions = [x for x in sessions if _FAN_RE.search(x.label or "")]
    sessions, notes = select_device(sessions, device)
    loads = [sweep_point(x) for x in sessions if x.kind == "compute"]
    idles = [sweep_point(x) for x in sessions if x.kind == "idle"]
    excluded = [{"name": p["name"], "reason": p["reason"]} for p in loads + idles if not p["ok"]]
    loads, idles = [p for p in loads if p["ok"]], [p for p in idles if p["ok"]]
    for p in list(loads) + list(idles):          # problems that make a point meaningless, whatever the clock
        why = []
        if p.get("guard_failed"):
            why.append("stopped early: " + p["guard_failed"][0])
        if p["fan_source"] == "telemetry" and p["label_fan_pct"] is not None and abs(p["fan_pct"] - p["label_fan_pct"]) > FAN_TOL_PCT:
            why.append(f"fan reported {p['fan_pct']:.0f}% but labelled {p['label_fan_pct']:.0f}%: the fan setting was not applied")
        if p["kind"] != "idle" and p.get("at_power_limit"):
            why.append(f"power at the GPU's limit ({p['P_W']:.0f} W): the clock lock was not holding power below the limit, "
                       "so power cannot rise with temperature")
        if why:
            excluded.append({"name": p["name"], "reason": "; ".join(why)})
            (loads if p in loads else idles).remove(p)
    if loads:
        clocks = np.array([p["clock_MHz"] for p in loads])
        vals, counts = np.unique(np.round(clocks), return_counts=True)
        c0 = float(vals[np.argmax(counts)])
        for p in loads:
            if abs(p["clock_MHz"] - c0) > 3.0:
                excluded.append({"name": p["name"], "reason": f"clock {p['clock_MHz']:.0f} MHz, not the sweep's {c0:.0f} MHz"})
        loads = [p for p in loads if abs(p["clock_MHz"] - c0) <= 3.0]
    for p in list(loads):
        why = []
        if not p["settled"]:
            why.append(f"not settled ({p['T_drift_K_per_min']:+.2f} K/min over the last {p['window_min']:.1f} min)")
        if (p["thermal_flag_frac"] or 0) > 0.05:
            why.append(f"thermal limit active {100 * p['thermal_flag_frac']:.0f}% of the time")
        if p["fan_pct"] is None:
            why.append("fan speed unknown (not reported and not in the label)")
        if why:
            excluded.append({"name": p["name"], "reason": "; ".join(why)})
            loads.remove(p)
    out = {"kind": "ueic_leakage_sweep", "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "device": device_label(sessions[0].device) if sessions else None, "points": loads, "idle_points": idles,
           "excluded": excluded, "notes": notes,
           "method": "OLS of steady-state board power on die temperature across fixed fan speeds at one locked clock "
                     "and constant compute load; fan power removed with idle sessions at the same fan speeds"}
    if len(loads) < 3:
        return {**out, "ok": False, "reason": f"{len(loads)} usable load points; need at least 3 fan speeds"}
    T = np.array([p["T_C"] for p in loads])
    P = np.array([p["P_W"] for p in loads])
    fans = np.array([p["fan_pct"] for p in loads])
    out["clock_MHz"] = float(np.median([p["clock_MHz"] for p in loads]))
    out["fit_uncorrected"] = _ols(T, P)
    if len(idles) >= 2:
        idf = np.array([p["fan_pct"] for p in idles], dtype=float)
        order = np.argsort(idf)
        idf, idp = idf[order], np.array([p["P_W"] for p in idles])[order]
        outside = [f for f in fans if f < idf[0] - 3 or f > idf[-1] + 3]
        corr = np.interp(fans, idf, idp) - float(np.interp(fans.min(), idf, idp))
        out["fan_power_W"] = {"at_fan_pct": [float(f) for f in fans], "correction_W": [float(c) for c in corr],
                              "idle_T_range_C": _range_or_none([p["T_C"] for p in idles])}
        if outside:
            out["notes"].append(f"load fan speeds {sorted(set(outside))} lie outside the idle sessions' range; "
                                "their fan-power correction is the nearest idle value")
        out["fit"] = _ols(T, P - corr)
        out["fit_basis"] = "fan-power corrected"
    else:
        out["fit"] = out["fit_uncorrected"]
        out["fit_basis"] = "uncorrected (fewer than 2 idle sessions): a lower bound if fan power rises with fan speed"
        out["notes"].append("no fan-power correction: record idle sessions at the same fan speeds")
    if T.max() - T.min() < 8.0:
        out["notes"].append(f"temperature window only {T.max() - T.min():.1f} K; aim for 15 K or more")
    return {**out, "ok": True}


def plan_leakage_sweep(clock_MHz: int, fans: list[int], gpu: int = 0, seconds: int = 480, idle_seconds: int = 150) -> str:
    """Commands for the USER to review and run (M003). UEIC never changes clocks or fan speeds itself."""
    fs = sorted(fans, reverse=True)
    lines = ["# M003 leakage sweep: steady power at several FIXED fan speeds, one locked clock, constant load.",
             "# Review before running. One Administrator PowerShell with the virtual environment active.",
             "# UEIC only records. YOU set the clock (nvidia-smi) and the fan speed (your card maker's tool,",
             "# e.g. MSI Afterburner: fixed fan curve / manual speed). The GPU's own thermal protection stays on.",
             "# Safety: start at the highest fan speed and step down; do not go below your card's minimum; stop",
             "# and restore automatic fan control if the GPU passes 85 C. Close other GPU and heavy CPU work.",
             f"# If you stop partway: nvidia-smi -i {gpu} -rgc  and restore automatic fan control.",
             f"python -m ueic calib check --gpu {gpu}",
             f"nvidia-smi -i {gpu} -lgc {clock_MHz},{clock_MHz}    # must print 'GPU clocks set to ...'; needs Administrator", "",
             f"# 1) Load at each fan speed ({seconds // 60} min each; only the last half is used, once settled)."]
    lines += ["#    Each step below pauses (Read-Host) until you press Enter, so pasting the whole block is safe.",
              "#    Each run checks itself after 30 s and stops with an ERROR if the clock lock or fan speed is",
              "#    not what its label says. If that happens, fix it and run that step again."]
    for f in fs:
        lines += [f"Read-Host \"Set the fan to {f}% in your fan tool, wait until it shows {f}%, then press Enter\"",
                  f"python -m ueic calib run --kind compute --seconds {seconds} --gpu {gpu} --label \"sweep fan={f} clk={clock_MHz}\""]
    lines += ["", f"# 2) Idle at the same fan speeds ({idle_seconds // 60} min each), to measure the fans' own power.",
              "#    Clocks back to default first, so the idle chip sits at its lowest clock and voltage and its",
              "#    own leakage barely changes between fan speeds.",
              f"nvidia-smi -i {gpu} -rgc    # reset clocks"]
    for f in fs:
        lines += [f"Read-Host \"Set the fan to {f}%, wait until it shows {f}%, then press Enter\"",
                  f"python -m ueic calib run --kind idle --seconds {idle_seconds} --gpu {gpu} --label \"sweep fan={f}\""]
    lines += ["", "# restore automatic fan control in your fan tool", "",
              "python -m ueic calib leak data\\calibration\\* --out data\\calibration\\M003_leakage_sweep.json"]
    return "\n".join(lines)


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
    loaded = [load_session(d) for d in session_dirs]
    stopped = [s for s in loaded if s.guard_failed]
    sweep = [s for s in loaded if (s.kind == "idle" or _FAN_RE.search(s.label or "")) and s not in stopped]
    sessions, device_notes = select_device([s for s in loaded if s not in sweep and s not in stopped], device)
    if sweep:
        device_notes.append(f"left out {len(sweep)} fan-sweep session(s) (labels with fan=, or idle); "
                            "`calib leak` fits those")
    if stopped:
        device_notes.append(f"left out {len(stopped)} session(s) that stopped themselves early: "
                            + "; ".join(f"{s.path.name}: {s.guard_failed[0]}" for s in stopped))
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
    spurious: list[dict] = []
    for x in summ:
        if not x["ok"]:
            notes.append(f"{x['path']}: skipped ({x['reason']})")
            continue
        lc = x.get("label_clock_MHz")
        if lc and abs(x["clock_MHz"] - lc) / lc > CLOCK_HELD_TOL:
            notes.append(f"{x['name']}: locked at {lc:.0f} MHz but ran at {x['clock_MHz']:.0f} MHz (median); the "
                         "lock was not held. Fits use the measured clock")
        if x.get("limited_frac") is not None and x["limited_frac"] > 0.10:
            if flag_without_limit(x):
                spurious.append(x)
                continue
            which = ", ".join(f"{LIMIT_REASONS[k][1].split(' (')[0]} {100 * v:.0f}%"
                              for k, v in sorted(x["limit_reasons"].items(), key=lambda kv: -kv[1]))
            notes.append(f"{x['name']}: clock held down by a limit in {100 * x['limited_frac']:.0f}% of samples "
                         f"({which})")
    if spurious:
        worst = max(x["power_p95_W"] / x["power_limit_W"] for x in spurious)
        notes.append(f"the driver set a limit flag in {len(spurious)} session(s) although each locked clock held "
                     f"(within {100 * CLOCK_HELD_TOL:.0f}%) and power stayed at or below {100 * worst:.0f}% of the "
                     "limit; the flag does not indicate a limit on this GPU and was not treated as one")
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
    cands = []
    if fb_c["ok"]:
        cands.append({"name": "beta_compute", "value": fb_c["value"], "se": fb_c["se"], "evidence": "B", "at_bound": []})
    if fb_m["ok"]:
        cands.append({"name": "beta_memory", "value": fb_m["value"], "se": fb_m["se"], "evidence": "B", "at_bound": []})
    if fp["ok"]:
        cands.append({"name": "v_min_ratio", "value": fp["v_min_ratio"], "se": fp["v_min_ratio_se"], "evidence": "B",
                      "at_bound": fp["at_bound"]})
    if fl["ok"]:
        f = fl["leak_fraction_at_ref"]
        scaled = f / (1 - f) * (cfg.p_dyn_max + cfg.p_static_other) if f < 1 else float("inf")
        cands.append({"name": "kappa_leak", "value": fl["kappa"], "se": fl["kappa_se"], "evidence": "B",
                      "at_bound": fl["at_bound"]})
        cands.append({"name": "p_leak_ref", "value": float(scaled), "se": None, "evidence": "E", "at_bound": [],
                      "derived_from": "kappa_leak",
                      "note": f"measured leak fraction {f:.3f} at 60 C scaled to the simulated accelerator"})
    out["overrides"], out["rejected"] = accept_estimates(cands)
    out["energy_per_work"] = energy_curves(summ)
    for k, v in out["overrides"].items():
        from .params import REGISTRY
        lo, hi = REGISTRY[k].low, REGISTRY[k].high
        if lo is not None and not lo <= v["value"] <= hi:
            notes.append(f"{k} = {v['value']} lies outside the registry range [{lo}, {hi}] swept in E002")
    # every transferred value must yield a valid configuration
    make_config({k: v["value"] for k, v in out["overrides"].items()})
    return out


def energy_curves(summ: list[dict]) -> dict[str, Any]:
    """Model-free result: measured board energy per unit of work at each clock (J/TFLOP for the
    compute kernel, J/GB for the memory kernel), normalised to the highest clock."""
    out: dict[str, Any] = {}
    for kind, unit in (("compute", "J/TFLOP"), ("memory", "J/GB")):
        pts = sorted((x for x in summ if x["kind"] == kind and x["ok"] and x.get("energy_per_work")),
                     key=lambda x: x["clock_MHz"])
        if len(pts) < 2:
            continue
        top = pts[-1]
        rows = [{"clock_MHz": x["clock_MHz"], "s": x.get("s"), "power_W": x["power_W"], "temp_C": x["temp_C"],
                 "throughput": x["throughput"], "energy_per_work": x["energy_per_work"],
                 "energy_rel_top": x["energy_per_work"] / top["energy_per_work"],
                 "power_rel_top": x["power_W"] / top["power_W"]} for x in pts]
        best = min(rows, key=lambda r: r["energy_per_work"])
        out[kind] = {"unit": unit, "points": rows, "min_at_clock_MHz": best["clock_MHz"], "min_at_s": best["s"],
                     "saving_vs_top": 1.0 - best["energy_rel_top"]}
    return out


PHYSICAL = {"beta_compute": (0.0, 1.0), "beta_memory": (0.0, 1.0), "v_min_ratio": (0.0, 1.0),
            "kappa_leak": (0.0, float("inf")), "p_leak_ref": (0.0, float("inf"))}
ROUND = {"beta_compute": 4, "beta_memory": 4, "v_min_ratio": 4, "kappa_leak": 5, "p_leak_ref": 2}


def accept_estimates(cands: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Decide which fitted values may be transferred to the simulator. Rules (set on 2026-10-26,
    after the first desktop fit summary was seen and before its raw telemetry was examined):
      R1 boundary  - a fit that ended at an edge of its allowed parameter range is rejected: the
                     model did not describe the data.
      R2 precision - a value whose 95% CI half-width (1.96 se) exceeds the width of the registry
                     range it would replace is rejected: it adds no information beyond E002.
      R3 physical  - a value outside its physical range is moved to that limit when its 95% CI
                     reaches the limit, and rejected otherwise.
    A derived value (p_leak_ref) is accepted only if the value it is derived from is accepted.
    Rejected values are kept in the record with the reason."""
    from .params import REGISTRY
    acc: dict[str, Any] = {}
    rej: dict[str, Any] = {}
    for c in cands:
        k, v, se = c["name"], float(c["value"]), c["se"]
        base = {"value": round(v, ROUND[k]), "se": se, "evidence": c["evidence"]}
        if c.get("note"):
            base["note"] = c["note"]
        if c.get("derived_from"):
            continue
        if c["at_bound"]:
            rej[k] = {**base, "reason": "fit ended at the edge of its allowed range (" + ", ".join(c["at_bound"]) +
                      "): the model does not describe these data"}
            continue
        if se is None or not np.isfinite(se):
            rej[k] = {**base, "reason": "no standard error (too few points for the number of fitted parameters)"}
            continue
        lo, hi = REGISTRY[k].low, REGISTRY[k].high
        if lo is not None and 1.96 * se > hi - lo:
            rej[k] = {**base, "reason": f"95% CI half-width {1.96 * se:.3g} is wider than the registry range "
                                        f"[{lo}, {hi}] it would replace"}
            continue
        plo, phi = PHYSICAL[k]
        if v < plo or v > phi:
            limit = plo if v < plo else phi
            if abs(v - limit) <= 1.96 * se:
                acc[k] = {**base, "value": limit, "measured": round(v, ROUND[k]), "status": "at physical limit",
                          "note": f"measured {v:.4g} +/- {1.96 * se:.2g} (95% CI) reaches the physical limit {limit:g}; "
                                  "transferred at the limit"}
            else:
                rej[k] = {**base, "reason": f"outside the physical range [{plo:g}, {phi:g}] beyond its 95% CI"}
            continue
        acc[k] = {**base, "status": "accepted"}
    for c in cands:
        if c.get("derived_from"):
            k = c["name"]
            base = {"value": round(float(c["value"]), ROUND[k]), "se": None, "evidence": c["evidence"],
                    "note": c.get("note")}
            if c["derived_from"] in acc:
                acc[k] = {**base, "status": "accepted"}
            else:
                rej[k] = {**base, "reason": f"derived from {c['derived_from']}, which was rejected"}
    return acc, rej


def apply_calibration(spec: dict[str, Any], calib: dict[str, Any], calib_sha256: str) -> dict[str, Any]:
    """New spec whose every cell uses the calibrated values; provenance travels with the spec."""
    spec = json.loads(json.dumps(spec))
    over = {k: v["value"] for k, v in calib["overrides"].items()}
    if not over:
        raise ValueError("the calibration has no accepted values to transfer")
    spec["design"]["param_overrides"] = {**spec["design"].get("param_overrides", {}), **over}
    spec["key"] = spec["key"] + "C"
    spec["title"] = spec["title"] + " (calibrated)"
    spec["calibration_source"] = {"sha256": calib_sha256, "device": calib.get("device"), "overrides": calib["overrides"],
                                  "rejected": calib.get("rejected", {})}
    return spec


def ingest(store, calib: dict[str, Any], calib_sha256: str, key: str = "M001", title: str | None = None) -> str:
    """Record a calibration as a measurement experiment in the append-only store."""
    spec = {
        "key": key, "title": title or f"GPU calibration measurement ({(calib.get('device') or {}).get('name', 'unknown GPU')})",
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
    notes = list(calib.get("notes", []))
    for k, v in calib["overrides"].items():
        prov = "physical_measurement" if v["evidence"] == "B" else "engineering_assumption"
        metrics[k] = (float(v["value"]), "-", prov)
        if v.get("se") is not None:
            metrics[k + "_se"] = (float(v["se"]), "-", prov)
        if "measured" in v:
            metrics[k + "_measured"] = (float(v["measured"]), "-", prov)
            notes.append(f"{k}: {v['note']}")
    fl = (calib.get("fits") or {}).get("leakage") or {}
    for tag, key in (("", "slope"), ("_const_fan", "slope_const_fan")):
        sl = fl.get(key)
        if sl:
            metrics[f"leak_dPdT{tag}_W_per_K"] = (sl["dPdT_W_per_K"], "W/K", "physical_measurement")
            metrics[f"leak_dPdT{tag}_se"] = (sl["se"], "W/K", "physical_measurement")
            metrics[f"leak_dPdT{tag}_rel_per_K"] = (sl["rel_per_K"], "1/K", "physical_measurement")
            notes.append(f"leakage slope{tag.replace('_', ' ')}: {sl['dPdT_W_per_K']:.3f} +/- {1.96 * sl['se']:.3f} W/K "
                         f"over {sl['T_range_C'][0]:.0f}-{sl['T_range_C'][1]:.0f} C at {fl.get('clock_MHz', float('nan')):.0f} MHz, "
                         f"{sl['P_mean_W']:.0f} W")
    # failures are preserved: rejected estimates are recorded, labelled, with the reason
    for k, v in calib.get("rejected", {}).items():
        prov = "physical_measurement" if v["evidence"] == "B" else "engineering_assumption"
        metrics[k + "_rejected"] = (float(v["value"]), "-", prov)
        if v.get("se") is not None and np.isfinite(v["se"]):
            metrics[k + "_rejected_se"] = (float(v["se"]), "-", prov)
        notes.append(f"{k} rejected (not transferred): {v['reason']}")
    store.finish_run(run_id, metrics, notes, None)
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
    cs = sorted(clocks_MHz)
    warm = cs[-2] if len(cs) >= 2 else cs[0]   # high power for a wide temperature rise, but below the power limit
    lines += ["# 1) Leakage warm-up at one locked clock: 10 min idle to cool down, then 15 min of steady load.",
              "#    For a usable measurement the temperature must rise well over 10 K at constant fan power: if your",
              "#    card lets you, fix the fan at a constant speed (card maker's tool) for this step, keep other GPU",
              "#    and heavy CPU work off, and restore automatic fan control afterwards. Stop if it passes 85 C.",
              f"nvidia-smi -i {gpu} -lgc {warm},{warm}",
              f"python -m ueic calib run --kind warmup --seconds 900 --idle-before 600 --gpu {gpu} --label clk={warm}",
              "# 2) Clock sweep: compute-bound and memory-bound kernels at each clock."]
    for c in clocks_MHz:
        lines += [f"nvidia-smi -i {gpu} -lgc {c},{c}",
                  f"python -m ueic calib run --kind compute --seconds {seconds} --gpu {gpu} --label clk={c}",
                  f"python -m ueic calib run --kind memory --seconds {seconds} --gpu {gpu} --label clk={c}"]
    lines += [f"nvidia-smi -i {gpu} -rgc    # reset clocks to default", "",
              "python -m ueic calib fit data\\calibration\\* --out data\\calibration\\calibration.json"]
    return "\n".join(lines)
