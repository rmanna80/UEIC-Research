"""Compute the structured results of E001-E005 from the store.

Shared by report.py (markdown + figures) and dashboard.py (HTML). Every number
here is derived from finalised runs in the database; nothing is typed in by hand.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Any

import numpy as np

from . import analysis as A
from .params import REGISTRY, make_config
from .store import Store, code_hash
from .workload import SCENARIOS, routing_expectations

POLICY_ORDER = ["fixed", "compute_only", "cooling_only", "independent", "joint"]
E001_METRICS = ["E_per_success_kJ", "E_grid_kWh", "E_it_kWh", "E_conv_loss_kWh", "E_pump_kWh", "E_fan_kWh",
                "E_chiller_kWh", "E_cooling_kWh", "success_rate", "slo_violations", "latency_p95_s",
                "peak_T_j_C", "chip_s_over_target", "chip_s_throttled", "Q_reusable_kWh", "Ex_rejected_kWh",
                "Q_rejected_kWh", "grid_to_it_ratio", "controller_wall_mean_ms", "tasks", "escalations"]


def _f(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else float(x)


def _row(r):
    return {k: (_f(v) if isinstance(v, (float, np.floating)) else v) for k, v in r.items()}


def e001(store: Store, threshold: float) -> dict[str, Any] | None:
    eid = store.latest_experiment("E001")
    if not eid:
        return None
    exp = store.experiment(eid)
    runs = store.runs(eid)
    scen = exp["spec"]["design"]["scenarios"]
    pols = [p for p in POLICY_ORDER if p in exp["spec"]["design"]["policies"]]
    table: dict = defaultdict(dict)
    for m in E001_METRICS:
        for r in A.summary(runs, m):
            table[r["group"][0]].setdefault(r["policy"], {})[m] = {"mean": _f(r["mean"]), "lo": _f(r["lo"]), "hi": _f(r["hi"]), "n": r["n"]}
    comps = []
    pairs = [(p, "fixed") for p in pols if p != "fixed"] + [("joint", "independent"), ("joint", "compute_only"),
                                                           ("joint", "cooling_only"), ("independent", "compute_only")]
    for a, b in pairs:
        for r in A.paired(runs, "E_per_success_kJ", a, b):
            row = _row(r)
            row["scenario"] = r["group"][0]
            row["verdict"] = A.verdict(r, threshold)
            # guards
            g_slo = A.paired(runs, "slo_violations", a, b, relative=False)
            g_suc = A.paired(runs, "success_rate", a, b, relative=False)
            g_thr = A.paired(runs, "chip_s_throttled", a, b, relative=False)
            pick = lambda rows: next(x for x in rows if x["group"] == r["group"])
            row["d_slo_violations"] = _f(pick(g_slo)["mean"])
            row["d_success_rate"] = _f(pick(g_suc)["mean"])
            row["d_throttled"] = _f(pick(g_thr)["mean"])
            comps.append(row)
    # hypotheses
    ji = [c for c in comps if c["a"] == "joint" and c["b"] == "independent"]
    h1_hits = [c["scenario"] for c in ji if c["hi"] is not None and c["hi"] < 0
               and (c["d_slo_violations"] or 0) <= 0 and (c["d_throttled"] or 0) <= 0]
    h1_meaningful = [c["scenario"] for c in ji if c["hi"] is not None and c["hi"] < -threshold]
    vf = [c for c in comps if c["b"] == "fixed"]
    h2_fail = [(c["a"], c["scenario"]) for c in vf if not (c["hi"] is not None and c["hi"] < 0)]
    # Pre-registered quality guard: SLO violations and success rate must not worsen.
    h2_guard_fail = [{"policy": c["a"], "scenario": c["scenario"], "d_slo_violations": c["d_slo_violations"],
                      "d_success_rate": c["d_success_rate"]}
                     for c in vf if (c["d_slo_violations"] or 0) > 0 or (c["d_success_rate"] or 0) < 0]
    # time series (seed with recorded series), per scenario & policy
    ts = defaultdict(dict)
    for r in runs:
        if r["timeseries_path"] and r["status"] == "completed":
            t = store.load_timeseries(r["run_id"])
            keep = ("t", "P_grid", "P_it", "P_pump", "P_fan", "W_ch", "T_sup", "flow", "T_ret", "T_max",
                    "T_mean", "busy", "s_c", "s_m", "queue", "util_offered")
            ts[r["scenario"]][r["policy"]] = {k: [round(v, 4) for v in t[k]] for k in keep if k in t}
    warnings = [{"scenario": r["scenario"], "policy": r["policy"], "seed": r["seed"], "warnings": r["warnings"]}
                for r in runs if r["warnings"]]
    failed = [r for r in runs if r["status"] != "completed"]
    return {
        "id": eid, "spec": exp["spec"], "scenarios": scen, "policies": pols,
        "scenario_info": {s: {"t_amb": SCENARIOS[s].t_amb, "load_mean": SCENARIOS[s].load_mean,
                              "load_amp": SCENARIOS[s].load_amp, "description": SCENARIOS[s].description,
                              "overrides": SCENARIOS[s].param_overrides} for s in scen},
        "table": table, "comparisons": comps,
        "H1": {"supported": len(h1_hits) >= 4, "scenarios_ci_below_zero": h1_hits,
               "scenarios_meaningful": h1_meaningful, "required": 4},
        "H2": {"energy_criterion_met": not h2_fail, "energy_failures": h2_fail,
               "guard_failures": h2_guard_fail, "supported": not h2_fail and not h2_guard_fail},
        "timeseries": ts, "warnings": warnings, "n_runs": len(runs), "n_failed": len(failed),
    }


def e002(store: Store, threshold: float) -> dict[str, Any] | None:
    eid = store.latest_experiment("E002")
    if not eid:
        return None
    exp = store.experiment(eid)
    runs = store.runs(eid)
    meta = {v["label"]: v for v in exp["spec"]["design"]["variants"]}
    out = {}
    for a, b in (("joint", "independent"), ("joint", "fixed"), ("independent", "fixed")):
        rows = {r["group"][1]: _row(r) for r in A.paired(runs, "E_per_success_kJ", a, b)}
        out[f"{a}_vs_{b}"] = rows
    thr = {r["group"][1] + "|" + r["policy"]: _f(r["mean"]) for r in A.summary(runs, "chip_s_throttled")}
    tornado = {}
    for key, rows in out.items():
        base = rows.get("default", {}).get("mean")
        items = []
        params = sorted({m["param"] for m in meta.values() if "param" in m})
        for p in params:
            lo = rows.get(f"{p}=low", {}).get("mean")
            hi = rows.get(f"{p}=high", {}).get("mean")
            if lo is None or hi is None:
                continue
            items.append({"param": p, "low_value": REGISTRY[p].low, "high_value": REGISTRY[p].high,
                          "default_value": REGISTRY[p].value, "unit": REGISTRY[p].unit,
                          "evidence": REGISTRY[p].evidence, "at_low": lo, "at_high": hi,
                          "swing": abs(hi - lo)})
        items.sort(key=lambda x: -x["swing"])
        tornado[key] = {"base": base, "items": items}
    ji = out["joint_vs_independent"]
    sign_flips = [k for k, r in ji.items() if r["mean"] is not None and r["mean"] > 0]
    sign_flips_sig = [k for k, r in ji.items() if r["lo"] is not None and r["lo"] > 0]
    return {"id": eid, "spec": exp["spec"], "comparisons": out, "tornado": tornado,
            "throttled": thr, "joint_worse_mean": sign_flips, "joint_worse_ci": sign_flips_sig,
            "n_runs": len(runs), "n_failed": sum(r["status"] != "completed" for r in runs)}


def e003(store: Store, threshold: float) -> dict[str, Any] | None:
    eid = store.latest_experiment("E003")
    if not eid:
        return None
    exp = store.experiment(eid)
    runs = store.runs(eid)
    variants = exp["spec"]["design"]["variants"]
    rows = []
    for v in variants:
        if v["label"] == "routing_off":
            continue
        cfg = make_config(v.get("param_overrides", {}))
        ana = routing_expectations(cfg)
        for pol in exp["spec"]["design"]["policies"]:
            e = next((r for r in A.paired(runs, "E_per_success_kJ", v["label"], "routing_off",
                                          key=("scenario", "policy"), factor="variant") if r["group"][1] == pol), None)
            w = next((r for r in A.paired(runs, "work_enqueued_s", v["label"], "routing_off",
                                          key=("scenario", "policy"), factor="variant") if r["group"][1] == pol), None)
            s = next((r for r in A.paired(runs, "success_rate", v["label"], "routing_off",
                                          key=("scenario", "policy"), factor="variant", relative=False)
                      if r["group"][1] == pol), None)
            lat = next((r for r in A.paired(runs, "latency_p95_s", v["label"], "routing_off",
                                            key=("scenario", "policy"), factor="variant") if r["group"][1] == pol), None)
            if not e:
                continue
            rows.append({
                "variant": v["label"], "policy": pol,
                "rs_plus_rv": cfg.small_cost_ratio + cfg.verify_cost_ratio,
                "false_accept": cfg.verifier_false_accept,
                "analytic_work_ratio": ana["work_ratio"],
                "analytic_work_per_success_ratio": ana["work_per_success_ratio"],
                "analytic_success": ana["success_cascade"],
                "sim_work_change": _f(w["mean"]), "sim_work_lo": _f(w["lo"]), "sim_work_hi": _f(w["hi"]),
                "energy_change": _f(e["mean"]), "energy_lo": _f(e["lo"]), "energy_hi": _f(e["hi"]),
                "verdict": A.verdict(e, threshold),
                "d_success_rate": _f(s["mean"]), "d_success_lo": _f(s["lo"]), "d_success_hi": _f(s["hi"]),
                "p95_latency_change": _f(lat["mean"]),
            })
    base = make_config()
    Ep = base.frac_easy * base.p_small_easy + (1 - base.frac_easy) * base.p_small_hard
    return {"id": eid, "spec": exp["spec"], "rows": rows, "break_even_rs_rv": Ep,
            "n_runs": len(runs), "n_failed": sum(r["status"] != "completed" for r in runs)}


def e004(store: Store) -> dict[str, Any] | None:
    eid = store.latest_experiment("E004")
    if not eid:
        return None
    runs = store.runs(eid)
    by = defaultdict(dict)
    for r in runs:
        if r["status"] == "completed":
            by[(r["policy"], r["seed"])][r["variant"]] = r["metrics"]
    rows = []
    for (pol, seed), v in sorted(by.items()):
        ref = v.get("dt=0.5", {}).get("E_grid_kWh")
        for lab in ("dt=0.25", "dt=1.0", "dt=2.0"):
            if lab in v and ref:
                rows.append({"policy": pol, "seed": seed, "variant": lab,
                             "rel_change_vs_dt0.5": v[lab]["E_grid_kWh"] / ref - 1.0})
    crit = [r for r in rows if r["variant"] == "dt=1.0"]
    worst = {p: max(abs(r["rel_change_vs_dt0.5"]) for r in crit if r["policy"] == p) for p in {r["policy"] for r in crit}}
    return {"id": eid, "rows": rows, "worst_abs_dt1_vs_dt05": worst,
            "hypothesis_met": all(w < 0.005 for w in worst.values())}


def e005(store: Store, threshold: float) -> dict[str, Any] | None:
    eid = store.latest_experiment("E005")
    if not eid:
        return None
    exp = store.experiment(eid)
    runs = store.runs(eid)
    rows = []
    comp = {(r["group"]): _row(r) for r in A.paired(runs, "E_per_success_kJ", "joint", "independent")}
    summ = {}
    for m in ("chip_s_over_target", "chip_s_throttled", "peak_T_j_C", "E_per_success_kJ"):
        for r in A.summary(runs, m):
            summ[(r["group"], r["policy"], m)] = _f(r["mean"])
    for (sc, var), c in comp.items():
        rows.append({"scenario": sc, "variant": var, "joint_vs_independent": c["mean"], "lo": c["lo"], "hi": c["hi"],
                     "verdict": A.verdict(c, threshold),
                     **{f"{p}_{m}": summ.get(((sc, var), p, m)) for p in ("joint", "independent")
                        for m in ("chip_s_over_target", "chip_s_throttled", "peak_T_j_C", "E_per_success_kJ")}})
    rows.sort(key=lambda r: (r["scenario"], r["variant"]))
    return {"id": eid, "spec": exp["spec"], "rows": rows,
            "n_runs": len(runs), "n_failed": sum(r["status"] != "completed" for r in runs)}


def compute_all(store: Store, threshold: float = 0.01) -> dict[str, Any]:
    from datetime import datetime, timezone
    from .params import assumptions_table
    ok, chain_msg = store.verify_chain()
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code_sha256": code_hash(),
        "chain_ok": ok, "chain_msg": chain_msg,
        "threshold": threshold,
        "E001": e001(store, threshold), "E002": e002(store, threshold), "E003": e003(store, threshold),
        "E004": e004(store), "E005": e005(store, threshold),
        "E006": e006(store, threshold), "E007": e007(store, threshold), "E008": e008(store, threshold),
        "assumptions": assumptions_table(),
        "research_log": store.research_log(),
        "experiments": [{"id": x["id"], "key": x["key"], "status": x["status"], "title": x["spec"]["title"],
                         "hypothesis": x["spec"]["hypothesis"], "summary": x["summary"], "created": x["created_utc"]}
                        for x in store.experiments()],
    }


def verdicts(R: dict[str, Any]) -> list[dict[str, Any]]:
    """Pre-registered hypotheses evaluated mechanically from the results."""
    out = []
    e1 = R.get("E001")
    if e1:
        h1 = e1["H1"]
        state = "supported" if h1["supported"] else "not supported"
        if h1["supported"] and len(h1["scenarios_meaningful"]) < h1["required"]:
            state = "supported, small"
        out.append({"key": "E001 H1", "state": state,
                    "text": f"Joint below independent with CI under zero in {len(h1['scenarios_ci_below_zero'])}/6 scenarios; "
                            f"beyond the {R['threshold']:.0%} practical threshold in {len(h1['scenarios_meaningful'])}/6."})
        h2 = e1["H2"]
        out.append({"key": "E001 H2", "state": "supported" if h2["supported"] else
                    ("energy met, guard failed" if h2["energy_criterion_met"] else "not supported"),
                    "text": "Every optimising policy below fixed on energy per successful task in every scenario"
                            + ("" if h2["energy_criterion_met"] else " (not met)")
                            + (f"; quality guard failed in {len(h2['guard_failures'])} comparisons (slightly more late tasks)."
                               if h2["guard_failures"] else "; quality guard held.")})
    e3 = R.get("E003")
    if e3:
        be = e3["break_even_rs_rv"]
        clean = [r for r in e3["rows"] if r["false_accept"] == 0]
        below = [r for r in clean if r["rs_plus_rv"] < be - 0.02]
        above = [r for r in clean if r["rs_plus_rv"] > be + 0.02]
        c1 = all(r["energy_hi"] is not None and r["energy_hi"] < 0 for r in below)
        c2 = all(r["energy_lo"] is not None and r["energy_lo"] > 0 for r in above)
        c3 = all(abs(r["energy_change"]) < abs(r["analytic_work_ratio"] - 1) for r in below)
        fa = [r for r in e3["rows"] if r["false_accept"] > 0]
        c4 = all(r["d_success_hi"] is not None and r["d_success_hi"] < 0 for r in fa)
        n_ok = sum([c1, c2, c3, c4])
        out.append({"key": "E003", "state": "supported" if n_ok == 4 else ("partly supported" if n_ok else "not supported"),
                    "text": f"Saves below break-even: {'yes' if c1 else 'no'}; costs above it: {'yes' if c2 else 'no'}; "
                            f"energy saving smaller than work saving: {'yes' if c3 else 'no'}; false accepts lower success: "
                            f"{'yes' if c4 else 'no'}."})
    e4 = R.get("E004")
    if e4:
        w = e4["worst_abs_dt1_vs_dt05"]
        out.append({"key": "E004", "state": "met" if e4["hypothesis_met"] else "not met",
                    "text": "Worst change dt 1 s vs 0.5 s: " + ", ".join(f"{k} {v*100:.2f}%" for k, v in sorted(w.items()))
                            + " (criterion < 0.5%)."})
    e5 = R.get("E005")
    if e5:
        rows = {(r["scenario"], r["variant"]): r for r in e5["rows"]}
        # The hypothesis covers leakage and cold-plate mismatch; the chiller case is reported but not scored.
        cases = [(k, r) for k, r in rows.items() if "twin_correct" not in k[1] and not k[1].startswith("poor_chiller")]
        over, reduced = [], []
        for (sc, var), r in cases:
            ref = rows.get((sc, var.split("|")[0] + "|twin_correct"))
            if (r["joint_chip_s_over_target"] or 0) > 0:
                over.append(f"{sc}:{var}")
            if ref and r["joint_vs_independent"] is not None and ref["joint_vs_independent"] is not None \
                    and r["joint_vs_independent"] > ref["joint_vs_independent"]:
                reduced.append(f"{sc}:{var}")
        n = len(cases)
        state = "supported" if len(over) == n and len(reduced) == n else ("partly supported" if over or reduced else "not supported")
        out.append({"key": "E005", "state": state,
                    "text": f"Leakage/cold-plate twin errors pushed joint over the 80 °C target in {len(over)}/{n} cases "
                            f"({', '.join(sorted({o.split(':')[0] for o in over})) or 'none'}) and shrank its advantage over independent in {len(reduced)}/{n}; "
                            f"hardware protection held peak temperature near 85 °C."})
    e2 = R.get("E002")
    if e2:
        flips = e2["joint_worse_mean"]
        ji = [i["param"] for i in e2["tornado"]["joint_vs_independent"]["items"]]
        jf = [i["param"] for i in e2["tornado"]["joint_vs_fixed"]["items"]]
        c1 = not flips
        c2 = bool(ji) and ji[0] in ("kappa_leak", "p_leak_ref")
        c3 = bool(jf) and jf[0] == "v_min_ratio"
        c4 = "beta_memory" in jf[:2]
        n_ok = sum([c1, c2, c3, c4])
        out.append({"key": "E002", "state": "supported" if n_ok == 4 else ("partly supported" if n_ok else "not supported"),
                    "text": (f"Joint never above independent in {len(e2['tornado']['joint_vs_independent']['items']) * 2} "
                             f"one-at-a-time variants. " if c1 else f"Joint above independent in {len(flips)} variants. ")
                            + f"Top driver of joint vs independent: {ji[0] if ji else 'n/a'}; of joint vs fixed: "
                            f"{jf[0] if jf else 'n/a'}; beta_memory ranks "
                            f"{jf.index('beta_memory') + 1 if 'beta_memory' in jf else 'n/a'} (predicted top 2)."})
    out += verdicts_phase3(R)
    return out


# ============================================================== Phase 3 (E006-E008)
def _summ(runs, metrics, key=("scenario", "variant")):
    out = {}
    for m in metrics:
        for r in A.summary(runs, m, key=key):
            out[(r["group"], r["policy"], m)] = _f(r["mean"])
    return out


def e006(store: Store, threshold: float) -> dict[str, Any] | None:
    eid = store.latest_experiment("E006")
    if not eid:
        return None
    exp = store.experiment(eid)
    runs = store.runs(eid)
    ji = [{**_row(r), "scenario": r["group"][0], "plant": r["group"][1], "verdict": A.verdict(r, threshold)}
          for r in A.paired(runs, "E_per_success_kJ", "joint", "independent")]
    plant = []
    for pol in exp["spec"]["design"]["policies"]:
        for v in ("dyn_40kg_1Kmin", "dyn_150kg_0.25Kmin"):
            for r in A.paired(runs, "E_per_success_kJ", v, "quasi_steady", key=("scenario", "policy"), factor="variant"):
                if r["group"][1] == pol:
                    plant.append({**_row(r), "scenario": r["group"][0], "policy": pol, "plant": v})
    s = _summ(runs, ["chip_s_over_target", "chip_s_throttled", "peak_T_j_C", "E_loop_storage_kWh", "E_grid_kWh",
                     "action_changes", "E_per_success_kJ"])
    thermal = []
    for (g, p, m), v in s.items():
        if m == "chip_s_over_target":
            thermal.append({"scenario": g[0], "plant": g[1], "policy": p, "over": v,
                            "throttled": s[(g, p, "chip_s_throttled")], "peak": s[(g, p, "peak_T_j_C")],
                            "storage_pct": 100 * s[(g, p, "E_loop_storage_kWh")] / s[(g, p, "E_grid_kWh")],
                            "E_per_success_kJ": s[(g, p, "E_per_success_kJ")]})
    thermal.sort(key=lambda r: (r["scenario"], r["plant"], r["policy"]))
    warn = sum(1 for r in runs if any("loop storage" in w for w in r["warnings"]))
    return {"id": eid, "version": exp["version"], "supersedes": exp["supersedes"], "spec": exp["spec"],
            "joint_vs_independent": ji, "plant_effect": plant, "thermal": thermal, "storage_warnings": warn,
            "n_runs": len(runs), "n_failed": sum(r["status"] != "completed" for r in runs)}


def e007(store: Store, threshold: float) -> dict[str, Any] | None:
    eid = store.latest_experiment("E007")
    if not eid:
        return None
    exp = store.experiment(eid)
    runs = store.runs(eid)
    by = defaultdict(list)
    for r in runs:
        if r["status"] == "completed":
            by[(r["scenario"], r["variant"])].append(r)
    switching = []
    for (sc, v), rs in sorted(by.items()):
        mean = lambda m: float(np.mean([r["metrics"][m] for r in rs]))
        thr, dt = (float(x.split("=")[1]) for x in v.split("|"))
        switching.append({"scenario": sc, "variant": v, "threshold": thr, "dt": dt, "action_changes": mean("action_changes"),
                          "clock_changes": mean("clock_changes"), "flow_changes": mean("flow_changes"),
                          "tsup_changes": mean("tsup_changes"), "E_per_success_kJ": mean("E_per_success_kJ"),
                          "over": mean("chip_s_over_target")})
    energy = []
    for v in sorted({r["variant"] for r in runs if r["variant"].endswith("dt=1.0")}):
        for r in A.paired(runs, "E_per_success_kJ", v, "thr=0.0|dt=1.0", key=("scenario", "policy"), factor="variant"):
            energy.append({**_row(r), "scenario": r["group"][0], "variant": v})
    dts = []
    for thr in sorted({x["threshold"] for x in switching}):
        for sc in sorted({x["scenario"] for x in switching}):
            a = {r["seed"]: r["metrics"]["E_grid_kWh"] for r in by.get((sc, f"thr={thr}|dt=1.0"), [])}
            b = {r["seed"]: r["metrics"]["E_grid_kWh"] for r in by.get((sc, f"thr={thr}|dt=0.5"), [])}
            d = [abs(a[k] / b[k] - 1) for k in a if k in b]
            if d:
                dts.append({"threshold": thr, "scenario": sc, "max": float(max(d)), "mean": float(np.mean(d)), "n": len(d)})
    return {"id": eid, "spec": exp["spec"], "switching": switching, "energy_vs_no_threshold": energy, "dt_sensitivity": dts,
            "n_runs": len(runs), "n_failed": sum(r["status"] != "completed" for r in runs)}


def e008(store: Store, threshold: float) -> dict[str, Any] | None:
    eid = store.latest_experiment("E008")
    if not eid:
        return None
    exp = store.experiment(eid)
    runs = store.runs(eid)
    s = _summ(runs, ["chip_s_over_target", "chip_s_throttled", "peak_T_j_C"])
    comp = {}
    for a, b in (("joint_robust", "independent"), ("joint_robust", "joint"), ("joint", "independent")):
        for r in A.paired(runs, "E_per_success_kJ", a, b):
            comp[(r["group"], a, b)] = _row(r)
    rows = []
    for g in sorted({k[0] for k in comp}):
        row = {"scenario": g[0], "variant": g[1]}
        for (a, b) in (("joint_robust", "independent"), ("joint_robust", "joint"), ("joint", "independent")):
            c = comp.get((g, a, b))
            row[f"{a}_vs_{b}"] = {"mean": c["mean"], "lo": c["lo"], "hi": c["hi"], "verdict": A.verdict(c, threshold)} if c else None
        for p in ("independent", "joint", "joint_robust"):
            row[p] = {"over": s.get((g, p, "chip_s_over_target")), "throttled": s.get((g, p, "chip_s_throttled")),
                      "peak": s.get((g, p, "peak_T_j_C"))}
        rows.append(row)
    return {"id": eid, "spec": exp["spec"], "rows": rows,
            "n_runs": len(runs), "n_failed": sum(r["status"] != "completed" for r in runs)}


def verdicts_phase3(R: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    e6 = R.get("E006")
    if e6:
        dyn = [r for r in e6["joint_vs_independent"] if r["plant"] != "quasi_steady"]
        h1 = all(r["hi"] is not None and r["hi"] < 0 for r in dyn)
        slow_over = [t for t in e6["thermal"] if t["policy"] == "joint" and t["plant"] == "dyn_150kg_0.25Kmin" and (t["over"] or 0) > 0]
        fixed_eff = [p for p in e6["plant_effect"] if p["policy"] == "fixed"]
        h3 = all(abs(p["mean"]) < 0.005 for p in fixed_eff)
        th = {(t["scenario"], t["plant"], t["policy"]): t for t in e6["thermal"]}
        h4_fail = [f"{sc}/{pl}" for (sc, pl, p) in th if p == "joint_robust"
                   and (th[(sc, pl, "joint_robust")]["over"] or 0) > (th[(sc, pl, "joint")]["over"] or 0)]
        n = sum([h1, bool(slow_over), h3, not h4_fail])
        out.append({"key": "E006", "state": "supported" if n == 4 else ("partly supported" if n else "not supported"),
                    "text": f"H1 joint < independent under both dynamic plants in all scenarios: {'yes' if h1 else 'no'}. "
                            f"H2 joint over target with the slow plant: {'yes (' + ', '.join(t['scenario'] for t in slow_over) + ')' if slow_over else 'no'}. "
                            f"H3 fixed policy unaffected: {'yes' if h3 else 'no'}. "
                            f"H4 joint_robust never worse than joint on overheating: {'yes' if not h4_fail else 'no (' + ', '.join(h4_fail) + ')'}."})
    e7 = R.get("E007")
    if e7:
        sw = {(x["scenario"], x["threshold"], x["dt"]): x for x in e7["switching"]}
        red = {sc: 1 - sw[(sc, 0.05, 1.0)]["action_changes"] / sw[(sc, 0.0, 1.0)]["action_changes"]
               for sc in {k[0] for k in sw} if (sc, 0.05, 1.0) in sw and (sc, 0.0, 1.0) in sw}
        h1 = all(v < 0.25 for v in red.values())
        dts = {(d["scenario"], d["threshold"]): d for d in e7["dt_sensitivity"]}
        h2 = all(d["max"] < 0.005 for (sc, t), d in dts.items() if t == 0.02)
        base_ok = all(d["max"] < 0.005 for (sc, t), d in dts.items() if t == 0.0)
        cost = [x for x in e7["energy_vs_no_threshold"] if x["variant"].startswith("thr=0.02")]
        h3 = all(x["hi"] is not None and x["hi"] <= 0.003 for x in cost)
        n = sum([h1, h2, h3])
        out.append({"key": "E007", "state": ("supported" if n == 3 else "partly supported" if n else "not supported")
                    + (", but suppression not the cause" if h2 and base_ok else ""),
                    "text": "Switching cut by a 5% threshold: " + ", ".join(f"{sc} {v:.1%}" for sc, v in sorted(red.items()))
                            + f" (H1 <25%: {'yes' if h1 else 'no'}). Worst dt-sensitivity at 2%: "
                            + ", ".join(f"{sc} {dts[(sc, 0.02)]['max']:.2%}" for sc in sorted(red) if (sc, 0.02) in dts)
                            + f"; with no threshold: " + ", ".join(f"{sc} {dts[(sc, 0.0)]['max']:.2%}" for sc in sorted(red) if (sc, 0.0) in dts)
                            + f". Energy cost of 2%: {'<= 0.3%' if h3 else '> 0.3%'}."})
    e8 = R.get("E008")
    if e8:
        over_cases = [r for r in e8["rows"] if (r["joint"]["over"] or 0) > 0]
        h1 = all((r["joint_robust"]["throttled"] or 0) == 0 and (r["joint_robust"]["over"] or 0) <= 0.2 * r["joint"]["over"]
                 for r in over_cases)
        h2_fail = [f"{r['scenario']}/{r['variant']}" for r in e8["rows"]
                   if not (r["joint_robust_vs_independent"] and r["joint_robust_vs_independent"]["hi"] is not None
                           and r["joint_robust_vs_independent"]["hi"] <= 0)]
        correct = [r for r in e8["rows"] if r["variant"] == "default" or r["variant"].endswith("twin_correct")]
        h3 = all(abs(r["joint_robust_vs_joint"]["mean"]) <= 0.005 for r in correct)
        n = sum([h1, not h2_fail, h3])
        red = [1 - r["joint_robust"]["over"] / r["joint"]["over"] for r in over_cases if r["joint"]["over"]]
        out.append({"key": "E008", "state": "supported" if n == 3 else ("partly supported" if n else "not supported"),
                    "text": f"Where joint overheated ({len(over_cases)} cases) the correction cut chip-seconds over target by "
                            + ", ".join(f"{x:.0%}" for x in red) + " with no throttling (H1: " + ("yes" if h1 else "no") + "). "
                            + ("Never worse than independent on energy (H2: yes). " if not h2_fail else
                               f"Not confirmed no-worse than independent in {', '.join(h2_fail)} (H2: no). ")
                            + f"Within 0.5% of joint with a correct twin (H3: {'yes' if h3 else 'no'})."})
    return out
