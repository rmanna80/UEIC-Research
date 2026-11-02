"""Pre-register E020 (multi-node joint optimisation) on the Stage 6 facility simulator."""
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ueic.facility.cluster import make_topology  # noqa: E402

scales = {"n1": (1, 1), "n4": (1, 4), "n16": (4, 4)}
arms = {
    "independent": ({"supply": "fixed", "T_set": 25.0, "valves": "equal"}, "least_loaded"),
    "warm": ({"supply": "warmest_safe", "valves": "equal"}, "least_loaded"),
    "warm_valves": ({"supply": "warmest_safe", "valves": "heat_proportional"}, "least_loaded"),
    "joint": ({"supply": "warmest_safe", "valves": "heat_proportional"}, "thermal_credit"),
}
conds = []
for sk, (r, n) in scales.items():
    topo = make_topology(r, n, 8, chain=2, hydraulic_spread=1.0 if r * n > 1 else 0.0)
    for amb in (20.0, 30.0):
        for ak, (fac, sch) in arms.items():
            conds.append({"label": f"{sk}|amb{amb:.0f}|{ak}", "topology": topo, "jobs": {"load": 0.75},
                          "facility": {"dt": 2.0, "duration_s": 7200.0, "drain_s": 1800.0, "T_amb": amb,
                                       "supply_margin_K": 3.0, **fac},
                          "params": {"plant_model": 1}, "schedulers": [sch]})
spec = {
    "key": "E020", "kind": "facility",
    "title": "Multi-node joint optimisation: supply temperature, flow distribution and placement, 1 to 16 nodes",
    "research_question": "With a shared plant, unequal branch hydraulics and series cold plates, does jointly choosing "
                         "the supply temperature, the valve openings and the placement lower facility energy per "
                         "on-time job compared with independent control (fixed cold supply, equal valves, least-loaded "
                         "placement), and does the benefit hold from 1 to 16 nodes?",
    "hypothesis": (
        "Scales 1 node (8 GPUs), 4 nodes (1 rack), 16 nodes (4 racks); series pairs; branch resistance spread 1.0 "
        "across nodes (none for one node); load 0.75; ambient 20 and 30 C; NTU plant; 2 h + 30 min drain. Arms: "
        "independent = supply fixed at 25 C, equal valves, least_loaded; warm = warmest-safe supply (3 K margin), "
        "equal valves, least_loaded; warm_valves = warm + heat-proportional valves; joint = warm_valves + "
        "thermal_credit. Paired by seed. H1: joint's facility energy per on-time job is at least 3% lower than "
        "independent's at every scale and ambient (95% CI below 0). H2: joint's on-time fraction is within 1 "
        "percentage point of independent's at every scale and ambient (seed means). H3: the joint-vs-independent "
        "energy benefit at 16 nodes is at least the 1-node benefit minus 1 percentage point, at both ambients. H4: "
        "at 16 nodes, warm_valves has lower energy per on-time job than warm (95% CI below 0) at both ambients. "
        "Descriptive: mean supply, fan, chiller and pump energy, chip-seconds above target, throttling."),
    "null_hypothesis": "Joint control does not lower facility energy per on-time job relative to independent control.",
    "independent_variables": ["arm (4)", "scale (3)", "ambient (2)"],
    "dependent_variables": ["E_per_on_time_job_kJ", "on_time_frac", "E_grid_kWh", "E_it_kWh", "E_fan_kWh",
                            "E_chiller_kWh", "E_pump_kWh", "T_sup_mean_C", "chip_s_over_target", "throttle_gpu_s"],
    "controlled_variables": ["identical job streams per (scale, ambient, seed) across arms", "same hardware layers",
                             "same pump flow (factor 1)", "dt 2 s"],
    "baseline": "independent",
    "configuration": {"arms": {k: {"facility": v[0], "scheduler": v[1]} for k, v in arms.items()}},
    "evaluation_criteria": "Paired relative differences per seed, mean and 95% t-CI; seed means for fractions.",
    "sample_size": "5 seeds x 24 conditions = 120 runs.",
    "randomization": "Job streams drawn per (condition topology size, seed); arms share them.",
    "measurement_boundary": "Simulated facility electricity of the cluster (IT / conversion, pumps, fans, chiller).",
    "known_limitations": "Instant plant (no supply lag; E015 covers lag on one node); warmest-safe supply uses measured "
                         "state with a fixed 3 K margin; valve model has no actuator dynamics; pump flow fixed; "
                         "illustrative topology; leakage and plant parameters are registry placeholders (class F).",
    "known_confounders": ["job streams differ between scales (different GPU counts), so scales are compared through "
                          "paired within-scale ratios only"],
    "disclosure": "Before registration: E018's design, unit-test runs of the facility simulator, and E012/E021 "
                  "expectations that warmer supply saves fan and chiller energy but adds leakage. No E020 cell was "
                  "run before registration.",
    "design": {"seeds": [0, 1, 2, 3, 4], "timeseries_seeds": [0], "schedulers": ["least_loaded"], "conditions": conds},
    "data_collection": "Append-only store; per-run config and code hashes; time series for seed 0.",
    "statistics": "Paired by seed; d = (A - B)/B; mean with 95% t-CI.",
    "practical_significance_threshold": 0.03,
}
out = Path(__file__).with_name("E020_multinode_joint.json")
out.write_text(json.dumps(spec, indent=1))
print(out)
