"""Analyses for the next-generation experiments E018, E019, E020 and E022, written before their runs and
applying the pre-registered criteria verbatim (see each spec's "hypothesis"). Imported by results.py."""
from __future__ import annotations

from typing import Any

import numpy as np

from . import analysis as A
from .store import Store


def _f(x):
    return None if x is None or not np.isfinite(x) else float(x)


def _mean(d: dict, k: str):
    v = [m[k] for m in d.values() if m.get(k) is not None and np.isfinite(m[k])]
    return float(np.mean(v)) if v else float("nan")


def _paired(a: dict, b: dict, k: str):
    seeds = sorted(set(a) & set(b))
    x = np.array([a[s][k] / b[s][k] - 1 for s in seeds if b[s].get(k)])
    if x.size < 2:
        return {"mean": None, "lo": None, "hi": None, "n": int(x.size)}
    m, lo, hi = A.t_ci(x)
    return {"mean": _f(m), "lo": _f(lo), "hi": _f(hi), "n": int(x.size)}


def _load(store: Store, key: str):
    eid = store.latest_experiment(key)
    if not eid:
        return None, None, None
    runs = store.runs(eid)
    return eid, runs, A.index_runs(runs)


# ------------------------------------------------------------------ E018
E018_BASE = ("round_robin", "least_loaded", "power_aware", "temperature_aware")
E018_KEYS = ("E_per_on_time_job_kJ", "on_time_frac", "chip_s_over_target", "throttle_gpu_s", "cap_steps",
             "mean_wait_s", "work_done_gpu_s", "E_grid_kWh", "jobs_on_time")


def e018(store: Store, threshold: float = 0.02) -> dict[str, Any] | None:
    eid, runs, idx = _load(store, "E018")
    if not eid:
        return None
    conds = sorted({g[0] for g in idx})
    rows = {}
    for c in conds:
        arms = idx[(c, c)]
        rows[c] = {"means": {p: {k: _f(_mean(d, k)) for k in E018_KEYS} for p, d in arms.items()},
                   "tc_vs": {b: _paired(arms["thermal_credit"], arms[b], "E_per_on_time_job_kJ")
                             for b in E018_BASE if b in arms and "thermal_credit" in arms},
                   "tp_vs_ta": _paired(arms.get("thermal_placement", {}), arms.get("temperature_aware", {}), "E_per_on_time_job_kJ"),
                   "tc_vs_tp": _paired(arms.get("thermal_credit", {}), arms.get("thermal_placement", {}), "E_per_on_time_job_kJ")}
    M = lambda c, p, k: (rows.get(c, {}).get("means", {}).get(p, {}) or {}).get(k)   # noqa: E731
    stress = [c for c in conds if c.startswith(("C2", "C3", "C5"))]
    h1 = {c: {b: v for b, v in rows[c]["tc_vs"].items()} for c in stress}
    h1_ok = all(v["hi"] is not None and v["hi"] < 0 and v["mean"] <= -threshold for c in stress for v in h1[c].values())
    h2_ok = all((M(c, "thermal_credit", "chip_s_over_target") or 0) <= (M(c, "temperature_aware", "chip_s_over_target") or 0) + 1e-9
                for c in conds) and all((M(c, "thermal_credit", "chip_s_over_target") or 0) <= 0.5 * (M(c, "least_loaded", "chip_s_over_target") or 0) + 1e-9
                                        for c in stress)
    best = lambda c: max(M(c, b, "on_time_frac") or 0 for b in E018_BASE)   # noqa: E731
    h3_ok = all((M(c, "thermal_credit", "on_time_frac") or 0) >= best(c) - 0.02 for c in stress)
    c1 = next((c for c in conds if c.startswith("C1")), None)
    h4 = rows[c1]["tc_vs"].get("least_loaded") if c1 else None
    h4_ok = bool(c1) and h4["mean"] is not None and abs(h4["mean"]) < 0.01 and \
        abs((M(c1, "thermal_credit", "on_time_frac") or 0) - (M(c1, "least_loaded", "on_time_frac") or 0)) < 0.01
    c4 = next((c for c in conds if c.startswith("C4")), None)
    h5_ok = bool(c4) and (M(c4, "thermal_credit", "on_time_frac") or 0) >= (M(c4, "power_aware", "on_time_frac") or 0) - 1e-12
    return {"id": eid, "n_runs": len(runs), "n_failed": sum(r["status"] != "completed" for r in runs), "rows": rows,
            "H1": {"supported": h1_ok, "values": h1}, "H2": {"supported": h2_ok}, "H3": {"supported": h3_ok},
            "H4": {"supported": h4_ok, "values": h4}, "H5": {"supported": h5_ok}}


