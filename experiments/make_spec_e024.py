"""Pre-register E024 (integrated ablation) on the facility simulator: 2^4 factorial of the Stage 5-7 components."""
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ueic.facility.cluster import make_topology  # noqa: E402

topo = make_topology(4, 4, 8, chain=2, hydraulic_spread=1.0)
conds = []
for S, V, T, D in itertools.product((0, 1), repeat=4):
    label = f"S{S}V{V}T{T}D{D}"
    fac = {"dt": 2.0, "duration_s": 7200.0, "drain_s": 1800.0, "T_amb": 30.0, "supply_margin_K": 3.0,
           "supply": "warmest_safe" if S else "fixed", "T_set": 25.0, "valves": "heat_proportional" if V else "equal",
           "grid_caps": [[3600.0, 5400.0, 60000.0]], "defer_during_cap": bool(D),
           "price_profile": "tou", "carbon_profile": "diurnal", "t0_clock_s": 15 * 3600.0}
    conds.append({"label": label, "topology": topo, "jobs": {"load": 0.75}, "facility": fac,
                  "params": {"plant_model": 1}, "schedulers": ["thermal_credit" if T else "least_loaded"]})
spec = {
    "key": "E024", "kind": "facility",
    "title": "Integrated ablation: warm supply, flow balancing, thermal-credit placement and grid deferral, 2^4 factorial",
    "research_question": "On one 128-GPU simulated facility with a demand-response cap, which of the next-generation "
                         "components lower facility energy per on-time job, do they combine additively, and does the full "
                         "combination keep service and thermal safety?",
    "hypothesis": (
        "16 nodes (4 racks x 4, 8 GPUs each, series pairs, branch resistance spread 1.0), load 0.75, ambient 30 C, NTU "
        "plant, 15:00-17:00 + 30 min drain, a 60 kW grid cap 16:00-16:30 enforced in every arm. Factors: S warmest-safe "
        "supply (3 K margin) vs fixed 25 C; V heat-proportional valves vs equal; T thermal_credit vs least_loaded; D defer "
        "deferrable jobs during the cap vs not. Paired by seed. H1: the full system (S1V1T1D1) has at least 5% lower "
        "energy per on-time job than the baseline (S0V0T0D0), 95% CI below 0. H2: removing any one component from the "
        "full system raises energy per on-time job (each leave-one-out arm vs full: mean > 0). H3: the full system's "
        "on-time fraction is within 1 percentage point of the baseline's (seed means). H4: the full system's chip-seconds "
        "above t_target are at most the baseline's (seed means). Descriptive: main effects and two-way interactions "
        "(effect coding, seed-mean energy per on-time job), cap compliance, cost and emissions."),
    "null_hypothesis": "No component or combination changes energy per on-time job, service or safety.",
    "independent_variables": ["S (2)", "V (2)", "T (2)", "D (2)"],
    "dependent_variables": ["E_per_on_time_job_kJ", "on_time_frac", "chip_s_over_target", "E_above_cap_kWh", "cost",
                            "co2_kg", "T_sup_mean_C", "E_fan_kWh", "E_chiller_kWh"],
    "controlled_variables": ["identical job streams per seed", "same topology, plant, ambient and cap"],
    "baseline": "S0V0T0D0",
    "configuration": {"factors": {"S": ["fixed 25 C", "warmest_safe"], "V": ["equal", "heat_proportional"],
                                  "T": ["least_loaded", "thermal_credit"], "D": ["no", "defer during cap"]}},
    "evaluation_criteria": "Paired relative differences with 95% t-CI; seed means for fractions; effects from seed means.",
    "sample_size": "16 arms x 5 seeds = 80 runs.",
    "randomization": "Job streams drawn per seed, shared by all arms.",
    "measurement_boundary": "Simulated facility grid power of 128 GPUs (IT / conversion, pumps, fans, chiller).",
    "known_limitations": "Excludes the Stage 3 MPC (single-node simulator) and Stage 8 supervision (separate E019); instant "
                         "plant; illustrative signals; one ambient; hand-set component parameters.",
    "disclosure": "Before registration: E015 and E016 results; the designs (not results) of E018-E022; shortened dry-runs of "
                  "the E018/E020/E022 pipelines in a scratch database (10-minute runs, not representative). No E024 cell was "
                  "run before registration.",
    "design": {"seeds": [0, 1, 2, 3, 4], "timeseries_seeds": [0], "schedulers": ["least_loaded"], "conditions": conds},
    "data_collection": "Append-only store; time series for seed 0.",
    "statistics": "Paired by seed; d = (A - B)/B; mean with 95% t-CI.",
    "practical_significance_threshold": 0.05,
}
out = Path(__file__).with_name("E024_integrated_ablation.json")
out.write_text(json.dumps(spec, indent=1))
print(out)
