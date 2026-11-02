"""Pre-register E022 (grid-to-inference coordination: demand-response cap, deferral, cold storage)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ueic.facility.cluster import make_topology  # noqa: E402

topo = make_topology(1, 4, 8, chain=2, hydraulic_spread=0.5)
CAP = [[3600.0, 5400.0, 15000.0]]
arms = {
    "none": {"grid_caps": CAP, "enforce_caps": False},
    "cap": {"grid_caps": CAP},
    "cap_defer": {"grid_caps": CAP, "defer_during_cap": True},
    "cap_storage": {"grid_caps": CAP, "storage_kWh_th": 6.0, "storage_charge": [[1800.0, 3600.0, 4000.0]]},
    "cap_defer_storage": {"grid_caps": CAP, "defer_during_cap": True, "storage_kWh_th": 6.0,
                          "storage_charge": [[1800.0, 3600.0, 4000.0]]},
}
conds = []
for amb in (20.0, 30.0):
    for ak, extra in arms.items():
        conds.append({"label": f"amb{amb:.0f}|{ak}", "topology": topo, "jobs": {"load": 0.75},
                      "facility": {"dt": 2.0, "duration_s": 7200.0, "drain_s": 1800.0, "T_amb": amb, "supply": "fixed",
                                   "T_set": 25.0, "price_profile": "tou", "carbon_profile": "diurnal",
                                   "t0_clock_s": 15 * 3600.0, **extra},
                      "params": {"plant_model": 1}})
spec = {
    "key": "E022", "kind": "facility",
    "title": "Grid-to-inference coordination: a demand-response cap with IT capping, job deferral and cold storage",
    "research_question": "When the grid asks a facility to stay under a power cap for 30 minutes, how much do IT power "
                         "capping, deferring flexible jobs and pre-charged cold storage each contribute to compliance, "
                         "completed work and on-time service, and do energy, cost and emissions move together?",
    "hypothesis": (
        "32 GPUs (4 nodes, series pairs, spread 0.5), load 0.75, supply fixed 25 C, NTU plant, ambient 20 and 30 C; "
        "simulation starts 15:00; cap 15 kW on facility grid power from 16:00 to 16:30; illustrative TOU tariff "
        "(0.10 off-peak, 0.30 from 16:00 to 21:00) and illustrative diurnal carbon intensity. Arms: none (cap "
        "accounted, not enforced), cap (EMS converts the grid cap to an IT limit using the previous step's non-IT "
        "power; clocks scaled), cap_defer (+ hold deferrable jobs: deadline - window end >= 1.5 x remaining work), "
        "cap_storage (+ 6 kWh_th cold storage charged at 4 kW_th from 15:30 to 16:00 at a 12 C charging temperature, "
        "5% loss, replacing chiller work during the cap), cap_defer_storage. Paired by seed. H1: with 'cap', energy "
        "above the cap is at most 2% of the event's grid energy at both ambients (seed means). H2: cap_defer's on-time "
        "fraction is at least cap's at both ambients (seed means). H3: at 30 C, cap_storage completes at least 3% more "
        "work during the event than cap (paired, 95% CI above 0); at 20 C the difference is below 1% in magnitude "
        "(expected null: little chiller work to replace). H4 (energy is not cost): at 30 C, cap_storage uses more "
        "total grid energy than cap while costing less (seed means). H5: without enforcement ('none') the cap is "
        "exceeded in every seed (the cap binds). Descriptive: emissions, deferrals, storage use, max exceedance."),
    "null_hypothesis": "Capping, deferral and storage make no difference to compliance, work during the event, service, "
                       "energy or cost.",
    "independent_variables": ["arm (5)", "ambient (2)"],
    "dependent_variables": ["E_above_cap_kWh", "E_event_kWh", "max_exceed_kW", "t_over_cap_s", "work_in_event_gpu_s",
                            "on_time_frac", "E_grid_kWh", "cost", "co2_kg", "deferrals", "storage_used_kWh_th",
                            "storage_charge_kWh_el"],
    "controlled_variables": ["identical job streams per seed", "same topology, supply and plant", "least_loaded placement"],
    "baseline": "cap (for deferral and storage); none (for the cap itself)",
    "configuration": {"arms": arms},
    "evaluation_criteria": "Paired relative differences per seed with 95% t-CI; seed means for fractions and ratios.",
    "sample_size": "5 seeds x 10 conditions = 50 runs.",
    "randomization": "Job streams drawn per seed, shared by all arms.",
    "measurement_boundary": "Simulated facility grid power (IT / conversion, pumps, fans, chiller, storage charging); "
                            "cost and emissions from illustrative signals, reported separately from energy.",
    "known_limitations": "Storage modelled as a heat reservoir replacing chiller duty (no tank temperatures or "
                         "flow constraints); fan power for rejecting charging heat ignored; EMS has a one-step lag; "
                         "tariff and carbon shapes are illustrative; one cap event.",
    "known_confounders": ["deferral moves work after the window, which can push it into the peak tariff period"],
    "disclosure": "Before registration, one exploratory uncapped run at 30 C ambient (32 GPUs, load 0.75, supply 25 C) "
                  "was used to choose the cap level: mean grid power ~18.6 kW from 16:00 to 16:30, chiller ~8% of "
                  "facility energy. No E022 cell was run before registration.",
    "design": {"seeds": [0, 1, 2, 3, 4], "timeseries_seeds": [0], "schedulers": ["least_loaded"], "conditions": conds},
    "data_collection": "Append-only store; time series for seed 0.",
    "statistics": "Paired by seed; d = (A - B)/B; mean with 95% t-CI.",
    "practical_significance_threshold": 0.03,
}
out = Path(__file__).with_name("E022_grid_coordination.json")
out.write_text(json.dumps(spec, indent=1))
print(out)
