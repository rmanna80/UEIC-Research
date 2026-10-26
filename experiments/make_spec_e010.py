"""Pre-registered spec for E010: when does joint control keep chips below the thermal target where
independent control does not, and does that safety cost energy? Leakage and clock sensitivity come
from the RTX 5070 measurements (as in E009).

Written and committed before E010 ran. Usage:  python experiments/make_spec_e010.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent

e009 = json.loads((HERE / "E009_matched_leakage.json").read_text())
betas = e009["design"]["param_overrides"]
leak = next(v["param_overrides"] for v in e009["design"]["variants"] if v["label"] == "matched_k0.02")

DEGRADATION = {"clean": {"r_cond": 0.035, "r_conv_ref": 0.015},        # registry defaults
               "moderate": {"r_cond": 0.040, "r_conv_ref": 0.0225},
               "severe": {"r_cond": 0.045, "r_conv_ref": 0.030}}        # as S6_degraded_cooling
AMBIENT = [20.0, 30.0, 40.0]
PLANTS = {"quasi": {"loop_mass_kg": 0.0, "tsup_ramp_K_per_min": 0.0},
          "dyn40": {"loop_mass_kg": 40.0, "tsup_ramp_K_per_min": 1.0}}

variants = []
for pl, plant in PLANTS.items():
    for dg, res in DEGRADATION.items():
        for amb in AMBIENT:
            variants.append({"label": f"{dg}|amb{amb:.0f}|{pl}",
                             "param_overrides": {**res, **plant, "warm_start": 1.0},
                             "scenario_overrides": {"t_amb": amb}})

spec = {
    "key": "E010",
    "title": "Thermal safety: joint vs independent control under cooling degradation and heat (measured leakage)",
    "research_question": "With leakage and clock sensitivity as measured on real hardware, in which conditions does "
                         "joint control keep chips below the 80 C target where independent control does not, and "
                         "does that safety cost energy?",
    "hypothesis": (
        "Conditions: 3 cold-plate states (clean, moderate, severe) x 3 ambient temperatures (20, 30, 40 C) x 2 plants "
        "(quasi-steady; 40 kg loop with 1 K/min ramp), high load (S6 profile). "
        "H1: with the quasi-steady plant, joint records zero chip-seconds throttled in all 9 conditions and zero "
        "chip-seconds above 80 C in at least 8 of 9. "
        "H2: with the quasi-steady plant, independent throttles (seed-mean chip-seconds throttled > 0) in at least 3 of "
        "the 9 conditions, all of them with moderate or severe degradation. "
        "H3: with the dynamic loop, joint exceeds 80 C (seed mean > 0) in at least one severe-degradation condition. "
        "H4: safety costs no energy: joint vs independent energy per successful task has a 95% CI upper bound below "
        "+1% in all 18 conditions. "
        "H5: joint uses at least 10% less energy per successful task than fixed in every condition (95% CI upper "
        "bound below -10%)."),
    "null_hypothesis": "Joint and independent control are equally safe under cooling degradation and heat.",
    "independent_variables": ["cold-plate state (3)", "ambient temperature (3)", "plant (2)",
                              "policy (fixed, independent, joint)"],
    "dependent_variables": ["chip_s_over_target", "chip_s_throttled", "peak_T_j_C", "slo_violations",
                            "success_rate", "E_per_success_kJ"],
    "controlled_variables": ["S6 load profile (mean 0.65, amplitude 0.15)", "seeds 0-4", "warm start",
                             "leakage matched to the measured slope (kappa 0.02)", "clock sensitivity from M001",
                             "twin knows the true cold-plate state"],
    "baseline": "independent within each condition (safety and energy); fixed within each condition (energy)",
    "configuration": (f"Every cell: {betas} (M001) and {leak} (E009 matched_k0.02). Cold-plate states: {DEGRADATION}. "
                      f"Plants: {PLANTS}. Dynamic-loop values are class F placeholders, as in E006."),
    "evaluation_criteria": "Thermal outcomes as seed means over 5 seeds; energy as paired relative differences with "
                           "95% t-CI; practical threshold 1%.",
    "known_limitations": (
        "The controllers' twin knows the true cold-plate state; an unnoticed fouling case is E005/E008 territory. "
        "Leakage matched at one operating point from one consumer card. Voltage-frequency form is the rejected "
        "registry placeholder. No facility power cap. 5 seeds."),
    "disclosure": (
        "Known when these hypotheses were written: E009 (S6 profile, matched leakage: independent 395 chip-s above "
        "80 C and 20 throttled, joint 0), E006 v2 (registry leakage: joint exceeded 80 C under the slow loop with "
        "degraded cooling, never throttled), and E001/E001C thermal outcomes. No E010 cells were run before "
        "registration."),
    "design": {"scenarios": ["S6_degraded_cooling"], "policies": ["fixed", "independent", "joint"],
               "seeds": [0, 1, 2, 3, 4], "timeseries_seeds": [0], "param_overrides": {**betas, **leak},
               "variants": variants},
}
base = json.loads((HERE / "E001_policy_benchmark.json").read_text())
for k in ("data_collection", "statistics", "practical_significance_threshold"):
    if k in base:
        spec[k] = base[k]

if __name__ == "__main__":
    (HERE / "E010_thermal_safety.json").write_text(json.dumps(spec, indent=2))
    print(f"wrote E010_thermal_safety.json: {len(variants)} conditions x 3 policies x 5 seeds = {len(variants) * 15} runs")
