"""Pre-register E018 (thermal-credit scheduling) on the Stage 6 facility simulator."""
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ueic.facility.cluster import make_topology  # noqa: E402

TYPES = {"A": {}, "B": {"p_dyn_scale": 1.4, "r_cond_scale": 1.3, "mem_GB": 141.0, "speed": 1.3}}
base_fac = {"dt": 2.0, "duration_s": 7200.0, "drain_s": 1800.0, "T_amb": 20.0, "supply": "fixed"}
conds = [
    ("C1_uniform_moderate", make_topology(2, 2, 8, chain=1), {"load": 0.5}, {**base_fac, "T_set": 30.0}),
    ("C2_series_unequal_high", make_topology(2, 2, 8, chain=2, hydraulic_spread=1.0), {"load": 0.85}, {**base_fac, "T_set": 35.0}),
    ("C3_warm_supply_high", make_topology(2, 2, 8, chain=2, hydraulic_spread=1.0), {"load": 0.85}, {**base_fac, "T_set": 40.0}),
    ("C4_rack_capped_bursty", make_topology(2, 2, 8, chain=2, hydraulic_spread=0.5, rack_limit_W=7000.0),
     {"load": 0.6, "bursts": [[1800.0, 900.0, 0.4], [5400.0, 900.0, 0.4]]}, {**base_fac, "T_set": 35.0}),
    ("C5_heterogeneous", make_topology(2, 2, 8, chain=2, hydraulic_spread=0.5, types=TYPES, type_mix=["A", "B"]),
     {"load": 0.8}, {**base_fac, "T_set": 35.0}),
]
scheds = ["round_robin", "least_loaded", "power_aware", "temperature_aware", "thermal_credit", "thermal_placement"]
spec = {
    "key": "E018", "kind": "facility",
    "title": "Thermal-credit scheduling vs round-robin, least-loaded, power-aware and temperature-aware placement",
    "research_question": "Under equal hardware protection (thermal throttle, rack power caps) and equal cooling, does "
                         "placing jobs by thermal capacity budgets (and lowering clocks or holding jobs when no placement "
                         "stays within budget) improve completed on-time work, facility energy per on-time job and "
                         "thermal safety, and when does it give no benefit?",
    "hypothesis": (
        "32 GPUs (2 racks x 2 nodes x 8), 2 h arrivals + 30 min drain, NTU plant, 5 conditions: C1 uniform cooling "
        "(parallel plates, equal hydraulics), load 0.5, supply 30 C; C2 series pairs, farthest node 2x branch "
        "resistance, load 0.85, supply 35 C; C3 as C2 with supply 40 C; C4 series pairs, spread 0.5, rack IT limit "
        "7 kW, load 0.6 with two 15-min bursts (+0.4); C5 heterogeneous nodes (type A and type B: 1.4x dynamic power, "
        "1.3x conduction resistance, 1.3x speed, 141 GB), series pairs, spread 0.5, load 0.8, supply 35 C. Paired by "
        "seed (identical job streams). H1: in C2, C3 and C5, thermal_credit's facility energy per on-time job is lower "
        "than each of the four baselines (round_robin, least_loaded, power_aware, temperature_aware) with the 95% CI "
        "of the paired relative difference below 0 and the mean at most -2%. H2: in every condition, thermal_credit's "
        "chip-seconds above t_target are at most temperature_aware's (seed means), and in C2, C3 and C5 at most half "
        "of least_loaded's. H3: in C2, C3 and C5, thermal_credit's on-time fraction is no more than 2 percentage "
        "points below the best baseline's (seed means). H4 (expected null): in C1, thermal_credit and least_loaded "
        "differ by less than 1% in energy per on-time job and by less than 1 percentage point in on-time fraction. "
        "H5: in C4, thermal_credit's on-time fraction is at least power_aware's (seed means). Descriptive: "
        "thermal_placement (placement rule only, full clock, never holds) separates the placement effect from the "
        "clock/admission effect; admission decision counts; throttle GPU-seconds; cap steps; waits."),
    "null_hypothesis": "Thermal-credit scheduling performs no better than the baselines in energy, service or safety.",
    "independent_variables": ["scheduler (6)", "condition (5)"],
    "dependent_variables": ["E_per_on_time_job_kJ", "on_time_frac", "jobs_on_time", "work_done_gpu_s", "E_grid_kWh",
                            "chip_s_over_target", "throttle_gpu_s", "cap_steps", "mean_wait_s", "p95_wait_s", "T_max_C"],
    "controlled_variables": ["identical job streams per seed", "EDF queue order with backfilling for every scheduler",
                             "same hardware throttle and power caps", "same plant and supply", "dt 2 s"],
    "baseline": "round_robin, least_loaded, power_aware, temperature_aware",
    "configuration": {"conditions": [c[0] for c in conds], "thermal_credit": "horizon cap 600 s, margin 2 K, reduced "
                      "clocks 0.9/0.8/0.7/0.6, hold window 60 s"},
    "evaluation_criteria": "Paired relative differences per seed, mean and two-sided 95% Student-t CI; seed means for "
                           "fractions and counts.",
    "sample_size": "5 seeds x 5 conditions x 6 schedulers = 150 runs (each ~400 jobs).",
    "randomization": "Job streams drawn per (condition, seed) and shared by all schedulers.",
    "measurement_boundary": "Simulated facility electricity (IT / conversion efficiency, pumps, dry-cooler fans, "
                            "chiller) of 32 GPUs; jobs counted on time if finished by their deadline; unfinished jobs "
                            "at the end of the drain count as not on time.",
    "known_limitations": "Synthetic jobs and illustrative accelerator types; lumped junction model; instant supply "
                         "(no plant lag); no migration; communication costs are stated constants; thermal-credit "
                         "parameters were set by hand, not tuned; one topology size.",
    "known_confounders": ["thermal_credit may lower clocks, which changes IT energy as well as temperatures; the "
                          "thermal_placement ablation separates this"],
    "disclosure": "Before registration, exploratory runs while building the simulator: one 1-h run (2x2 nodes, "
                  "series pairs, spread 0.6, rack limit 9 kW, load 0.8, supply 35 C, seed 1) gave thermal_credit "
                  "~11% lower energy per job, 60% fewer chip-seconds above target and a slightly lower on-time fraction "
                  "(0.977 vs 0.991) than least_loaded; unit-test runs. No E018 cell was run before registration.",
    "design": {"seeds": [0, 1, 2, 3, 4], "timeseries_seeds": [0], "schedulers": scheds,
               "conditions": [{"label": l, "topology": t, "jobs": j, "facility": f, "params": {"plant_model": 1}}
                              for l, t, j, f in conds]},
    "data_collection": "Append-only store; per-run config and code hashes; time series for seed 0.",
    "statistics": "Paired by seed; d = (A - B)/B; mean with 95% t-CI; practical threshold 2% (energy), 2 points (service).",
    "practical_significance_threshold": 0.02,
}
out = Path(__file__).with_name("E018_thermal_scheduling.json")
out.write_text(json.dumps(spec, indent=1))
print(out)
