"""Pre-registered spec for E021: heat-reuse economics with an approach-dependent dry cooler.

E012's warm-water hypotheses could not pass because the legacy plant's fan power ignored approach
temperature. E021 re-asks the question with the effectiveness-NTU dry cooler (plant_model = 1, Stage 1),
keeping the legacy plant as the reference, and adds the economics: how much extra electricity a supply floor
costs per kWh of reusable heat it creates, compared with lifting cold-loop heat with a heat pump.

Written and committed before any E021 cell ran. Usage:  python experiments/make_spec_e021.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "experiments"
vf = json.loads((ROOT / "data" / "calibration" / "M001_vf_fit.json").read_text())
m001 = json.loads((ROOT / "data" / "calibration" / "M001_calibration.json").read_text())
WORLDS = {"registry": {},
          "rtx5070": {**{k: v["value"] for k, v in m001["overrides"].items()}, "kappa_leak": 0.02,
                      "p_leak_ref": vf["fit"]["p_leak_ref"], "v_min_ratio": vf["fit"]["v_min_ratio"],
                      "vf_knee": vf["fit"]["vf_knee"]}}
PLANTS = {"legacy": {"plant_model": 0}, "ntu": {"plant_model": 1},
          "ntu_fan_hi": {"plant_model": 1, "fan_ratio": 0.04}, "ntu_fan_lo": {"plant_model": 1, "fan_ratio": 0.01}}
FLOORS = {"none": 12.0, "f35": 35.0, "f40": 40.0, "f44": 44.0}   # t_sup_max is 45 C
AMB = [8.0, 20.0, 30.0]
variants = [{"label": f"{w}|{pl}|{fl}|amb{a:.0f}", "param_overrides": {**wo, **po, "t_sup_min": fv, "warm_start": 1.0},
             "scenario_overrides": {"t_amb": a}}
            for w, wo in WORLDS.items() for pl, po in PLANTS.items() for fl, fv in FLOORS.items() for a in AMB]

spec = {
    "key": "E021",
    "title": "Heat-reuse economics with an approach-dependent dry cooler",
    "research_question": "When the dry cooler's fan power depends on approach temperature, when does warmer coolant reduce "
                         "cooling electricity, how much chip leakage does it add, how much reusable heat does it create, and "
                         "what does a supply floor cost per kWh of reusable heat compared with a heat pump?",
    "hypothesis": (
        "Conditions: 2 parameter worlds (registry; RTX 5070-derived, as E012) x 4 plants (legacy; NTU dry cooler with "
        "fan_ratio 0.02 / 0.04 / 0.01) x 4 supply floors (none = 12 C, 35, 40, 44 C; t_sup_max is 45 C) x 3 ambients (8, 20, 30 C); S1 load "
        "profile, 4 h, instant plant, joint_fb; 5 seeds. Reusable heat = return water >= 45 C (t_reuse_min). "
        "H1 (fixing the plant moves the optimum): without a floor, joint_fb's mean supply with the NTU plant (fan 0.02) is "
        "at least 1 K warmer than with the legacy plant in all 6 world x ambient conditions. "
        "H2 (but not to reuse temperatures): without a floor, the NTU plant's (fan 0.02) mean supply stays below 35 C at "
        "8 and 20 C ambient in both worlds. "
        "H3 (real silicon tolerates warmth better): at 8 and 20 C ambient the warming in H1 is larger in the RTX 5070 "
        "world than in the registry world. "
        "H4 (the floor gets cheaper): at 8 and 20 C ambient, in both worlds, the 40 C floor's energy cost (energy per "
        "successful task, floor vs none, paired) is lower with the NTU plant (fan 0.02) than with the legacy plant. "
        "H5 (fan cost sets the optimum): without a floor, at 8 and 20 C ambient in both worlds, mean supply orders as "
        "fan 0.04 >= fan 0.02 >= fan 0.01 (NTU). "
        "H6 (direct reuse is cheap per kWh): in the RTX 5070 world, with the NTU plant (fan 0.02) and with the legacy "
        "plant, the 44 C floor's extra grid electricity per kWh of reusable heat gained is below 0.10 kWh_el/kWh_th at 8 "
        "and 20 C ambient. "
        "H7 (warm loop beats a heat pump): in the same conditions as H6, that ratio is lower than the electricity a heat "
        "pump would need to lift the no-floor return water to 45 C + 2 K (heat_pump.upgrade with eta_II 0.5, 3 K "
        "approaches; evaluated at the run's mean return temperature). "
        "Descriptive: break-even heat-to-electricity price ratios per condition, and sensitivity to fan cost."),
    "null_hypothesis": "With an approach-dependent dry cooler, the energy-optimal supply and the cost of warm-water reuse "
                       "are the same as with the legacy plant.",
    "independent_variables": ["world (2)", "plant (4)", "supply floor (4)", "ambient (3)"],
    "dependent_variables": ["T_sup_mean_C", "T_ret_mean_C", "E_per_success_kJ", "E_grid_kWh", "E_it_kWh", "E_fan_kWh",
                            "E_chiller_kWh", "E_pump_kWh", "Q_reusable_kWh", "Q_rejected_kWh"],
    "controlled_variables": ["S1 load profile (mean 0.5, amplitude 0.25)", "seeds 0-4", "warm start", "instant plant",
                             "policy joint_fb", "t_reuse_min 45 C"],
    "baseline": "legacy plant within each world, floor and ambient; no floor within each world, plant and ambient",
    "configuration": f"Worlds {WORLDS}. Plants {PLANTS}. Floors {FLOORS}. Ambient {AMB}.",
    "evaluation_criteria": "Mean supply as seed means; energy as paired relative differences with 95% t-CI; ratios "
                           "from seed-mean energies and heats.",
    "sample_size": "5 seeds (paired), 480 runs.",
    "randomization": "Workloads drawn per seed and shared across all variants.",
    "measurement_boundary": "Simulated facility electricity (IT, conversion, pump, fans, chiller) of one node; reusable heat "
                            "is heat leaving at >= 45 C, assumed fully demanded (an upper bound on its value); heat-pump "
                            "electricity is computed in analysis, not simulated; no heat-customer dynamics.",
    "known_limitations": (
        "NTU dry-cooler parameters are class F; the fan-ratio variants are a sensitivity, not a calibration. Constant ambient "
        "per run, no seasonal heat demand, no heat price model beyond a ratio. Heat-pump comparison uses mean return "
        "temperature. Simulation only."),
    "disclosure": (
        "Known before registration: E012's results and audit; the NTU dry cooler's fan power at the node's design heat "
        "(100 W at 25 C supply and 20 C ambient, ~14 W at 30 C, ~4 W at 35 C); a back-of-envelope estimate (PHASE_REPORT, "
        "E012) that with a cubic fan law the optimum approach would be ~6-8 K. One 30-minute S1 run with plant_model 1 "
        "(unit test: fan energy lower than legacy). No E021 cell was run before registration."),
    "design": {"scenarios": ["S1_moderate"], "policies": ["joint_fb"], "seeds": [0, 1, 2, 3, 4], "timeseries_seeds": [0],
               "variants": variants},
}
base = json.loads((HERE / "E001_policy_benchmark.json").read_text())
for k in ("data_collection", "statistics", "practical_significance_threshold"):
    if k in base:
        spec[k] = base[k]

if __name__ == "__main__":
    (HERE / "E021_heat_reuse.json").write_text(json.dumps(spec, indent=2))
    print(f"wrote E021_heat_reuse.json: {len(variants)} variants, {len(variants) * 5} runs")
