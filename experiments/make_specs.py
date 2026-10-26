"""Generate the pre-registered experiment specs (E001-E005) as JSON.

Run once, review the JSON, then run each spec. Hypotheses and evaluation
criteria are frozen in the database at registration, before any result exists.
Usage:  python experiments/make_specs.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ueic.params import REGISTRY  # noqa: E402

HERE = Path(__file__).resolve().parent
THRESHOLD = 0.01   # practical-significance threshold on relative energy per successful task

COMMON = {
    "data_collection": "Simulator outputs written to the append-only SQLite store; every metric labelled with "
                       "provenance; per-run config SHA-256 and code SHA-256 recorded; time series for selected seeds.",
    "statistics": "Paired by seed (identical workload realisation across levels). Per-seed relative difference "
                  "d=(A-B)/B; mean with two-sided 95% Student-t CI.",
    "practical_significance_threshold": THRESHOLD,
}

E001 = {
    "key": "E001",
    "title": "Policy benchmark: fixed vs compute-only vs cooling-only vs independent vs joint",
    "research_question": "How much facility energy per successful task does each control strategy save relative "
                         "to a fixed conventional policy, and does joint compute-cooling optimisation save more "
                         "than energy-aware compute and cooling controllers running independently?",
    "hypothesis": "H1: joint uses less energy per successful task than independent in at least 4 of 6 scenarios "
                  "(paired 95% CI entirely below 0), without more SLO violations or thermal-limit exceedances. "
                  "H2: every optimising policy uses less energy per successful task than fixed in every scenario.",
    "null_hypothesis": "Joint and independent do not differ (CI includes 0) or differ by less than the practical "
                       "threshold.",
    "independent_variables": ["policy (5 levels)", "scenario (6 levels)"],
    "dependent_variables": ["E_per_success_kJ (primary)", "E_grid_kWh", "E_it_kWh", "E_cooling_kWh",
                            "E_chiller_kWh", "success_rate", "slo_violations", "latency_p95_s", "peak_T_j_C",
                            "chip_s_over_target", "chip_s_throttled", "Q_reusable_kWh", "Ex_rejected_kWh"],
    "controlled_variables": ["workload realisation per seed", "all registry parameters at defaults",
                             "4 h arrival window + drain", "dt=1 s", "60 s control interval",
                             "thermal target 80 C / hardware throttle 85 C", "controller model = true plant"],
    "baseline": "fixed: full clock when busy, 18 C supply, design flow",
    "configuration": "8 accelerators on one liquid loop; dry cooler + trim chiller; see parameter registry",
    "evaluation_criteria": f"Primary: paired relative difference in E_per_success_kJ. A difference is 'meaningful' "
                           f"only if the whole 95% CI lies beyond {THRESHOLD:.0%}. Quality guard: success_rate and "
                           f"SLO violations must not worsen relative to the comparator. Thermal guard: zero "
                           f"chip-seconds throttled.",
    "known_limitations": "Synthetic workload (class F); controller has a perfect model of the plant; quasi-steady "
                         "plant without loop thermal mass; single node; constant ambient per scenario.",
    "design": {"scenarios": ["S1_moderate", "S2_high_load", "S3_hot", "S4_cool", "S5_memory_heavy",
                             "S6_degraded_cooling"],
               "policies": ["fixed", "compute_only", "cooling_only", "independent", "joint"],
               "seeds": list(range(10)), "timeseries_seeds": [0]},
    **COMMON,
}

SENS_PARAMS = ["kappa_leak", "p_leak_ref", "p_dyn_max", "p_static_other", "idle_dyn_frac", "activity_memory",
               "v_min_ratio", "beta_compute", "beta_memory", "c_th", "r_cond", "r_conv_ref", "n_conv", "dp_ref",
               "m_dp", "eta_pump", "eta_ii_chiller", "dt_evap", "dt_cond", "dt_drycooler", "fan_ratio",
               "eta_conv", "job_work_mean", "frac_memory", "fixed_t_sup"]
variants = [{"label": "default"}]
for name in SENS_PARAMS:
    p = REGISTRY[name]
    for end, val in (("low", p.low), ("high", p.high)):
        variants.append({"label": f"{name}={end}", "param": name, "end": end, "param_overrides": {name: val}})

E002 = {
    "key": "E002",
    "title": "One-at-a-time sensitivity of policy comparisons to uncertain assumptions",
    "research_question": "Which uncertain (class E/F) assumptions materially change the conclusions of E001 for "
                         "joint vs independent and joint vs fixed?",
    "hypothesis": "The sign of (joint - independent) energy per successful task is non-positive for every "
                  "one-at-a-time variation; its magnitude is most sensitive to the leakage parameters "
                  "(kappa_leak, p_leak_ref). The joint-vs-fixed saving is most sensitive to the V-f curve "
                  "(v_min_ratio) and memory-boundness (beta_memory).",
    "null_hypothesis": "Some variation reverses the sign of joint - independent, or other parameters dominate.",
    "independent_variables": ["one parameter at its low or high bound (25 parameters x 2)", "policy (3 levels)"],
    "dependent_variables": ["E_per_success_kJ", "chip_s_throttled", "slo_violations"],
    "controlled_variables": ["scenario S1_moderate shortened to a 2 h arrival window (one load cycle)",
                             "all other parameters at defaults", "seeds 0-2"],
    "baseline": "default variant; fixed policy within each variant",
    "configuration": "As E001, S1 scenario, 2 h",
    "evaluation_criteria": "For each variant: paired relative difference joint vs independent and joint vs fixed "
                           "with 95% CI (n=3 seeds, so CIs are wide; used for ranking, not confirmation). Rank "
                           "parameters by the swing (high minus low) of the mean difference.",
    "known_limitations": "One-at-a-time design misses interactions; only 3 seeds per cell; ranges are judgement "
                         "calls recorded in the registry.",
    "design": {"scenarios": ["S1_moderate"], "policies": ["fixed", "independent", "joint"], "seeds": [0, 1, 2],
               "scenario_overrides": {"duration_s": 7200.0, "load_period_s": 7200.0},
               "timeseries_seeds": [], "variants": variants},
    **COMMON,
}

Ep = 0.6 * 0.92 + 0.4 * 0.30  # registry defaults: frac_easy, p_small_easy, p_small_hard
rv = REGISTRY["verify_cost_ratio"].value
route = {"routing": True}
E003 = {
    "key": "E003",
    "title": "Model-routing cascade with verification: realised energy vs analytic work savings",
    "research_question": "Does a verified small-model cascade reduce facility energy per successful task, and how "
                         "does the realised energy saving compare with the analytic saving in computational work?",
    "hypothesis": f"With a perfect verifier the cascade reduces energy per successful task if and only if "
                  f"(small cost + verifier cost) < E[p_small] = {Ep:.3f}; the realised fractional energy saving is "
                  f"smaller than the fractional work saving because idle, static, conversion and cooling energy do "
                  f"not scale with work. A verifier with false accepts lowers task success.",
    "null_hypothesis": "Energy saving tracks work saving one-to-one, or the break-even point differs from analytic.",
    "independent_variables": ["routing on/off and small-model cost ratio", "verifier false-accept rate", "policy"],
    "dependent_variables": ["E_per_success_kJ", "work_enqueued_s", "escalations", "success_rate",
                            "latency_p95_s", "slo_violations"],
    "controlled_variables": ["scenario S1_moderate", "task arrivals and outcome random numbers per seed"],
    "baseline": "routing off (large model only) under the same policy",
    "configuration": "All routing parameters are hypothetical (class F); see registry",
    "evaluation_criteria": "Paired relative difference of each routing variant vs routing_off within policy; "
                           "compare with analytic work ratio from workload.routing_expectations().",
    "known_limitations": "Quality model is a Bernoulli placeholder, not a measured model evaluation; verifier "
                         "cost and accuracy are assumed; no batching effects.",
    "design": {"scenarios": ["S1_moderate"], "policies": ["fixed", "joint"], "seeds": list(range(10)),
               "timeseries_seeds": [], "variants": [
                   {"label": "routing_off"},
                   {"label": "rs+rv=0.25", "scenario_overrides": route},
                   {"label": "rs+rv=0.45", "scenario_overrides": route, "param_overrides": {"small_cost_ratio": 0.40}},
                   {"label": "rs+rv=0.60", "scenario_overrides": route, "param_overrides": {"small_cost_ratio": 0.55}},
                   {"label": "rs+rv=0.67", "scenario_overrides": route, "param_overrides": {"small_cost_ratio": round(Ep - rv, 3)}},
                   {"label": "rs+rv=0.80", "scenario_overrides": route, "param_overrides": {"small_cost_ratio": 0.75}},
                   {"label": "rs+rv=0.25,false_accept=0.10", "scenario_overrides": route,
                    "param_overrides": {"verifier_false_accept": 0.10}},
               ]},
    **COMMON,
}

E004 = {
    "key": "E004",
    "title": "Numerical convergence in the time step",
    "research_question": "Are E001-E003 results converged with respect to the simulation time step?",
    "hypothesis": "Grid energy and energy per successful task change by less than 0.5% between dt=0.5 s and "
                  "dt=1 s for both fixed and joint policies.",
    "null_hypothesis": "Change exceeds 0.5%.",
    "independent_variables": ["dt in {0.25, 0.5, 1, 2} s", "policy"],
    "dependent_variables": ["E_grid_kWh", "E_per_success_kJ", "peak_T_j_C", "latency_p95_s"],
    "controlled_variables": ["scenario S1 shortened to 1 h", "seeds 0-1"],
    "baseline": "dt=0.25 s",
    "configuration": "As E001",
    "evaluation_criteria": "Relative difference vs dt=0.25 s per policy and seed.",
    "known_limitations": "Convergence of a time-stepped scheme does not validate the physics itself.",
    "design": {"scenarios": ["S1_moderate"], "policies": ["fixed", "joint"], "seeds": [0, 1],
               "scenario_overrides": {"duration_s": 3600.0, "load_period_s": 3600.0}, "timeseries_seeds": [],
               "variants": [{"label": f"dt={d}", "param_overrides": {"dt": d}} for d in (0.25, 0.5, 1.0, 2.0)]},
    **COMMON,
}

E005 = {
    "key": "E005",
    "title": "Robustness of model-based control to digital-twin mismatch",
    "research_question": "How much of the joint controller's advantage survives when its digital twin is wrong, "
                         "and do thermal limits still hold?",
    "hypothesis": "When the twin underestimates leakage or overestimates cold-plate performance, the joint "
                  "controller exceeds the 80 C thermal target for some chip-seconds and loses part or all of its "
                  "advantage over independent control; hardware protection still bounds temperature.",
    "null_hypothesis": "Joint retains its advantage and meets the thermal target under every mismatch.",
    "independent_variables": ["twin-vs-truth mismatch (3 cases, each with a matched-truth reference)", "policy",
                              "scenario"],
    "dependent_variables": ["E_per_success_kJ", "chip_s_over_target", "chip_s_throttled", "peak_T_j_C"],
    "controlled_variables": ["seeds 0-4", "4 h window"],
    "baseline": "same true plant with a correct twin",
    "configuration": "Mismatch applied only to the controller's model config (model_param_overrides).",
    "evaluation_criteria": "Within each truth case: joint vs independent paired difference with correct vs wrong "
                           "twin; count chip-seconds over target.",
    "known_limitations": "Mismatches are single-parameter-group and static; real drift is gradual and correlated.",
    "design": {"scenarios": ["S1_moderate", "S3_hot"], "policies": ["independent", "joint"],
               "seeds": [0, 1, 2, 3, 4], "timeseries_seeds": [0],
               "variants": [
                   {"label": "high_leak|twin_correct", "param_overrides": {"kappa_leak": 0.03, "p_leak_ref": 130.0}},
                   {"label": "high_leak|twin_low_leak", "param_overrides": {"kappa_leak": 0.03, "p_leak_ref": 130.0},
                    "model_param_overrides": {"kappa_leak": 0.012, "p_leak_ref": 70.0}},
                   {"label": "fouled_plate|twin_correct", "param_overrides": {"r_conv_ref": 0.026}},
                   {"label": "fouled_plate|twin_clean", "param_overrides": {"r_conv_ref": 0.026},
                    "model_param_overrides": {"r_conv_ref": 0.015}},
                   {"label": "poor_chiller|twin_correct", "param_overrides": {"eta_ii_chiller": 0.35}},
                   {"label": "poor_chiller|twin_optimistic", "param_overrides": {"eta_ii_chiller": 0.35},
                    "model_param_overrides": {"eta_ii_chiller": 0.55}},
               ]},
    **COMMON,
}

if __name__ == "__main__":
    for spec, fname in ((E001, "E001_policy_benchmark.json"), (E002, "E002_sensitivity.json"),
                        (E003, "E003_routing_cascade.json"), (E004, "E004_timestep_convergence.json"),
                        (E005, "E005_model_mismatch.json")):
        (HERE / fname).write_text(json.dumps(spec, indent=2))
        print("wrote", fname)
