"""Pre-registered spec for E012: with real-silicon parameters, does energy-optimal control run warm enough
to make the waste heat reusable, and what does a heat-reuse-grade supply floor cost?

Two parameter worlds: the registry placeholders, and the RTX 5070-derived values (clock sensitivity M001,
leakage matched to the measured temperature slope, voltage-floor V-f form fitted to the measured power curve).
Written and committed before E012 ran (and before E011's results were seen).
Usage:  python experiments/make_spec_e012.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "experiments"
vf = json.loads((ROOT / "data" / "calibration" / "M001_vf_fit.json").read_text())
m001 = json.loads((ROOT / "data" / "calibration" / "M001_calibration.json").read_text())

WORLDS = {
    "registry": {},
    "measured": {**{k: v["value"] for k, v in m001["overrides"].items()},
                 "kappa_leak": 0.02, "p_leak_ref": vf["fit"]["p_leak_ref"],
                 "v_min_ratio": vf["fit"]["v_min_ratio"], "vf_knee": vf["fit"]["vf_knee"]},
}
FLOORS = {"nofloor": {"t_sup_min": 12.0}, "floor40": {"t_sup_min": 40.0}}
PLANTS = {"quasi": {"loop_mass_kg": 0.0, "tsup_ramp_K_per_min": 0.0},
          "dyn150": {"loop_mass_kg": 150.0, "tsup_ramp_K_per_min": 0.25}}

variants = [{"label": f"{w}|{fl}|{pl}", "param_overrides": {**wo, **fo, **po, "warm_start": 1.0}}
            for w, wo in WORLDS.items() for fl, fo in FLOORS.items() for pl, po in PLANTS.items()]

spec = {
    "key": "E012",
    "title": "Warm water on real silicon: does energy-optimal control make AI waste heat reusable, and what does a "
             "heat-reuse supply floor cost?",
    "research_question": "With clock sensitivity, leakage-temperature slope and voltage-frequency shape taken from a "
                         "real GPU instead of placeholders, how warm does energy-optimal (lag-aware joint) control run "
                         "the coolant, how much of the rejected heat becomes reusable (return water >= 45 C), and what "
                         "does forcing a 40 C supply floor cost in energy, safety and service?",
    "hypothesis": (
        "Conditions: 2 parameter worlds (registry; measured) x 2 supply floors (none, i.e. 12 C; 40 C) x 2 plants "
        "(quasi-steady; 150 kg loop, 0.25 K/min) x 3 scenarios (S1 20 C, S3 35 C, S4 8 C ambient). "
        "H1: without a floor, joint_lag's time-averaged supply temperature is at least 10 K higher in the measured "
        "world than in the registry world, in every scenario and plant. "
        "H2: without a floor, in the measured world joint_lag makes at least 50% of rejected heat reusable in S1 and "
        "S4 with the quasi-steady plant, while in the registry world it makes less than 20% reusable there. "
        "H3: the 40 C floor raises joint_lag's energy per successful task by less than 0.5% (95% CI upper bound) in the "
        "measured world in every scenario and plant, and the floor's penalty is larger in the registry world than in "
        "the measured world in every scenario and plant (seed-paired difference of penalties, 95% CI above 0). "
        "H4: joint_lag records zero chip-seconds above 80 C in all 24 conditions. "
        "H5: steady-state joint exceeds 80 C in at least one condition with the 150 kg loop."),
    "null_hypothesis": "Real-silicon parameters change neither the energy-optimal supply temperature nor the cost of "
                       "warm-water operation.",
    "independent_variables": ["parameter world (2)", "supply floor (2)", "plant (2)", "scenario (3)",
                              "policy (independent, joint, joint_lag)"],
    "dependent_variables": ["T_sup_mean_C (time-averaged supply temperature)", "Q_reusable_kWh / Q_rejected_kWh",
                            "E_per_success_kJ", "chip_s_over_target", "chip_s_throttled", "slo_violations",
                            "Ex_rejected_kWh"],
    "controlled_variables": ["seeds 0-4", "warm start", "registry values for everything not listed in the world",
                             "reuse threshold t_reuse_min = 45 C (registry, class F)"],
    "baseline": "registry world within each floor, plant and scenario; no floor within each world",
    "configuration": f"Worlds: {WORLDS}. Floors: {FLOORS}. Plants: {PLANTS}. Measured-world V-f and leakage from "
                     f"data/calibration/M001_vf_fit.json (rms shape error {vf['rms_error_rel_top']:.3f} of top-clock "
                     f"power vs {vf['registry_linear_rms']:.3f} for the registry linear form).",
    "evaluation_criteria": "T_sup_mean_C and reuse fractions as seed means over 5 seeds; energy as paired relative "
                           "differences with 95% t-CI; floor penalty = E_per_success(floor40)/E_per_success(nofloor) - 1 "
                           "per seed.",
    "known_limitations": (
        "Heat counts as reusable when the water leaving the loop is at or above 45 C; there is no heat customer, price "
        "or seasonal demand. The measured world transfers shapes from one 250 W consumer card to a 600 W-class "
        "simulated accelerator (class E). Leakage slope from a 4 K window. Ambient temperature is constant within a "
        "run. 5 seeds."),
    "disclosure": (
        "Written before E011's results were seen and before any E012 cell ran. Known: E009 and E010 results; the "
        "voltage-floor fit (v_min_ratio 0.78, vf_knee 0.805, p_leak_ref re-matched to 27.42 W); one exploratory E011 "
        "run (see E011). The T_sup_mean_C metric is added to the simulator after this spec is committed and before "
        "E012 runs; it changes no other output."),
    "design": {"scenarios": ["S1_moderate", "S3_hot", "S4_cool"], "policies": ["independent", "joint", "joint_lag"],
               "seeds": [0, 1, 2, 3, 4], "timeseries_seeds": [0], "variants": variants},
}
base = json.loads((HERE / "E001_policy_benchmark.json").read_text())
for k in ("data_collection", "statistics", "practical_significance_threshold"):
    if k in base:
        spec[k] = base[k]

if __name__ == "__main__":
    (HERE / "E012_warm_water.json").write_text(json.dumps(spec, indent=2))
    print(f"wrote E012_warm_water.json: {len(variants)} variants x 3 scenarios x 3 policies x 5 seeds = {len(variants) * 45} runs")
