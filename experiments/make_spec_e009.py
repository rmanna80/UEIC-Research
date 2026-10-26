"""Pre-registered spec for E009: joint vs independent control with leakage matched to the measured
temperature slope of a real GPU (M001/M002, RTX 5070).

Written and committed before E009 ran. Usage:  python experiments/make_spec_e009.py
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ueic import calibrate as cal  # noqa: E402
from ueic import physics as ph  # noqa: E402
from ueic.params import make_config  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = ROOT / "data" / "calibration"
M001 = DATA / "M001_calibration.json"


def rel_slope(cfg, s, T):
    """Simulator's d(chip power)/dT relative to chip power, compute-bound work (activity 1)."""
    v = float(ph.voltage_ratio(s, cfg))
    return cfg.kappa_leak * float(ph.leakage_power(T, v, cfg)) / float(ph.chip_power(s, T, 1.0, cfg))


def match_p_leak(base, kappa, target, s, T):
    """p_leak_ref that gives the target relative slope at (s, T) for this kappa (bisection)."""
    lo, hi = 0.0, 2000.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if rel_slope(make_config({**base, "kappa_leak": kappa, "p_leak_ref": mid}), s, T) < target:
            lo = mid
        else:
            hi = mid
    return round(0.5 * (lo + hi), 3)


calib = json.loads(M001.read_bytes())
betas = {k: v["value"] for k, v in calib["overrides"].items()}
f_ref = calib["clock_reference"]["f_ref_MHz"]
warm = cal.load_session(next(DATA.glob("*204001_warmup*")))
fl = cal.fit_leakage(warm)
sl = fl["slope_const_fan"]
target = sl["rel_per_K"]
half = 1.96 * sl["se"] / sl["P_mean_W"]
s_op = fl["clock_MHz"] / f_ref
T_op = round(float(sum(sl["T_range_C"]) / 2), 1)
registry_rel = rel_slope(make_config(betas), s_op, T_op)

variants = [{"label": "registry_leakage", "param_overrides": {}}]
for k in (0.01, 0.02, 0.03):
    variants.append({"label": f"matched_k{k}", "param_overrides": {"kappa_leak": k,
                                                                   "p_leak_ref": match_p_leak(betas, k, target, s_op, T_op)}})
for tag, t in (("low", target - half), ("high", target + half)):
    variants.append({"label": f"matched_k0.02_{tag}", "param_overrides": {"kappa_leak": 0.02,
                                                                          "p_leak_ref": match_p_leak(betas, 0.02, t, s_op, T_op)}})

base = json.loads((HERE / "E001_policy_benchmark.json").read_text())
spec = {
    "key": "E009",
    "title": "Joint vs independent control with leakage matched to a real GPU's measured temperature slope",
    "research_question": "Does joint control keep its advantage over independent control when the simulator's leakage "
                         "is only as temperature-sensitive as measured on real hardware?",
    "hypothesis": (
        "H1: with leakage matched to the measured slope (matched_k0.02), joint's advantage over independent is smaller "
        "in magnitude than with registry leakage in all 6 scenarios (seed-paired change in joint/independent - 1, "
        "95% CI entirely above 0). H2: with matched leakage (matched_k0.02), joint vs independent energy per successful "
        "task lies within the 1% practical threshold in all 6 scenarios (95% CI entirely inside -1%..+1%). H3: H2 also "
        "holds for every matched variant (kappa 0.01, 0.02, 0.03, and both ends of the slope's 95% CI). H4: in every "
        "scenario where independent control spent chip-seconds above the 80 C target with registry leakage, it spends "
        "fewer with matched leakage."),
    "null_hypothesis": "Matching leakage to the measured slope leaves joint control's advantage unchanged.",
    "independent_variables": ["leakage variant (registry; matched at kappa 0.01/0.02/0.03; matched at the slope's CI ends)",
                              "policy (independent, joint)", "scenario (6)"],
    "dependent_variables": ["E_per_success_kJ (primary)", "chip_s_over_target", "chip_s_throttled", "peak_T_j_C",
                            "slo_violations"],
    "controlled_variables": ["seeds 0-4", "registry defaults except leakage", "beta_compute and beta_memory from M001",
                             "4 h window + drain", "quasi-steady plant"],
    "baseline": "registry_leakage variant within E009 (same seeds and workloads)",
    "configuration": (
        f"Target: the simulator's relative temperature slope of chip power at s = {s_op:.3f}, {T_op} C, compute-bound "
        f"work, set to the measured {100 * target:.4f}%/K (95% CI {100 * (target - half):.4f}-{100 * (target + half):.4f}%/K) "
        f"from M001's warm-up at {fl['clock_MHz']:.0f} MHz, one clock step, constant fan "
        f"({sl['dPdT_W_per_K']:.3f} +/- {1.96 * sl['se']:.3f} W/K at {sl['P_mean_W']:.0f} W). The registry gives "
        f"{100 * registry_rel:.4f}%/K at the same point. For each kappa, p_leak_ref is solved to hit the target. "
        f"Clock sensitivity from M001: {betas}."),
    "evaluation_criteria": "Paired relative differences with 95% t-CI over 5 seeds; practical threshold 1%. H1: per "
                           "scenario and seed, d = (joint/independent - 1) in the matched variant minus the same in "
                           "registry_leakage. H4 on seed means of chip-seconds above target.",
    "known_limitations": (
        "The target comes from GPU board power of one consumer card over a 4 K window at one operating point; the "
        "simulator's slope at other clocks and temperatures follows its exponential model. Several matched p_leak_ref "
        "values lie below the registry range swept in E002. The voltage-frequency form is still the rejected registry "
        "placeholder. 5 seeds."),
    "disclosure": (
        "E002's one-at-a-time results were known when these hypotheses were written: joint vs independent was -0.62% at "
        "registry values, -0.04% with p_leak_ref = 30 W and -0.03% with kappa_leak = 0.005, which motivated H2. The "
        "measured slopes (M001 warm-up, M002 warm-up) were known. No E009 cells were run before registration."),
    "measurement_source": {"M001_calibration_sha256": hashlib.sha256(M001.read_bytes()).hexdigest(),
                           "warmup_session": warm.path.name, "slope": sl, "target_rel_per_K": target,
                           "target_ci95": [target - half, target + half], "operating_point": {"s": s_op, "T_C": T_op},
                           "registry_rel_per_K": registry_rel},
    "design": {"scenarios": base["design"]["scenarios"], "policies": ["independent", "joint"], "seeds": [0, 1, 2, 3, 4],
               "timeseries_seeds": [], "param_overrides": betas, "variants": variants},
}
for k in ("data_collection", "statistics", "practical_significance_threshold"):
    if k in base:
        spec[k] = base[k]

if __name__ == "__main__":
    for v in variants:
        if v["param_overrides"]:
            cfg = make_config({**betas, **v["param_overrides"]})
            print(f"{v['label']:20s} {v['param_overrides']}  rel slope {100 * rel_slope(cfg, s_op, T_op):.4f}%/K")
    print(f"target {100 * target:.4f}%/K at s={s_op:.3f}, {T_op} C; registry {100 * registry_rel:.4f}%/K")
    (HERE / "E009_matched_leakage.json").write_text(json.dumps(spec, indent=2))
    print("wrote E009_matched_leakage.json")
