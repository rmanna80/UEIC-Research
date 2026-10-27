"""Fit the voltage-floor V-f form (v_min_ratio, vf_knee) to the RTX 5070's measured power-vs-clock shape (M001).

The simulator's chip power at each measured clock ratio and temperature (compute-bound, activity 1, leakage
matched to the measured slope as in E009, clock sensitivity from M001), normalised to the top clock, is
compared with the measured board power normalised the same way. This is a shape transfer from a 250 W consumer
card to the simulated accelerator (class E), not a voltage measurement: NVML does not report voltage.

Usage:  python experiments/fit_vf_m001.py  ->  data/calibration/M001_vf_fit.json
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ueic import physics as ph  # noqa: E402
from ueic.params import make_config  # noqa: E402

calib = json.loads((ROOT / "data" / "calibration" / "M001_calibration.json").read_text())
e009 = json.loads((ROOT / "experiments" / "E009_matched_leakage.json").read_text())
base = {**e009["design"]["param_overrides"],
        **next(v["param_overrides"] for v in e009["design"]["variants"] if v["label"] == "matched_k0.02")}
pts = calib["energy_per_work"]["compute"]["points"]
s = np.array([p["s"] for p in pts]); T = np.array([p["temp_C"] for p in pts]); y = np.array([p["power_rel_top"] for p in pts])


def shape(over):
    cfg = make_config({**base, **over})
    P = np.array([float(ph.chip_power(si, Ti, 1.0, cfg)) for si, Ti in zip(s, T)])
    return P / P[-1]


def sse(over):
    return float(((shape(over) - y) ** 2).sum())


# The measured leakage slope was matched (E009) under the registry's linear V-f form. With the voltage-floor form
# the voltage at the matching point changes, so the V-f shape and p_leak_ref are re-solved together: fit the
# shape, re-match p_leak_ref to the same measured slope, repeat until both settle.
src = e009["measurement_source"]
target, s_op, T_op = src["target_rel_per_K"], src["operating_point"]["s"], src["operating_point"]["T_C"]


def rel_slope(cfg):
    v = float(ph.voltage_ratio(s_op, cfg))
    return cfg.kappa_leak * float(ph.leakage_power(T_op, v, cfg)) / float(ph.chip_power(s_op, T_op, 1.0, cfg))


def rematch(over):
    lo, hi = 0.0, 2000.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if rel_slope(make_config({**base, **over, "p_leak_ref": mid})) < target:
            lo = mid
        else:
            hi = mid
    return round(0.5 * (lo + hi), 3)


history = []
for it in range(6):
    best = None
    for vmin in np.arange(0.50, 0.951, 0.005):
        for knee in np.arange(0.50, 0.951, 0.005):
            e = sse({"v_min_ratio": round(float(vmin), 3), "vf_knee": round(float(knee), 3)})
            if best is None or e < best[0]:
                best = (e, round(float(vmin), 3), round(float(knee), 3))
    p_new = rematch({"v_min_ratio": best[1], "vf_knee": best[2]})
    history.append({"v_min_ratio": best[1], "vf_knee": best[2], "p_leak_ref": p_new})
    if p_new == base["p_leak_ref"]:
        break
    base["p_leak_ref"] = p_new
lin_reg = sse({"v_min_ratio": 0.70})
lin_best = min((sse({"v_min_ratio": round(float(v), 3)}), round(float(v), 3)) for v in np.arange(0.30, 1.001, 0.005))
fit = {"v_min_ratio": best[1], "vf_knee": best[2], "p_leak_ref": base["p_leak_ref"]}
check = make_config({**base, **fit})
out = {
    "kind": "ueic_vf_shape_fit", "source": "M001_calibration.json (compute kernel points)",
    "evidence": "E (shape transfer from a 250 W consumer card; voltage not measured)",
    "fixed_parameters": {k: v for k, v in base.items() if k != "p_leak_ref"}, "fit": fit, "iterations": history,
    "leakage_slope_at_match_point": {"rel_per_K": rel_slope(check), "target": target, "s": s_op, "T_C": T_op},
    "rms_error_rel_top": float(np.sqrt(best[0] / len(s))),
    "registry_linear_rms": float(np.sqrt(lin_reg / len(s))),
    "best_linear": {"v_min_ratio": lin_best[1], "rms": float(np.sqrt(lin_best[0] / len(s)))},
    "points": [{"s": float(si), "measured": float(yi), "fitted": float(fi), "registry": float(ri)}
               for si, yi, fi, ri in zip(s, y, shape(fit), shape({"v_min_ratio": 0.70}))],
}
if __name__ == "__main__":
    (ROOT / "data" / "calibration" / "M001_vf_fit.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("fit", "iterations", "leakage_slope_at_match_point", "rms_error_rel_top",
                                          "registry_linear_rms", "best_linear")}, indent=1))
    for p in out["points"]:
        print(f"  s={p['s']:.3f} measured {p['measured']:.3f} fitted {p['fitted']:.3f} registry {p['registry']:.3f}")
