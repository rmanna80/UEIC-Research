"""Pre-registered spec for E011B: an ablation that splits E011's energy result into its two causes.

E011 found joint_lag about 4.6% cheaper than joint per successful task even in benign dynamic-loop conditions,
where lag-awareness should change nothing. A diagnostic of one cell (clean|amb20|dyn40, seed 0) traced the gap to
the 24 of 240 control intervals where demand exceeded planned capacity: joint then runs every clock at maximum
(1.0, 1.0); joint_lag's fallback maximises throughput among safe actions and breaks ties on power, so it ran
(1.0, 0.5), keeping the clock-insensitive memory-bound work at a low clock. E011's energy comparison therefore
mixes two changes. E011B adds joint_fb (joint's feasibility check, joint_lag's fallback) to separate them.

Written after E011's results were seen and committed before any E011B cell ran.
Usage:  python experiments/make_spec_e011b.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
e011 = json.loads((HERE / "E011_lag_aware.json").read_text())
d = e011["design"]
JOINT_OVERHEATED = ["moderate|amb40|dyn40", "severe|amb40|dyn40", "moderate|amb40|dyn150", "severe|amb40|dyn150"]
dyn = [v["label"] for v in d["variants"] if not v["label"].endswith("quasi")]
benign_dyn = [lab for lab in dyn if lab not in JOINT_OVERHEATED]

spec = {
    "key": "E011B",
    "title": "Ablation of E011: how much of lag-aware control's energy saving is the overload fallback?",
    "research_question": "E011's joint_lag differed from joint in two ways: it checks safety at the supply "
                         "temperature the chips will actually see, and it falls back differently when demand exceeds "
                         "planned capacity. Which change produced E011's safety result and which its energy result?",
    "hypothesis": (
        "Same 27 conditions as E011 (3 cold-plate states x 3 ambients x 3 plants, S6 profile, measured leakage slope "
        "and clock sensitivity), policies joint, joint_fb, joint_lag, seeds 0-4. "
        "H1 (the fallback is the energy effect): joint_fb uses less energy per successful task than joint in all 27 "
        "conditions, by more than 2% (95% CI upper bound of joint_fb/joint - 1 below -2%). "
        f"H2 (lag-awareness is nearly free where it is not needed): in the {len(benign_dyn)} dynamic-loop conditions "
        "where joint stayed below 80 C in E011, the 95% CI of joint_lag/joint_fb - 1 lies inside +/-0.5%. "
        "H3 (lag-awareness is the safety effect): joint_fb exceeds 80 C (seed-mean chip-seconds above target > 0) in "
        f"all 4 dynamic-loop conditions where joint did in E011 ({', '.join(JOINT_OVERHEATED)}); joint_lag in none "
        "of the 27. "
        "H4 (the late tasks are the price of lag-awareness): joint_fb's SLO violations (seed mean) exceed joint's by at "
        "most 1 in every condition, and joint_lag's exceed joint_fb's in severe|amb40|dyn40 and severe|amb40|dyn150. "
        "H5 (determinism): joint's and joint_lag's runs reproduce E011's stored metrics exactly, run by run, in all 27 "
        "conditions (all simulated metrics present in both; wall-clock timings excluded)."),
    "null_hypothesis": "The overload fallback does not change energy or safety; E011's differences come from "
                       "lag-awareness alone.",
    "independent_variables": ["cold-plate state (3)", "ambient (3)", "plant (3)", "policy (joint, joint_fb, joint_lag)"],
    "dependent_variables": ["E_per_success_kJ", "chip_s_over_target", "chip_s_throttled", "peak_T_j_C",
                            "slo_violations", "success_rate"],
    "controlled_variables": e011["controlled_variables"],
    "baseline": "joint within each condition (fallback effect); joint_fb within each condition (lag-awareness effect)",
    "configuration": f"Identical to E011: {e011['configuration']}",
    "evaluation_criteria": "Energy as paired relative differences with 95% t-CI over 5 seeds; thermal outcomes and SLO "
                           "violations as seed means. Decomposition reported per condition: "
                           "joint_lag/joint - 1 = (joint_fb/joint - 1) + (joint_lag/joint_fb - 1) + cross term.",
    "known_limitations": (
        "Everything in E011's limitations. The fallback compared here is a design choice inside UEIC's controllers; "
        "independent control keeps its original fallback (all clocks to maximum when infeasible), so joint vs "
        "independent comparisons in earlier experiments are like-for-like but understate what better overload "
        "handling saves. Ablation hypotheses were written after E011's results were seen."),
    "disclosure": (
        "Known when these hypotheses were written: all E011 results (joint_lag 0 chip-s above 80 C vs joint 17,218 "
        "summed over the dynamic conditions; joint_lag vs joint energy -4.6% in benign dynamic conditions, -2.9% and "
        "-8.8% where joint overheated; joint_lag's late tasks 7.6 vs 2.0 per run in severe|amb40 with both dynamic "
        "loops) and one diagnostic of decision branches in clean|amb20|dyn40, seed 0. joint_fb was exercised only by "
        "decision-level unit tests and one run of the default configuration on a 30-minute test scenario; no E011B "
        "condition was simulated with it before registration. The simulator gained the T_sup_mean_C and "
        "T_ret_mean_C metrics after E011 ran; they change no other output (H5 checks this)."),
    "design": {**d, "policies": ["joint", "joint_fb", "joint_lag"]},
}
base = json.loads((HERE / "E001_policy_benchmark.json").read_text())
for k in ("data_collection", "statistics", "practical_significance_threshold"):
    if k in base:
        spec[k] = base[k]

if __name__ == "__main__":
    (HERE / "E011B_fallback_ablation.json").write_text(json.dumps(spec, indent=2))
    print(f"wrote E011B_fallback_ablation.json: {len(d['variants'])} conditions x 3 policies x 5 seeds = "
          f"{len(d['variants']) * 15} runs; benign dynamic conditions: {len(benign_dyn)}")
