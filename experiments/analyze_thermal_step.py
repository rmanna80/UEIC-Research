"""Stage 2: fast thermal response of the RTX 5070 from the two warm-up sessions (M001 warm-up, M002).

Each warm-up idles, then switches to a constant compute load at a locked clock: a power step of ~100-140 W.
The fans were off for the first ~25 s of load in both sessions (automatic fan control), so the first 20 s are
a clean step response of the die and heatsink at zero fan speed. Fitted: T(t) = T0 + A(1 - exp(-t/tau)) + B t.

Evidence class B on this card only (air cooler, consumer board); transferring the numbers to the simulated
liquid-cooled accelerator would be class E. NVML temperatures are whole degrees, one step per session.
Usage:  python experiments/analyze_thermal_step.py  ->  data/calibration/M001_M002_thermal_step.json
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ueic.calibrate import load_session  # noqa: E402
from ueic.models.system_identification import fit_step_response  # noqa: E402

SESSIONS = {"M001 warm-up (2002 MHz)": "20261026T204001_warmup_clk=2017",
            "M002 warm-up (2340 MHz)": "20261026T214252_warmup_clk=2347"}
out = {"kind": "ueic_thermal_step_fit", "evidence": "B on the measured card (RTX 5070, air-cooled); class E if transferred",
       "fits": {}}
for name, folder in SESSIONS.items():
    s = load_session(ROOT / "data" / "calibration" / folder)
    tel = [r for r in s.tel if r["power_W"] is not None and r["temp_C"] is not None]
    t = np.array([r["t_unix"] for r in tel])
    lab = [r["label"] for r in tel]
    i0 = lab.index("warmup")
    t = t - t[i0]
    T = np.array([r["temp_C"] for r in tel], dtype=float)
    P = np.array([r["power_W"] for r in tel], dtype=float)
    F = np.array([np.nan if r.get("fan_pct") is None else r["fan_pct"] for r in tel], dtype=float)
    P_idle = float(np.median(P[(t > -30) & (t < 0)]))
    P_load = float(np.median(P[(t > 2) & (t < 20)]))
    fan_on = t[(t > 0) & (F > 0)]
    t_fit = min(20.0, float(fan_on[0]) - 0.5) if fan_on.size else 20.0     # stop before the fans start
    fit = fit_step_response(t, T, P_load - P_idle, t_fit_s=t_fit)
    fit["t_fit_s"] = t_fit
    # sensor update rate: how often the reported temperature actually changes during the rise
    rise = (t > 0) & (t < t_fit)
    changes = np.flatnonzero(np.diff(T[rise]) != 0)
    fit["temp_update_interval_s_median"] = float(np.median(np.diff(t[rise][changes]))) if changes.size > 2 else None
    fit.update({"P_idle_W": P_idle, "P_load_W": P_load, "fan_first_on_s": float(fan_on[0]) if fan_on.size else None,
                "session": folder})
    if fit["temp_update_interval_s_median"] and fit["tau_s"] < 3 * fit["temp_update_interval_s_median"]:
        fit["warnings"].append(f"tau is below 3x the sensor's update interval ({fit['temp_update_interval_s_median']:.2f} s): "
                               "not resolved; the die responds within about one or two sensor updates")
    out["fits"][name] = fit
if __name__ == "__main__":
    p = ROOT / "data" / "calibration" / "M001_M002_thermal_step.json"
    p.write_text(json.dumps(out, indent=1), encoding="utf-8")
    for k, v in out["fits"].items():
        print(f"{k}: step {v['dP_W']:.0f} W, tau {v['tau_s']:.2f} +/- {v['se']['tau_s']:.2f} s, A {v['A_K']:.1f} K "
              f"(R_fast {v['R_fast_K_per_W']:.3f} K/W), slow drift {v['B_K_per_s']:.3f} K/s, fan on at {v['fan_first_on_s']} s, "
              f"rmse {v['rmse_K']:.2f} K; {'; '.join(v['warnings'])}")
