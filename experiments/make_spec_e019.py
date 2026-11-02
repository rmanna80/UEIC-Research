"""Pre-register E019 (fault robustness). Needs the fault_* registry parameters and the four supervisor
policy names (nominal_/aware_ + joint_meas/mpc), which are added before the run (Stage 8)."""
import json
from pathlib import Path

WORLD = {"beta_compute": 0.983, "beta_memory": 0.0, "kappa_leak": 0.02, "p_leak_ref": 28.962, "warm_start": 1.0,
         "r_cond": 0.04, "r_conv_ref": 0.0225, "loop_mass_kg": 40.0, "tsup_ramp_K_per_min": 1.0}
SC = {"t_amb": 38.0, "load_mean": 0.6, "load_amp": 0.0, "duration_s": 7200.0}
W0, W1 = 2400.0, 4200.0
win = lambda k, m=0.0: {"fault_kind": k, "fault_t_start": W0, "fault_t_end": W1, "fault_magnitude": m}   # noqa: E731
faults = {
    "F0_none": ({}, win(0)),
    "F1_sensor_dropout": ({}, win(1)),
    "F2_junction_bias_low": ({}, win(2, -10.0)),
    "F3_stale_sensors": ({}, win(3)),
    "F4_clock_stuck": ({}, win(4)),
    "F5_comm_failure": ({}, win(5)),
    "F6_controller_crash": ({}, win(6)),
    "F7_solver_infeasible": ({}, win(7)),
    "F8_supply_bias_low": ({}, win(8, -8.0)),
    "P1_valve_delay": ({"tsup_cmd_delay_s": 600.0}, {**win(0), "tsup_cmd_delay_s": 0.0}),
    "P2_fouling_step": ({"r_fouling_step": 0.02, "r_fouling_start_s": W0}, {**win(0), "r_fouling_step": 0.0}),
    "P3_pump_degraded": ({"flow_max_factor": 0.6, "eta_pump": 0.35}, {**win(0), "flow_max_factor": 2.0, "eta_pump": 0.5}),
    "P4_wrong_model": ({}, {**win(0), "r_cond": 0.024}),
}
onset = {k: (W0 if k.startswith("F") or k == "P2_fouling_step" else 0.0) for k in faults}
pols = ["nominal_joint_meas", "aware_joint_meas", "nominal_mpc", "aware_mpc"]
spec = {
    "key": "E019", "title": "Fault robustness: nominal vs fault-aware supervision under identical injected failures",
    "research_question": "Under identical injected sensor, actuation, communication, software and physical faults, does "
                         "a fault-aware supervisor (validation, residual CUSUM, degradation estimate, recovery modes, "
                         "independent safety filter) reduce temperature violations relative to a nominal supervisor, "
                         "how fast does it detect and recover, and what does the caution cost?",
    "hypothesis": (
        "S6 scenario at 38 C ambient, load 0.6, 2 h, dynamic loop (40 kg, 1 K/min), RTX-world parameters (as E015). "
        "Controllers joint_meas and mpc, each under a nominal supervisor (catches exceptions, holds the last action) "
        "and a fault-aware supervisor. Window faults from 2400 to 4200 s: sensor dropout (junction and supply NaN), "
        "junction bias -10 K, stuck sensors, clock commands not applied, communication failure (telemetry frozen, "
        "commands lost), controller crash, solver infeasibility, supply-sensor bias -8 K. Physical faults unknown to "
        "the controller: 600 s setpoint delay, +0.02 K/W fouling step at 2400 s, degraded pump (flow capped at 0.6, "
        "efficiency 0.35), wrong model (controller's r_cond 0.024 vs true 0.04). H1: with no fault, the fault-aware "
        "supervisor raises no alarm in any run and its energy per success is within 0.5% of the nominal stack's for "
        "both controllers (seed means). H2: for the 8 window faults, the first alarm comes at or after onset and "
        "within 180 s (3 control intervals) in at least 80% of fault-aware runs (both controllers pooled). H3: for "
        "every fault and both controllers, fault-aware chip-seconds above t_target are at most the nominal stack's "
        "plus 1 chip-second (seed means). H4: for clock_stuck, fault-aware reduces chip-seconds above t_target by at "
        "least 50% relative to nominal for each controller where nominal's mean is above 0. H5: after window faults, "
        "the fault-aware supervisor is back in NORMAL mode within 300 s of the fault ending in at least 80% of the "
        "runs in which it left NORMAL. H6: for fouling, degraded pump and wrong model, the degradation detector "
        "alarms (at or after onset) in at least 80% of fault-aware runs. Descriptive: energy cost of fault-awareness "
        "per fault, late tasks, throttled chip-seconds, false alarms before onset."),
    "null_hypothesis": "Fault-aware supervision does not reduce temperature violations and detects faults no faster than chance.",
    "independent_variables": ["fault (13)", "supervisor (nominal, fault-aware)", "controller (joint_meas, mpc)"],
    "dependent_variables": ["chip_s_over_target", "throttled_chip_s", "E_per_success_kJ", "tasks_late",
                            "diag_first_alarm_t", "diag_recovered_t", "diag_safe_intervals", "diag_degraded_intervals",
                            "diag_degradation_alarm_t"],
    "controlled_variables": ["identical workloads per seed", "same scenario and plant", "hardware throttle on true temperature"],
    "baseline": "nominal supervisor with the same controller",
    "configuration": {"fault_onset_s": onset, "window": [W0, W1], "control_interval_s": 60},
    "evaluation_criteria": "Seed means for violations and fractions; detection delay = first alarm - onset; paired "
                           "relative differences with 95% t-CI for energy.",
    "sample_size": "5 seeds x 13 faults x 4 policy stacks = 260 runs.",
    "randomization": "Workloads drawn per seed, shared across faults and stacks.",
    "measurement_boundary": "Simulated single-node facility (as E015); faults are injected in simulation only.",
    "known_limitations": "Fault set and magnitudes chosen by hand; CUSUM learning window assumed fault-free (physical "
                         "faults present from t = 0 are learned as baseline and only the resistance estimator can see "
                         "them); one scenario; joint_meas does not use junction readings, so junction-sensor faults "
                         "cannot hurt it (a property, not an artefact). Crash and infeasibility are both injected as "
                         "exceptions for joint_meas.",
    "known_confounders": ["fault-aware SAFE mode raises cooling energy; energy differences mix caution with fault effects"],
    "disclosure": "Before registration, smoke runs (seed 0, 2 h, both controllers) of faults none, dropout, supply bias, "
                  "stale, clock_stuck and crash: no false alarm without a fault after a start-up fix; clock_stuck gave "
                  "515 (joint_meas) and 1224 (mpc) chip-seconds above target nominal vs 73 and 135 fault-aware; dropout "
                  "cost the fault-aware joint_meas stack ~23% energy per success; a supply bias of -8 K gave mpc 18 "
                  "chip-seconds above target nominal vs 0 fault-aware. Detector thresholds were fixed before E019 and "
                  "not tuned on these runs (the CUSUM was made more conservative after a unit test on synthetic "
                  "Gaussian residuals showed false alarms). No E019 cell was run before registration.",
    "design": {"scenarios": ["S6_degraded_cooling"], "seeds": [0, 1, 2, 3, 4], "timeseries_seeds": [0],
               "policies": pols, "scenario_overrides": SC,
               "variants": [{"label": k, "param_overrides": {**WORLD, **phys}, "model_param_overrides": model}
                            for k, (phys, model) in faults.items()]},
    "data_collection": "Append-only store; supervisor diagnostics stored as diag_* metrics.",
    "statistics": "Seed means; detection and recovery as run fractions; paired t-CI for energy.",
    "practical_significance_threshold": 0.01,
}
out = Path(__file__).with_name("E019_fault_robustness.json")
out.write_text(json.dumps(spec, indent=1), encoding="utf-8")
print(out)