def verdicts_e018(R: dict[str, Any]) -> list[dict[str, Any]]:
    e = R.get("E018")
    if not e:
        return []
    st = lambda ok: "supported" if ok else "not supported"   # noqa: E731
    pct = lambda v: "n/a" if v is None else f"{100 * v:+.1f}%"   # noqa: E731
    rows = e["rows"]
    out = []
    t1 = "; ".join(f"{c.split('_')[0]}: " + ", ".join(f"{b} {pct(v['mean'])} [{pct(v['lo'])}, {pct(v['hi'])}]"
                                                     for b, v in e["H1"]["values"][c].items()) for c in e["H1"]["values"])
    out.append({"key": "E018 H1", "state": st(e["H1"]["supported"]), "text": "thermal_credit energy per on-time job vs baselines: " + t1 + "."})
    t2 = "; ".join(f"{c.split('_')[0]} TC/TA/LL {rows[c]['means']['thermal_credit']['chip_s_over_target']:.0f}/"
                   f"{rows[c]['means']['temperature_aware']['chip_s_over_target']:.0f}/{rows[c]['means']['least_loaded']['chip_s_over_target']:.0f}"
                   for c in rows)
    out.append({"key": "E018 H2", "state": st(e["H2"]["supported"]), "text": "chip-s above t_target: " + t2 + "."})
    t3 = "; ".join(f"{c.split('_')[0]} TC {rows[c]['means']['thermal_credit']['on_time_frac']:.3f} best baseline "
                   f"{max(rows[c]['means'][b]['on_time_frac'] for b in E018_BASE):.3f}" for c in rows)
    out.append({"key": "E018 H3", "state": st(e["H3"]["supported"]), "text": "on-time fraction: " + t3 + "."})
    h4 = e["H4"]["values"] or {}
    out.append({"key": "E018 H4", "state": st(e["H4"]["supported"]), "text": f"C1 thermal_credit vs least_loaded energy {pct(h4.get('mean'))}."})
    out.append({"key": "E018 H5", "state": st(e["H5"]["supported"]), "text": "C4 on-time thermal_credit vs power_aware."})
    return out


# ------------------------------------------------------------------ E020
def e020(store: Store, threshold: float = 0.03) -> dict[str, Any] | None:
    eid, runs, idx = _load(store, "E020")
    if not eid:
        return None
    arm = {}
    for (c, _), pols in idx.items():
        sc, amb, a = c.split("|")
        arm[(sc, amb, a)] = next(iter(pols.values()))
    cells = {}
    for (sc, amb, a), d in arm.items():
        base = arm.get((sc, amb, "independent"), {})
        cells[f"{sc}|{amb}|{a}"] = {k: _f(_mean(d, k)) for k in ("E_per_on_time_job_kJ", "on_time_frac", "T_sup_mean_C",
                                                                 "E_fan_kWh", "E_chiller_kWh", "E_pump_kWh", "E_it_kWh",
                                                                 "chip_s_over_target", "throttle_gpu_s")}
        cells[f"{sc}|{amb}|{a}"]["vs_independent"] = _paired(d, base, "E_per_on_time_job_kJ") if a != "independent" else None
    scales, ambs = ["n1", "n4", "n16"], ["amb20", "amb30"]
    J = lambda sc, amb: cells.get(f"{sc}|{amb}|joint", {}).get("vs_independent") or {}   # noqa: E731
    h1_ok = all(J(s, a).get("hi") is not None and J(s, a)["hi"] < 0 and J(s, a)["mean"] <= -threshold for s in scales for a in ambs)
    h2_ok = all(abs((cells[f"{s}|{a}|joint"]["on_time_frac"] or 0) - (cells[f"{s}|{a}|independent"]["on_time_frac"] or 0)) <= 0.01
                for s in scales for a in ambs if f"{s}|{a}|joint" in cells)
    h3_ok = all(J("n16", a).get("mean") is not None and J("n1", a).get("mean") is not None and
                -J("n16", a)["mean"] >= -J("n1", a)["mean"] - 0.01 for a in ambs)
    wv = {a: _paired(arm.get(("n16", a, "warm_valves"), {}), arm.get(("n16", a, "warm"), {}), "E_per_on_time_job_kJ") for a in ambs}
    h4_ok = all(v["hi"] is not None and v["hi"] < 0 for v in wv.values())
    return {"id": eid, "n_runs": len(runs), "n_failed": sum(r["status"] != "completed" for r in runs), "cells": cells,
            "H1": {"supported": h1_ok}, "H2": {"supported": h2_ok}, "H3": {"supported": h3_ok},
            "H4": {"supported": h4_ok, "values": wv}}


