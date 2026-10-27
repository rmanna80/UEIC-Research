"""Pre-registered spec for E011: does lag-aware joint control (joint_lag) keep chips safe where
steady-state joint control failed under a slow coolant loop (E010), without costing energy?

Written and committed before E011 ran. Usage:  python experiments/make_spec_e011.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
e010 = json.loads((HERE / "E010_thermal_safety.json").read_text())
base_over = e010["design"]["param_overrides"]

DEGRADATION = {"clean": {"r_cond": 0.035, "r_conv_ref": 0.015},
               "moderate": {"r_cond": 0.040, "r_conv_ref": 0.0225},
               "severe": {"r_cond": 0.045, "r_conv_ref": 0.030}}
AMBIENT = [20.0, 30.0, 40.0]
PLANTS = {"quasi": {"loop_mass_kg": 0.0, "tsup_ramp_K_per_min": 0.0},
          "dyn40": {"loop_mass_kg": 40.0, "tsup_ramp_K_per_min": 1.0},
          "dyn150": {"loop_mass_kg": 150.0, "tsup_ramp_K_per_min": 0.25}}

variants = [{"label": f"{dg}|amb{amb:.0f}|{pl}", "param_overrides": {**res, **plant, "warm_start": 1.0},
             "scenario_overrides": {"t_amb": amb}}
            for pl, plant in PLANTS.items() for dg, res in DEGRADATION.items() for amb in AMBIENT]

spec = {
    "key": "E011",
    "title": "Lag-aware joint control under cooling degradation, heat and slow coolant loops",
    "research_question": "Does planning with the coolant loop's lag (joint_lag) remove the overheating that "
                         "steady-state joint control showed under a slow loop in E010, and at what energy and "
                         "service cost?",
    "hypothesis": (
        "Conditions: 3 cold-plate states x 3 ambient temperatures (20/30/40 C) x 3 plants (quasi-steady; 40 kg loop, "
        "1 K/min ramp; 150 kg loop, 0.25 K/min ramp), S6 load profile, measured leakage slope and clock sensitivity. "
        "H1: joint_lag records zero chip-seconds throttled in all 27 conditions. "
        "H2: joint_lag records zero chip-seconds above 80 C in all 18 dynamic-loop conditions. "
        "H3: with the quasi-steady plant, joint_lag's results equal joint's in all 9 conditions (identical decisions). "
        "H4: joint_lag uses no more energy per successful task than joint in every condition (95% CI upper bound of "
        "joint_lag/joint - 1 below +0.5%) and less than independent (CI upper bound below 0) wherever independent "
        "exceeded 80 C. "
        "H5: joint_lag's SLO violations (seed mean) exceed the larger of joint's and independent's by at most 2 per "
        "run in every condition."),
    "null_hypothesis": "Modelling the loop's lag does not change safety or energy relative to steady-state joint control.",
    "independent_variables": ["cold-plate state (3)", "ambient (3)", "plant (3)", "policy (independent, joint, joint_lag)"],
    "dependent_variables": ["chip_s_over_target", "chip_s_throttled", "peak_T_j_C", "slo_violations", "success_rate",
                            "E_per_success_kJ"],
    "controlled_variables": ["S6 load profile", "seeds 0-4", "warm start", "leakage matched to the measured slope "
                             "(kappa 0.02)", "clock sensitivity from M001", "twin knows the true cold-plate state "
                             "and the loop's mass and ramp limit"],
    "baseline": "joint and independent within each condition",
    "configuration": f"Every cell: {base_over}. Plants: {PLANTS}. Cold-plate states: {DEGRADATION}.",
    "evaluation_criteria": "Thermal outcomes and SLO violations as seed means over 5 seeds; energy as paired relative "
                           "differences with 95% t-CI.",
    "known_limitations": (
        "The controller knows the loop's mass and ramp limit exactly; the loop model is a single well-mixed tank. "
        "Leakage matched at one operating point from one consumer card; voltage-frequency form is the registry "
        "placeholder. 5 seeds. independent and joint cells repeat E010's design (40 kg) and add the 150 kg loop."),
    "disclosure": (
        "Before registration, one exploratory run (severe fouling, 40 C ambient, S6 profile shortened to 1 h, seed 0, "
        "40 kg loop and quasi-steady plant) compared joint_lag with joint and independent: with the 40 kg loop joint "
        "spent 617 chip-s above 80 C (26 throttled), independent 404 (94), joint_lag 0, and joint_lag used 8.50 vs "
        "8.64 kJ per successful task; with the quasi-steady plant joint_lag matched joint exactly. That run is kept "
        "as a regression test. E010's results were known. The 150 kg plant was not tried before registration."),
    "design": {"scenarios": ["S6_degraded_cooling"], "policies": ["independent", "joint", "joint_lag"],
               "seeds": [0, 1, 2, 3, 4], "timeseries_seeds": [0], "param_overrides": base_over, "variants": variants},
}
base = json.loads((HERE / "E001_policy_benchmark.json").read_text())
for k in ("data_collection", "statistics", "practical_significance_threshold"):
    if k in base:
        spec[k] = base[k]

if __name__ == "__main__":
    (HERE / "E011_lag_aware.json").write_text(json.dumps(spec, indent=2))
    print(f"wrote E011_lag_aware.json: {len(variants)} conditions x 3 policies x 5 seeds = {len(variants) * 15} runs")
