"""Pre-registered spec for E013: is a fixed thermal safety margin as good as lag-aware planning?

The obvious simpler answer to E010's overheating under a slow coolant loop is to plan against a lower
temperature target. E013 gives steady-state joint control (with joint_lag's overload fallback, i.e. joint_fb,
so the fallback is not a confound) margins of 0, 3, 6 and 9 K below the 80 C target and compares it with
joint_lag, which has no margin. Only the controller's target changes; time above target is still measured
against 80 C.

Written while E011B was running, before its results were seen, and committed before any E013 cell ran.
Usage:  python experiments/make_spec_e013.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
e011 = json.loads((HERE / "E011_lag_aware.json").read_text())
d = e011["design"]
MARGINS = [0, 3, 6, 9]
base_vars = [v for v in d["variants"] if not v["label"].endswith("quasi") and "amb20" not in v["label"]]
variants = []
for v in base_vars:
    for m in MARGINS:
        variants.append({"label": f"{v['label']}|m{m}", "param_overrides": v["param_overrides"],
                         "scenario_overrides": v["scenario_overrides"],
                         "model_param_overrides": {"t_target": 80.0 - m},
                         "policies": ["joint_fb", "joint_lag"] if m == 0 else ["joint_fb"]})
n_runs = sum(len(v["policies"]) for v in variants) * len(d["seeds"])

spec = {
    "key": "E013",
    "title": "Fixed thermal margin vs lag-aware planning under slow coolant loops",
    "research_question": "Can steady-state joint control match lag-aware joint control's safety under a slow coolant "
                         "loop simply by planning against a lower temperature target, and at what energy and service "
                         "cost compared with joint_lag?",
    "hypothesis": (
        f"Conditions: the {len(base_vars)} dynamic-loop conditions of E011 at 30 and 40 C ambient (3 cold-plate states x "
        "2 ambients x 2 loops), S6 profile, measured leakage slope and clock sensitivity. joint_fb plans against "
        "80 - m C for m in {0, 3, 6, 9} K; joint_lag plans against 80 C. Time above target is measured against 80 C. "
        "H1: joint_fb without a margin exceeds 80 C (seed-mean chip-seconds above target > 0) in at least one condition. "
        "H2: a 3 K margin is not enough: joint_fb with m = 3 exceeds 80 C in at least one condition. "
        "H3: lag-awareness costs less energy than a margin that makes joint_fb safe. Let m* be the smallest margin in "
        "{3, 6, 9} with zero seed-mean chip-seconds above 80 C in all conditions (m* = 9 if none). joint_lag's energy "
        "per successful task is below joint_fb's at m* in at least 9 of the conditions (95% CI upper bound of "
        "joint_lag / joint_fb(m*) - 1 below 0). "
        "H4: lag-awareness costs no more service than that margin: joint_lag's late tasks (seed mean) exceed joint_fb's "
        "at m* by at most 1 in every condition. "
        "H5: joint_lag records zero chip-seconds above 80 C in every condition."),
    "null_hypothesis": "A fixed margin on the thermal target gives the same safety at the same energy and service cost "
                       "as lag-aware planning.",
    "independent_variables": ["cold-plate state (3)", "ambient (2)", "loop (2)", "controller target margin (4, joint_fb)",
                              "policy (joint_fb, joint_lag)"],
    "dependent_variables": ["chip_s_over_target", "chip_s_throttled", "peak_T_j_C", "slo_violations", "success_rate",
                            "E_per_success_kJ"],
    "controlled_variables": e011["controlled_variables"] + ["thermal outcomes always measured against 80 C"],
    "baseline": "joint_fb at each margin within each condition",
    "configuration": f"As E011 (dynamic-loop conditions at 30 and 40 C). Margins {MARGINS} K via the controller's "
                     "t_target (model_param_overrides); the simulated hardware keeps t_target 80 C and t_throttle 85 C.",
    "evaluation_criteria": "Thermal outcomes and late tasks as seed means over 5 seeds; energy as paired relative "
                           "differences with 95% t-CI (joint_lag in the m0 variant paired seed by seed with joint_fb in "
                           "the m* variant of the same condition).",
    "known_limitations": (
        "Everything in E011's limitations. Margins are fixed, not tuned per condition; a margin scheduled on ambient or "
        "loop state would be a different (lag-aware in effect) controller. The margin grid is coarse (3 K steps)."),
    "disclosure": (
        "Known when written: E011's results (steady-state joint's peak junction temperature reached 81.5-81.8 C with "
        "moderate fouling and 85.1-85.2 C with severe fouling at 40 C ambient on both dynamic loops) and the E011 "
        "fallback diagnostic. E011B was running; none of its results had been looked at. No E013 cell was run before "
        "registration. The experiment runner gained per-variant policy lists for this spec; existing specs expand to "
        "the same cells as before."),
    "design": {"scenarios": d["scenarios"], "policies": ["joint_fb", "joint_lag"], "seeds": d["seeds"],
               "timeseries_seeds": d["timeseries_seeds"], "param_overrides": d["param_overrides"], "variants": variants},
}
base = json.loads((HERE / "E001_policy_benchmark.json").read_text())
for k in ("data_collection", "statistics", "practical_significance_threshold"):
    if k in base:
        spec[k] = base[k]

if __name__ == "__main__":
    (HERE / "E013_margin_vs_lag.json").write_text(json.dumps(spec, indent=2))
    print(f"wrote E013_margin_vs_lag.json: {len(variants)} variants, {n_runs} runs")