def verdicts_e020(R: dict[str, Any]) -> list[dict[str, Any]]:
    e = R.get("E020")
    if not e:
        return []
    st = lambda ok: "supported" if ok else "not supported"   # noqa: E731
    pct = lambda v: "n/a" if v is None else f"{100 * v:+.1f}%"   # noqa: E731
    C = e["cells"]
    t = "; ".join(f"{k.rsplit('|', 1)[0]}: {pct((v['vs_independent'] or {}).get('mean'))} "
                  f"[{pct((v['vs_independent'] or {}).get('lo'))}, {pct((v['vs_independent'] or {}).get('hi'))}]"
                  for k, v in sorted(C.items()) if k.endswith("|joint"))
    t2 = "; ".join(f"{k.rsplit('|', 1)[0]}: {C[k]['on_time_frac']:.3f} vs {C[k.replace('|joint', '|independent')]['on_time_frac']:.3f}"
                   for k in sorted(C) if k.endswith("|joint"))
    t4 = "; ".join(f"{a}: {pct(v['mean'])} [{pct(v['lo'])}, {pct(v['hi'])}]" for a, v in e["H4"]["values"].items())
    return [{"key": "E020 H1", "state": st(e["H1"]["supported"]), "text": "joint vs independent, energy per on-time job: " + t + "."},
            {"key": "E020 H2", "state": st(e["H2"]["supported"]), "text": "on-time fraction joint vs independent: " + t2 + "."},
            {"key": "E020 H3", "state": st(e["H3"]["supported"]), "text": "benefit at 16 nodes vs 1 node (see H1 values)."},
            {"key": "E020 H4", "state": st(e["H4"]["supported"]), "text": "16 nodes, heat-proportional valves vs equal: " + t4 + "."}]


# ------------------------------------------------------------------ E022
def e022(store: Store, threshold: float = 0.03) -> dict[str, Any] | None:
    eid, runs, idx = _load(store, "E022")
    if not eid:
        return None
    arm = {}
    for (c, _), pols in idx.items():
        amb, a = c.split("|")
        arm[(amb, a)] = next(iter(pols.values()))
    keys = ("E_above_cap_kWh", "E_event_kWh", "max_exceed_kW", "work_in_event_gpu_s", "on_time_frac", "E_grid_kWh",
            "cost", "co2_kg", "deferrals", "storage_used_kWh_th", "storage_charge_kWh_el")
    cells = {f"{amb}|{a}": {k: _f(_mean(d, k)) for k in keys} for (amb, a), d in arm.items()}
    M = lambda amb, a, k: (cells.get(f"{amb}|{a}") or {}).get(k)   # noqa: E731
    h1_ok = all((M(a, "cap", "E_above_cap_kWh") or 0) <= 0.02 * (M(a, "cap", "E_event_kWh") or 0) for a in ("amb20", "amb30"))
    h2_ok = all((M(a, "cap_defer", "on_time_frac") or 0) >= (M(a, "cap", "on_time_frac") or 0) - 1e-12 for a in ("amb20", "amb30"))
    s30 = _paired(arm.get(("amb30", "cap_storage"), {}), arm.get(("amb30", "cap"), {}), "work_in_event_gpu_s")
    s20 = _paired(arm.get(("amb20", "cap_storage"), {}), arm.get(("amb20", "cap"), {}), "work_in_event_gpu_s")
    h3_ok = (s30["lo"] is not None and s30["lo"] > 0 and s30["mean"] >= threshold and s20["mean"] is not None and abs(s20["mean"]) < 0.01)
    h4_ok = (M("amb30", "cap_storage", "E_grid_kWh") or 0) > (M("amb30", "cap", "E_grid_kWh") or 0) and \
        (M("amb30", "cap_storage", "cost") or 0) < (M("amb30", "cap", "cost") or 0)
    none_runs = [m for (amb, a), d in arm.items() if a == "none" for m in d.values()]
    h5_ok = bool(none_runs) and all(m["E_above_cap_kWh"] > 0 for m in none_runs)
    return {"id": eid, "n_runs": len(runs), "n_failed": sum(r["status"] != "completed" for r in runs), "cells": cells,
            "H1": {"supported": h1_ok}, "H2": {"supported": h2_ok}, "H3": {"supported": h3_ok, "amb30": s30, "amb20": s20},
            "H4": {"supported": h4_ok}, "H5": {"supported": h5_ok}}


