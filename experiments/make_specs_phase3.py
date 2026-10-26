"""Pre-registered Phase 3 experiment specs (E006-E008).

Written before any of these experiments ran. Disclosures of exploratory looks that
preceded registration are part of each spec and of the research log.
Usage:  python experiments/make_specs_phase3.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from make_specs import COMMON, THRESHOLD  # noqa: E402

HERE = Path(__file__).resolve().parent
QS = {"loop_mass_kg": 0.0, "tsup_ramp_K_per_min": 0.0}
DYN_FAST = {"loop_mass_kg": 40.0, "tsup_ramp_K_per_min": 1.0}
DYN_SLOW = {"loop_mass_kg": 150.0, "tsup_ramp_K_per_min": 0.25}
WARM = {"warm_start": 1.0}   # E006 v2: every policy starts in its own steady state (see disclosure)

E006 = {
    "key": "E006",
    "title": "Joint control under a dynamic coolant loop (thermal mass + setpoint ramp limits)",
    "research_question": "Does the joint controller's advantage over independent control, and its thermal safety, "
                         "survive when the coolant loop has thermal mass and the plant cannot move its outlet "
                         "temperature instantly?",
    "hypothesis": "H1: joint uses less energy per successful task than independent (paired 95% CI below 0) in all "
                  "3 scenarios under both dynamic plants. H2: under the slow plant (150 kg, 0.25 K/min) joint "
                  "records chip-seconds above the 80 C target in at least one scenario, because it plans against a "
                  "steady state the plant cannot reach quickly. H3: the fixed policy's energy changes by less than "
                  "0.5% between quasi-steady and dynamic plants (its setpoint never moves). H4: joint_robust records "
                  "no more chip-seconds above target than joint in every scenario and plant.",
    "null_hypothesis": "The joint advantage disappears (CI includes 0) under a dynamic plant, and loop dynamics do "
                       "not affect thermal safety.",
    "independent_variables": ["plant model (quasi-steady, 40 kg + 1 K/min, 150 kg + 0.25 K/min)",
                              "policy (4 levels)", "scenario (3 levels)"],
    "dependent_variables": ["E_per_success_kJ (primary)", "chip_s_over_target", "chip_s_throttled", "peak_T_j_C",
                            "slo_violations", "E_loop_storage_kWh (must stay below 0.5% of grid energy)",
                            "action_changes"],
    "controlled_variables": ["workload per seed", "registry defaults", "4 h window + drain", "dt = 1 s"],
    "baseline": "quasi-steady plant (identical to E001) within each policy; independent within each plant",
    "configuration": "Loop mass and ramp values are class F placeholders (CDU tank + piping), not measurements.",
    "evaluation_criteria": f"Paired relative differences with 95% t-CI; practical threshold {THRESHOLD:.0%}. "
                           "H2/H4 judged on seed means of chip-seconds above target.",
    "known_limitations": "Single well-mixed tank; no pipe transport delay; ramp limit is symmetric; controllers "
                         "still plan with a steady-state twin.",
    "disclosure": "v1 (E006-20261026T184900-8dd0d3) ran with a cold start: the joint controller's first decision, "
                  "made at zero demand, chose 12 C, and the dynamic plant used that setpoint as the initial tank "
                  "temperature. The joint runs then drew down that stored coldness (up to 4.9 kWh of heat absorbed "
                  "and never rejected), which overstated joint's advantage under dynamic plants. Found by examining "
                  "v1's energy breakdown. v2 adds warm_start to every variant so each policy starts in its own steady "
                  "state; hypotheses are unchanged. v1 results were seen before v2 was registered. Before v1, only "
                  "unit tests ran on the dynamic plant.",
    "design": {"scenarios": ["S1_moderate", "S3_hot", "S6_degraded_cooling"],
               "policies": ["fixed", "independent", "joint", "joint_robust"], "seeds": list(range(10)),
               "timeseries_seeds": [0],
               "variants": [{"label": "quasi_steady", "param_overrides": {**QS, **WARM}},
                            {"label": "dyn_40kg_1Kmin", "param_overrides": {**DYN_FAST, **WARM}},
                            {"label": "dyn_150kg_0.25Kmin", "param_overrides": {**DYN_SLOW, **WARM}}]},
    **COMMON,
}

E007 = {
    "key": "E007",
    "title": "Move suppression for the joint controller: switching, energy cost, and time-step sensitivity",
    "research_question": "Can a switching threshold make the joint controller's results insensitive to the "
                         "simulation time step (E004 failed at 0.52%) without costing energy?",
    "hypothesis": "H1: thresholds up to 5% cut the number of action changes by less than 25%, because most "
                  "switching tracks demand rather than chatters. H2: at a 2% threshold the worst per-seed change "
                  "in grid energy between dt = 1 s and dt = 0.5 s falls below 0.5% in both scenarios. H3: a 2% "
                  "threshold costs at most 0.3% energy per successful task versus no threshold.",
    "null_hypothesis": "Suppression neither reduces time-step sensitivity nor is cheap.",
    "independent_variables": ["switch threshold (0, 0.5%, 2%, 5%)", "dt (1 s, 0.5 s)", "scenario"],
    "dependent_variables": ["action_changes", "clock_changes", "flow_changes", "tsup_changes",
                            "E_per_success_kJ", "E_grid_kWh", "chip_s_over_target"],
    "controlled_variables": ["joint policy only", "workload per seed", "registry defaults", "quasi-steady plant"],
    "baseline": "threshold 0 at the same dt",
    "configuration": "As E001",
    "evaluation_criteria": "H1 on seed-mean action changes; H2 on max over seeds of |E(dt=1)/E(dt=0.5) - 1| "
                           "within each threshold; H3 paired CI of energy per successful task.",
    "known_limitations": "Threshold acts on predicted, not measured, savings.",
    "disclosure": "Before registration one exploratory run (S1, seed 4, dt 1 s) showed action changes falling from "
                  "102 to 89 at a 5% threshold, with all switching in clocks and flow and none in supply "
                  "temperature. H1 was written after seeing that run. No dt comparison with suppression was run.",
    "design": {"scenarios": ["S1_moderate", "S3_hot"], "policies": ["joint"], "seeds": list(range(10)),
               "timeseries_seeds": [],
               "variants": [{"label": f"thr={thr}|dt={dt}", "param_overrides": {"joint_switch_rel": thr, "dt": dt}}
                            for thr, dt in [(0.0, 1.0), (0.005, 1.0), (0.02, 1.0), (0.05, 1.0),
                                            (0.0, 0.5), (0.02, 0.5), (0.05, 0.5)]]},
    **COMMON,
}

MISMATCH = [
    {"label": "default"},
    {"label": "high_leak|twin_correct", "param_overrides": {"kappa_leak": 0.03, "p_leak_ref": 130.0}},
    {"label": "high_leak|twin_low_leak", "param_overrides": {"kappa_leak": 0.03, "p_leak_ref": 130.0},
     "model_param_overrides": {"kappa_leak": 0.012, "p_leak_ref": 70.0}},
    {"label": "fouled_plate|twin_correct", "param_overrides": {"r_conv_ref": 0.026}},
    {"label": "fouled_plate|twin_clean", "param_overrides": {"r_conv_ref": 0.026},
     "model_param_overrides": {"r_conv_ref": 0.015}},
    {"label": "poor_chiller|twin_correct", "param_overrides": {"eta_ii_chiller": 0.35}},
    {"label": "poor_chiller|twin_optimistic", "param_overrides": {"eta_ii_chiller": 0.35},
     "model_param_overrides": {"eta_ii_chiller": 0.55}},
]

E008 = {
    "key": "E008",
    "title": "Self-correcting joint control under digital-twin mismatch",
    "research_question": "Does feeding measured junction temperatures back into the joint controller (one-sided "
                         "offset-free correction) restore thermal safety under twin mismatch without giving up its "
                         "energy advantage?",
    "hypothesis": "H1: in every mismatch case where joint exceeded the 80 C target, joint_robust has zero "
                  "chip-seconds throttled and at least 80% fewer chip-seconds above target than joint. H2: "
                  "joint_robust uses no more energy per successful task than independent (paired 95% CI upper "
                  "bound <= 0) in every case. H3: with a correct twin (default and *_twin_correct variants), "
                  "joint_robust is within +/-0.5% of joint on energy per successful task.",
    "null_hypothesis": "The correction does not remove overheating, or it removes it only by giving up the "
                       "energy advantage.",
    "independent_variables": ["truth|twin case (7 levels)", "policy (independent, joint, joint_robust)", "scenario"],
    "dependent_variables": ["E_per_success_kJ", "chip_s_over_target", "chip_s_throttled", "peak_T_j_C"],
    "controlled_variables": ["seeds 0-4", "4 h window", "quasi-steady plant", "bias gain 0.5"],
    "baseline": "independent within each case; joint within each case",
    "configuration": "Mismatch cases as E005, plus the registry default.",
    "evaluation_criteria": f"Paired relative differences with 95% t-CI; practical threshold {THRESHOLD:.0%}; "
                           "chip-second counts as seed means.",
    "known_limitations": "The correction only tightens the temperature target; it does not re-estimate leakage, "
                         "so energy predictions stay biased.",
    "disclosure": "Before registration a unit test ran S3_hot (1 h, seed 0) with the leakage mismatch and showed "
                  "joint_robust with fewer than half of joint's chip-seconds above target.",
    "design": {"scenarios": ["S1_moderate", "S3_hot"], "policies": ["independent", "joint", "joint_robust"],
               "seeds": [0, 1, 2, 3, 4], "timeseries_seeds": [0], "variants": MISMATCH},
    **COMMON,
}

if __name__ == "__main__":
    for spec, fname in ((E006, "E006_dynamic_loop.json"), (E007, "E007_move_suppression.json"),
                        (E008, "E008_robust_joint.json")):
        (HERE / fname).write_text(json.dumps(spec, indent=2))
        print("wrote", fname)
