"""Pre-registered spec for E015: the thermal futures engine. When does predicting the coolant's future help?

Research question A of the next-generation plan: is there a reproducible relationship between forecast
quality, coolant thermal inertia, actuator delay and the value of anticipatory (multi-step predictive)
control? Compared against the existing controllers, including the measured-state rule (joint_meas)
that E011-E014 showed is safe but never uses the slow actuator.

Written and committed before any E015 cell ran. Usage:  python experiments/make_spec_e015.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
e011 = json.loads((HERE / "E011_lag_aware.json").read_text())
BASE = {**e011["design"]["param_overrides"], "warm_start": 1.0}           # M001 clock sensitivity, matched leakage
MOD = {"r_cond": 0.040, "r_conv_ref": 0.0225}
SEV = {"r_cond": 0.045, "r_conv_ref": 0.030}
H3 = 3 * 3600.0
SCEN = {
    "burst": ({**MOD}, {"t_amb": 38.0, "load_mean": 0.55, "load_amp": 0.0, "load_period_s": H3, "duration_s": H3,
                        "bursts": [[5400.0, 1200.0, 0.35]]}),
    "ambient_ramp": ({**MOD}, {"t_amb": 25.0, "load_mean": 0.60, "load_amp": 0.10, "load_period_s": H3,
                               "duration_s": H3, "t_amb_profile": [[0.0, 25.0], [1800.0, 25.0], [7200.0, 42.0],
                                                                   [H3, 42.0]]}),
    "overload": ({**MOD}, {"t_amb": 35.0, "load_mean": 0.90, "load_amp": 0.05, "load_period_s": H3, "duration_s": H3}),
    "degraded": ({**SEV}, {"t_amb": 35.0, "load_mean": 0.65, "load_amp": 0.15, "load_period_s": H3, "duration_s": H3}),
}
LOOPS = {"instant": {"loop_mass_kg": 0.0, "tsup_ramp_K_per_min": 0.0},
         "loop40": {"loop_mass_kg": 40.0, "tsup_ramp_K_per_min": 1.0},
         "loop150": {"loop_mass_kg": 150.0, "tsup_ramp_K_per_min": 0.25}}
DELAYS = {"d0": 0.0, "d180": 180.0}
FORECASTS = {   # model-side settings (the controller's forecast); the plant is the same in every variant
    "base": ({}, ["independent", "joint", "joint_meas", "joint_lag", "mpc", "mpc_robust"]),   # mpc: persistence
    "oracle": ({"mpc_forecast_mode": 1}, ["mpc", "mpc_robust"]),
    "noisy": ({"mpc_forecast_mode": 1, "mpc_forecast_noise": 0.3}, ["mpc"]),
    "biased": ({"mpc_forecast_mode": 1, "mpc_forecast_bias": -0.3}, ["mpc"]),
    "blind": ({"mpc_forecast_mode": 2}, ["mpc"]),
}

variants = []
for sn, (pover, sover) in SCEN.items():
    for ln, lover in LOOPS.items():
        for dn, d in DELAYS.items():
            for fn, (mover, pols) in FORECASTS.items():
                variants.append({"label": f"{sn}|{ln}|{dn}|{fn}",
                                 "param_overrides": {**pover, **lover, "tsup_cmd_delay_s": d},
                                 "scenario_overrides": sover, "model_param_overrides": mover, "policies": pols})
n_runs = sum(len(v["policies"]) for v in variants) * 5

spec = {
    "key": "E015",
    "title": "Thermal futures: when does multi-step predictive control help, and what does it need?",
    "research_question": "Is there a reproducible relationship between forecast quality, coolant thermal inertia, "
                         "actuator delay and the value of anticipatory control, compared with steady-state joint "
                         "control, the measured-state rule and independent control?",
    "hypothesis": (
        "Conditions: 4 scenarios (scheduled burst at 38 C; ambient rising 25 -> 42 C; sustained overload at 35 C; "
        "severe cold-plate fouling at 35 C) x 3 plants (instant; 40 kg loop, 1 K/min; 150 kg loop, 0.25 K/min) x 2 "
        "setpoint command delays (0, 180 s) = 24 conditions; 5 seeds; measured clock sensitivity and leakage slope "
        "(as E011). MPC forecast variants: persistence (base), oracle, noisy (log-sd 0.3), biased (-30%), burst-blind. "
        "'Slow-loop conditions' = the 40 kg and 150 kg loops at both delays. 'Late tasks' = seed-mean SLO violations. "
        "H1 (safety): mpc and mpc_robust record zero chip-seconds above 80 C (seed mean) in all 24 conditions for every "
        "forecast variant, and no run falls back (decisions_fallback = 0). "
        "H2 (anticipation helps with inertia and a forecast): in the burst scenario, mpc with the oracle forecast has "
        "at least 25% fewer late tasks than joint_meas (and at least 1 fewer) in at least 3 of the 4 slow-loop "
        "conditions, with energy per successful task no more than 2% above joint_meas (95% CI upper bound) in each of "
        "those conditions. "
        "H3 (no inertia, no anticipation value): on the instant plant without delay, mpc (oracle) and joint_meas differ "
        "by at most max(1, 10%) in late tasks and their energy per successful task 95% CI lies inside +/-1%, in every "
        "scenario. "
        "H4 (forecast quality): summed over the 4 slow-loop burst conditions, late tasks satisfy oracle <= noisy and "
        "oracle < persistence, and burst-blind is within +/-20% of persistence (or within 1 task). "
        "H5 (anticipation cannot create capacity): in the overload scenario every policy has late tasks (seed mean > 0) "
        "in every condition, and mpc (oracle) is within +/-15% of joint_meas in late tasks in every condition. "
        "H6 (cost of robustness): wherever mpc (oracle) records zero time above 80 C, so does mpc_robust (oracle), and "
        "mpc_robust's energy per successful task is at most 3% above mpc's (oracle, 95% CI upper bound) in every "
        "condition. "
        "Descriptive, not confirmatory: the value of anticipation (late tasks and energy, mpc oracle vs joint_meas) "
        "against loop time constant, delay and forecast quality, as input to research question A."),
    "null_hypothesis": "Predicting the coolant's future and the workload adds nothing over the measured-state rule.",
    "independent_variables": ["scenario (4)", "plant (3)", "command delay (2)", "policy", "forecast (MPC only, 5)"],
    "dependent_variables": ["slo_violations", "success_rate", "E_per_success_kJ", "chip_s_over_target",
                            "chip_s_throttled", "peak_T_j_C", "decisions_fallback", "decisions_filtered",
                            "tsup_changes"],
    "controlled_variables": ["seeds 0-4 (paired workloads)", "warm start", "M001 clock sensitivity, leakage matched to "
                             "the measured slope (E011 base)", "legacy plant (plant_model 0) for continuity with "
                             "E010-E014", "controllers know the true loop parameters and cold-plate state",
                             "mpc_backlog_weight 20 W per work-second, horizon 15 min (registry defaults, not tuned)"],
    "baseline": "joint_meas (measured-state rule, same overload fallback) within each condition; also independent, "
                "joint, joint_lag",
    "configuration": f"Base {BASE}. Scenarios {SCEN}. Plants {LOOPS}. Delays {DELAYS}. Forecast variants "
                     f"{ {k: v[0] for k, v in FORECASTS.items()} }.",
    "evaluation_criteria": "Late tasks and thermal outcomes as seed means over 5 seeds; energy as paired relative "
                           "differences with 95% t-CI (seed-paired across variants of the same condition, since the "
                           "plant and workload are identical across forecast variants). Practical thresholds as stated "
                           "in the hypotheses; a CI excluding zero alone is not called a benefit.",
    "sample_size": "5 seeds per cell (paired); chosen for compute budget (about 1,300 runs), as in E010-E014. Late-task "
                   "counts are small integers, so H2-H5 use thresholds with absolute floors.",
    "randomization": "Workloads drawn per seed and shared across all arms; forecast noise drawn from generators seeded by "
                     "(seed, decision index).",
    "measurement_boundary": "Simulated facility boundary (IT + conversion + pump + fans + chiller) of one simulated "
                            "8-accelerator node; nothing here is measured.",
    "known_limitations": (
        "Simulation only, legacy plant (fan power proportional to heat; E012 audit). The controllers know the loop's mass, "
        "ramp and delay exactly; model error is E014/E016 territory. Forecast errors are synthetic. One MPC configuration "
        "(weights, horizon, grids) chosen as registry defaults, not tuned per condition. No power caps (Stage 7). 5 seeds."),
    "disclosure": (
        "Before registration, while developing the MPC, exploratory runs were made and looked at: (1) S6 profile at mean "
        "load 0.8, 40 C, severe fouling, 40 kg loop, 1 h, seed 1: joint 859 chip-s above 80 C and 46 late tasks; "
        "joint_meas and joint_lag 0 and 46; mpc 0 and 55 at first, 0 and 46 after two fixes (the safety filter and MPC "
        "now share one supply bound; fallback clocks no longer raise a clock-insensitive memory clock). (2) A burst "
        "scenario (severe fouling, 40 C, mean load 0.55, +0.35 for 20 min at 40 min, 150 kg loop, 1.5 h, seed 0): "
        "joint_meas 12 late tasks, 7.99 kJ; joint 3,907 chip-s above 80 C; mpc oracle 0 late, 7.84 kJ; mpc persistence "
        "2 late, 7.79 kJ; mpc_robust oracle 0 late, 7.88 kJ; the MPC pre-cooled the tank to ~27 C before the burst. A "
        "shortened version of (2) is a regression test. E015's conditions differ (moderate fouling at 38 C for the "
        "burst, other scenarios new) but the mechanism had been seen. Registry defaults for the MPC were not changed "
        "after these runs."),
    "design": {"scenarios": ["S6_degraded_cooling"], "policies": ["independent", "joint", "joint_meas", "joint_lag",
                                                                  "mpc", "mpc_robust"],
               "seeds": [0, 1, 2, 3, 4], "timeseries_seeds": [0], "param_overrides": BASE, "variants": variants},
}
base = json.loads((HERE / "E001_policy_benchmark.json").read_text())
for k in ("data_collection", "statistics", "practical_significance_threshold"):
    if k in base:
        spec[k] = base[k]

if __name__ == "__main__":
    (HERE / "E015_thermal_futures.json").write_text(json.dumps(spec, indent=2))
    print(f"wrote E015_thermal_futures.json: {len(variants)} variants, {n_runs} runs")