def verdicts_e022(R: dict[str, Any]) -> list[dict[str, Any]]:
    e = R.get("E022")
    if not e:
        return []
    st = lambda ok: "supported" if ok else "not supported"   # noqa: E731
    C = e["cells"]
    g = lambda a, arm, k, d=3: f"{C[f'{a}|{arm}'][k]:.{d}f}" if C.get(f"{a}|{arm}", {}).get(k) is not None else "n/a"   # noqa: E731
    pct = lambda v: "n/a" if v is None else f"{100 * v:+.1f}%"   # noqa: E731
    out = []
    for a in ("amb20", "amb30"):
        pass
    out.append({"key": "E022 H1", "state": st(e["H1"]["supported"]), "text": "cap: energy above cap / event energy (kWh): " +
                "; ".join(f"{a} {g(a, 'cap', 'E_above_cap_kWh')}/{g(a, 'cap', 'E_event_kWh')}" for a in ("amb20", "amb30")) + "."})
    out.append({"key": "E022 H2", "state": st(e["H2"]["supported"]), "text": "on-time fraction cap_defer vs cap: " +
                "; ".join(f"{a} {g(a, 'cap_defer', 'on_time_frac')} vs {g(a, 'cap', 'on_time_frac')}" for a in ("amb20", "amb30")) + "."})
    h3 = e["H3"]
    out.append({"key": "E022 H3", "state": st(h3["supported"]), "text": f"work during the event, storage vs cap: 30 C "
                f"{pct(h3['amb30']['mean'])} [{pct(h3['amb30']['lo'])}, {pct(h3['amb30']['hi'])}]; 20 C {pct(h3['amb20']['mean'])}."})
    out.append({"key": "E022 H4", "state": st(e["H4"]["supported"]), "text": f"30 C energy cap_storage/cap {g('amb30', 'cap_storage', 'E_grid_kWh')}/"
                f"{g('amb30', 'cap', 'E_grid_kWh')} kWh; cost {g('amb30', 'cap_storage', 'cost')}/{g('amb30', 'cap', 'cost')}."})
    out.append({"key": "E022 H5", "state": st(e["H5"]["supported"]), "text": "uncapped arm exceeds the cap in every seed: " +
                "; ".join(f"{a} {g(a, 'none', 'E_above_cap_kWh')} kWh above" for a in ("amb20", "amb30")) + "."})
    return out


# ------------------------------------------------------------------ E019
WINDOW_FAULTS = ("F1_sensor_dropout", "F2_junction_bias_low", "F3_stale_sensors", "F4_clock_stuck", "F5_comm_failure",
                 "F6_controller_crash", "F7_solver_infeasible", "F8_supply_bias_low")
PHYS = ("P2_fouling_step", "P3_pump_degraded", "P4_wrong_model")


