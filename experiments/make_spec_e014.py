"""Pre-registered spec for E014: does lag-aware control need an accurate loop model, or any loop model at all?

joint_lag (E011) knew the coolant loop's mass and the plant's ramp limit exactly. Here its model is wrong by a
factor of 4 either way on each, and a model-free variant (joint_meas) is added: it checks thermal safety at
max(measured supply temperature, commanded setpoint), never assuming that a colder setpoint has arrived, and
ignores ramp and tank dynamics. All three share the same overload fallback.

Reasoning written down before running: when the controller lowers the setpoint, the hottest supply the chips
see before the next decision is the one measured now, which needs no model; the loop model matters only while
the tank warms toward a setpoint the plant is still ramping down from. Written while E012 was running, before
E013's results existed; committed before any E014 cell ran.
Usage:  python experiments/make_spec_e014.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
e011 = json.loads((HERE / "E011_lag_aware.json").read_text())
d = e011["design"]
PLANTS = {"dyn40": (40.0, 1.0), "dyn150": (150.0, 0.25)}          # true loop mass (kg) and ramp (K/min), as E011
ERRORS = {"exact": (1.0, 1.0), "mass_x0.25": (0.25, 1.0), "mass_x4": (4.0, 1.0),
          "ramp_x0.25": (1.0, 0.25), "ramp_x4": (1.0, 4.0)}
base_vars = [v for v in d["variants"] if "amb40" in v["label"] and not v["label"].endswith("quasi")]
variants = []
for v in base_vars:
    mass, ramp = PLANTS[v["label"].split("|")[2]]
    for name, (fm, fr) in ERRORS.items():
        variants.append({"label": f"{v['label']}|{name}", "param_overrides": v["param_overrides"],
                         "scenario_overrides": v["scenario_overrides"],
                         "model_param_overrides": {} if name == "exact" else
                         {"loop_mass_kg": mass * fm, "tsup_ramp_K_per_min": ramp * fr},
                         "policies": ["joint_lag", "joint_meas"] if name == "exact" else ["joint_lag"]})
n_runs = sum(len(v["policies"]) for v in variants) * len(d["seeds"])

spec = {
    "key": "E014",
    "title": "Robustness of lag-aware control to loop-model error, and a model-free ablation",
    "research_question": "Does lag-aware joint control stay safe when its model of the coolant loop's mass and the "
                         "plant's ramp limit is wrong by 4x, and does it need a loop model at all?",
    "hypothesis": (
        f"Conditions: the {len(base_vars)} slow-loop conditions of E011 at 40 C ambient (3 cold-plate states x 2 loops), "
        "S6 profile, measured leakage slope and clock sensitivity. "
        "H1 (replication): joint_lag with the exact loop model records zero chip-seconds above 80 C in all 6. "
        "H2 (robust to model error): joint_lag records zero chip-seconds above 80 C in all 6 conditions with each of "
        "the four wrong models (loop mass x0.25 and x4, ramp x0.25 and x4). "
        "H3 (no model needed for safety): joint_meas records at most 10 chip-seconds above 80 C (seed mean) in each of "
        "the 6 conditions and never throttles. "
        "H4 (no model needed for cost): joint_meas's energy per successful task is within +/-1% of joint_lag's (95% "
        "CI of joint_meas / joint_lag - 1 inside +/-1%) and its late tasks within 1 per run, in all 6. "
        "H5 (model error costs little): for each wrong model, joint_lag's energy per successful task is within +/-1% "
        "of the exact-model joint_lag's (95% CI) in all 6 conditions."),
    "null_hypothesis": "Lag-aware control's safety depends on an accurate loop model.",
    "independent_variables": ["cold-plate state (3)", "loop (2)", "loop-model error (5, joint_lag)",
                              "policy (joint_lag, joint_meas)"],
    "dependent_variables": ["chip_s_over_target", "chip_s_throttled", "peak_T_j_C", "slo_violations", "success_rate",
                            "E_per_success_kJ"],
    "controlled_variables": e011["controlled_variables"],
    "baseline": "joint_lag with the exact loop model within each condition",
    "configuration": f"As E011 at 40 C ambient on both slow loops. True loops {PLANTS} (mass kg, ramp K/min); model "
                     f"errors {ERRORS} (factors on mass, ramp) applied to the controller's model only.",
    "evaluation_criteria": "Thermal outcomes and late tasks as seed means over 5 seeds; energy as paired relative "
                           "differences with 95% t-CI (joint_meas and wrong-model joint_lag paired seed by seed with "
                           "exact-model joint_lag in the same condition).",
    "known_limitations": (
        "Everything in E011's limitations, including the single well-mixed tank in both simulator and controller: a "
        "model-structure error (stratification, transport delay) is not tested. Model errors are applied one at a "
        "time. 40 C ambient only."),
    "disclosure": (
        "Known when written: E011 and E011B results; E012 and E013 were running or queued and none of their results "
        "had been looked at. joint_meas was exercised only by unit tests (one 30-minute run of the default "
        "configuration and one decision on a constructed observation). No E014 cell was run before registration."),
    "design": {"scenarios": d["scenarios"], "policies": ["joint_lag", "joint_meas"], "seeds": d["seeds"],
               "timeseries_seeds": d["timeseries_seeds"], "param_overrides": d["param_overrides"], "variants": variants},
}
base = json.loads((HERE / "E001_policy_benchmark.json").read_text())
for k in ("data_collection", "statistics", "practical_significance_threshold"):
    if k in base:
        spec[k] = base[k]

if __name__ == "__main__":
    (HERE / "E014_loop_model.json").write_text(json.dumps(spec, indent=2))
    print(f"wrote E014_loop_model.json: {len(variants)} variants, {n_runs} runs")