def e019(store: Store, threshold: float = 0.01) -> dict[str, Any] | None:
    eid, runs, idx = _load(store, "E019")
    if not eid:
        return None
    sc = runs[0]["scenario"] if runs else ""
    onset = {k: (2400.0 if k.startswith("F") or k == "P2_fouling_step" else 0.0)
             for (_, k) in idx}
    ctrl = ("joint_meas", "mpc")
    cells = {}
    for (_, f), pols in idx.items():
        for c in ctrl:
            n, a = pols.get(f"nominal_{c}", {}), pols.get(f"aware_{c}", {})
            cells[f"{f}|{c}"] = {"nominal_over": _f(_mean(n, "chip_s_over_target")), "aware_over": _f(_mean(a, "chip_s_over_target")),
                                 "nominal_E": _f(_mean(n, "E_per_success_kJ")), "aware_E": _f(_mean(a, "E_per_success_kJ")),
                                 "nominal_late": _f(_mean(n, "slo_violations")), "aware_late": _f(_mean(a, "slo_violations")),
                                 "E_aware_vs_nominal": _paired(a, n, "E_per_success_kJ"), "aware_runs": a}
    aw = lambda f: [m for c in ctrl for m in cells.get(f"{f}|{c}", {}).get("aware_runs", {}).values()]   # noqa: E731
    f0 = aw("F0_none")
    h1_ok = bool(f0) and all(m.get("diag_first_alarm_t", -1) == -1 for m in f0) and \
        all(abs((cells[f"F0_none|{c}"]["E_aware_vs_nominal"]["mean"] or 0)) <= 0.005 for c in ctrl)
    det = [(m.get("diag_first_alarm_t", -1) >= 2400.0 and m.get("diag_first_alarm_t", -1) <= 2400.0 + 180.0)
           for f in WINDOW_FAULTS for m in aw(f)]
    h2_frac = float(np.mean(det)) if det else float("nan")
    h3_fail = [k for k, v in cells.items() if (v["aware_over"] or 0) > (v["nominal_over"] or 0) + 1.0]
    h4 = {c: (cells[f"F4_clock_stuck|{c}"]["aware_over"], cells[f"F4_clock_stuck|{c}"]["nominal_over"]) for c in ctrl
          if f"F4_clock_stuck|{c}" in cells}
    h4_ok = all(n is not None and (n <= 0 or a <= 0.5 * n) for a, n in h4.values())
    left = [m for f in WINDOW_FAULTS for m in aw(f) if (m.get("diag_safe_intervals", 0) + m.get("diag_degraded_intervals", 0)) > 0]
    rec = [0 <= m.get("diag_recovered_t", -1) <= 4200.0 + 300.0 for m in left]
    h5_frac = float(np.mean(rec)) if rec else float("nan")
    dg = [m.get("diag_degradation_alarm_t", -1) >= onset.get(f, 0.0) and m.get("diag_degradation_alarm_t", -1) >= 0
          for f in PHYS for m in aw(f)]
    h6_frac = float(np.mean(dg)) if dg else float("nan")
    for v in cells.values():
        v.pop("aware_runs", None)
    return {"id": eid, "scenario": sc, "n_runs": len(runs), "n_failed": sum(r["status"] != "completed" for r in runs),
            "cells": cells, "H1": {"supported": h1_ok}, "H2": {"supported": h2_frac >= 0.8, "fraction": _f(h2_frac)},
            "H3": {"supported": not h3_fail, "failing": h3_fail}, "H4": {"supported": h4_ok, "values": h4},
            "H5": {"supported": h5_frac >= 0.8, "fraction": _f(h5_frac)}, "H6": {"supported": h6_frac >= 0.8, "fraction": _f(h6_frac)}}


def verdicts_e019(R: dict[str, Any]) -> list[dict[str, Any]]:
    e = R.get("E019")
    if not e:
        return []
    st = lambda ok: "supported" if ok else "not supported"   # noqa: E731
    C = e["cells"]
    t3 = "; ".join(f"{k}: {v['nominal_over']:.0f} -> {v['aware_over']:.0f}" for k, v in sorted(C.items())
                   if (v["nominal_over"] or 0) > 0 or (v["aware_over"] or 0) > 0)
    return [{"key": "E019 H1", "state": st(e["H1"]["supported"]), "text": "no-fault: no alarms and energy within 0.5%: " +
             "; ".join(f"{c} {100 * (C[f'F0_none|{c}']['E_aware_vs_nominal']['mean'] or 0):+.2f}%" for c in ("joint_meas", "mpc")) + "."},
            {"key": "E019 H2", "state": st(e["H2"]["supported"]), "text": f"window faults detected within 180 s of onset in "
             f"{100 * (e['H2']['fraction'] or 0):.0f}% of fault-aware runs (needed 80%)."},
            {"key": "E019 H3", "state": st(e["H3"]["supported"]), "text": "chip-s above t_target nominal -> fault-aware (nonzero only): " + (t3 or "none") +
             (f". Failing: {', '.join(e['H3']['failing'])}" if e["H3"]["failing"] else "") + "."},
            {"key": "E019 H4", "state": st(e["H4"]["supported"]), "text": "clock stuck, aware/nominal chip-s: " +
             "; ".join(f"{c} {a:.0f}/{n:.0f}" for c, (a, n) in e["H4"]["values"].items()) + "."},
            {"key": "E019 H5", "state": st(e["H5"]["supported"]), "text": f"back to NORMAL within 300 s after the window in "
             f"{100 * (e['H5']['fraction'] or 0):.0f}% of runs that left NORMAL."},
            {"key": "E019 H6", "state": st(e["H6"]["supported"]), "text": f"degradation alarm in {100 * (e['H6']['fraction'] or 0):.0f}% "
             "of fault-aware runs with fouling, a degraded pump or a wrong model."}]


# ------------------------------------------------------------------ E024
def e024(store: Store, threshold: float = 0.05) -> dict[str, Any] | None:
    eid, runs, idx = _load(store, "E024")
    if not eid:
        return None
    arm = {c: next(iter(p.values())) for (c, _), p in idx.items()}
    full, base = arm.get("S1V1T1D1", {}), arm.get("S0V0T0D0", {})
    k = "E_per_on_time_job_kJ"
    h1 = _paired(full, base, k)
    loo = {}
    for i, f in enumerate("SVTD"):
        lab = "".join(f"{g}{0 if j == i else 1}" for j, g in enumerate("SVTD"))
        loo[f] = _paired(arm.get(lab, {}), full, k)
    means = {c: {m: _f(_mean(d, m)) for m in (k, "on_time_frac", "chip_s_over_target", "E_above_cap_kWh", "cost", "co2_kg",
                                              "T_sup_mean_C")} for c, d in arm.items()}
    lev = lambda c, f: 1 if f"{f}1" in c else -1            # noqa: E731  effect coding
    E = {c: v[k] for c, v in means.items() if v[k] is not None}
    main = {f: _f(np.mean([E[c] * lev(c, f) for c in E]) * 2 / max(np.mean(list(E.values())), 1e-9)) for f in "SVTD"} if len(E) == 16 else {}
    inter = {}
    if len(E) == 16:
        for a in range(4):
            for b in range(a + 1, 4):
                fa, fb = "SVTD"[a], "SVTD"[b]
                inter[fa + fb] = _f(np.mean([E[c] * lev(c, fa) * lev(c, fb) for c in E]) * 2 / np.mean(list(E.values())))
    M = lambda c, m: (means.get(c) or {}).get(m)   # noqa: E731
    return {"id": eid, "n_runs": len(runs), "n_failed": sum(r["status"] != "completed" for r in runs), "means": means,
            "main_effects_rel": main, "interactions_rel": inter,
            "H1": {"supported": h1["hi"] is not None and h1["hi"] < 0 and h1["mean"] <= -threshold, "value": h1},
            "H2": {"supported": all(v["mean"] is not None and v["mean"] > 0 for v in loo.values()), "values": loo},
            "H3": {"supported": abs((M("S1V1T1D1", "on_time_frac") or 0) - (M("S0V0T0D0", "on_time_frac") or 0)) <= 0.01},
            "H4": {"supported": (M("S1V1T1D1", "chip_s_over_target") or 0) <= (M("S0V0T0D0", "chip_s_over_target") or 0) + 1e-9}}


def verdicts_e024(R: dict[str, Any]) -> list[dict[str, Any]]:
    e = R.get("E024")
    if not e:
        return []
    st = lambda ok: "supported" if ok else "not supported"   # noqa: E731
    pct = lambda v: "n/a" if v is None else f"{100 * v:+.1f}%"   # noqa: E731
    h1 = e["H1"]["value"]
    m = e["means"]
    return [{"key": "E024 H1", "state": st(e["H1"]["supported"]), "text": f"full vs baseline energy per on-time job {pct(h1['mean'])} [{pct(h1['lo'])}, {pct(h1['hi'])}]."},
            {"key": "E024 H2", "state": st(e["H2"]["supported"]), "text": "leave-one-out vs full: " +
             "; ".join(f"without {f} {pct(v['mean'])}" for f, v in e["H2"]["values"].items()) + "."},
            {"key": "E024 H3", "state": st(e["H3"]["supported"]), "text": f"on-time fraction full {m.get('S1V1T1D1', {}).get('on_time_frac')} vs baseline {m.get('S0V0T0D0', {}).get('on_time_frac')}."},
            {"key": "E024 H4", "state": st(e["H4"]["supported"]), "text": f"chip-s above target full {m.get('S1V1T1D1', {}).get('chip_s_over_target')} vs baseline {m.get('S0V0T0D0', {}).get('chip_s_over_target')}."}]
