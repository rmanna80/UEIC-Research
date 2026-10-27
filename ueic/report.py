"""Generate docs/RESULTS.md, docs/04_assumptions_register.md, docs/research_log.md
and results/figures/*.png from the store. Every number comes from results.compute_all()."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .results import POLICY_ORDER, compute_all  # noqa: E402

# Reference categorical palette (dataviz skill), fixed slot order, light surface.
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
POLICY_COLOR = {p: SLOTS[i] for i, p in enumerate(POLICY_ORDER)}
INK, INK2, MUTED, GRID, AXIS, SURF = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
LABEL = {"fixed": "Fixed baseline", "compute_only": "Compute-only", "cooling_only": "Cooling-only",
         "independent": "Independent", "joint": "Joint"}


def _style(ax):
    ax.set_facecolor(SURF)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(AXIS)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def pct(x, d=1):
    return "n/a" if x is None else f"{x * 100:+.{d}f}%"


def ci(r, d=1):
    return f"{pct(r['mean'], d)} [{pct(r['lo'], d)}, {pct(r['hi'], d)}]"


def num(x, d=2):
    return "n/a" if x is None else f"{x:.{d}f}"


# ------------------------------------------------------------------------ figures
def fig_e001_energy(R, out):
    e = R["E001"]
    sc, pols = e["scenarios"], e["policies"]
    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=150)
    fig.patch.set_facecolor(SURF)
    _style(ax)
    w = 0.8 / len(pols)
    x = np.arange(len(sc))
    for j, p in enumerate(pols):
        m = [e["table"][s][p]["E_per_success_kJ"]["mean"] for s in sc]
        lo = [e["table"][s][p]["E_per_success_kJ"]["lo"] for s in sc]
        hi = [e["table"][s][p]["E_per_success_kJ"]["hi"] for s in sc]
        xs = x - 0.4 + w * (j + 0.5)
        ax.bar(xs, m, width=w * 0.9, color=POLICY_COLOR[p], label=LABEL[p], edgecolor=SURF, linewidth=1)
        ax.errorbar(xs, m, yerr=[np.subtract(m, lo), np.subtract(hi, m)], fmt="none", ecolor=INK2, elinewidth=0.8, capsize=0)
    ax.set_xticks(x, [s.split("_", 1)[1].replace("_", " ") for s in sc])
    ax.set_ylabel("Facility energy per successful task (kJ)", color=INK2, fontsize=9)
    ax.legend(frameon=False, ncol=5, fontsize=8.5, loc="upper center", bbox_to_anchor=(0.5, 1.12), labelcolor=INK)
    ax.set_title("E001 · Energy per successful task by policy and scenario (mean, 95% CI, 10 seeds; simulated)",
                 fontsize=10, color=INK, loc="left", pad=28)
    fig.tight_layout()
    fig.savefig(out / "e001_energy_per_task.png", facecolor=SURF)
    plt.close(fig)


def fig_e001_breakdown(R, out, scenario="S3_hot"):
    e = R["E001"]
    pols = e["policies"]
    parts = [("E_it_kWh", "Accelerators (IT)"), ("E_conv_loss_kWh", "Conversion loss"), ("E_pump_kWh", "Pump"),
             ("E_fan_kWh", "Heat-rejection fans"), ("E_chiller_kWh", "Chiller")]
    fig, ax = plt.subplots(figsize=(10, 3.4), dpi=150)
    fig.patch.set_facecolor(SURF)
    _style(ax)
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    left = np.zeros(len(pols))
    for i, (k, lab) in enumerate(parts):
        v = np.array([max(0.0, e["table"][scenario][p][k]["mean"]) for p in pols])
        ax.barh(range(len(pols)), v, left=left, color=SLOTS[i], label=lab, edgecolor=SURF, linewidth=2, height=0.6)
        left += v
    for i, p in enumerate(pols):
        ax.text(left[i] + 0.1, i, f"{left[i]:.2f} kWh", va="center", fontsize=8.5, color=INK2)
    ax.set_yticks(range(len(pols)), [LABEL[p] for p in pols])
    ax.invert_yaxis()
    ax.set_xlabel("Grid energy over the run (kWh, mean of 10 seeds)", color=INK2, fontsize=9)
    ax.legend(frameon=False, ncol=5, fontsize=8.5, loc="upper center", bbox_to_anchor=(0.5, 1.2), labelcolor=INK)
    ax.set_title(f"E001 · Where the energy goes, {scenario} (simulated)", fontsize=10, color=INK, loc="left", pad=30)
    fig.tight_layout()
    fig.savefig(out / "e001_breakdown.png", facecolor=SURF)
    plt.close(fig)


def fig_e001_timeseries(R, out, scenario="S3_hot"):
    ts = R["E001"]["timeseries"].get(scenario, {})
    pols = [p for p in ("fixed", "independent", "joint") if p in ts]
    if not pols:
        return
    fig, axes = plt.subplots(3, 1, figsize=(10, 6.6), dpi=150, sharex=True)
    fig.patch.set_facecolor(SURF)
    panels = [("P_grid", "Grid power (kW)", 1e-3), ("T_sup", "Coolant supply (°C)", 1.0),
              ("T_max", "Hottest junction (°C)", 1.0)]
    for ax, (k, lab, sc) in zip(axes, panels):
        _style(ax)
        for p in pols:
            t = np.array(ts[p]["t"]) / 3600
            ax.plot(t, np.array(ts[p][k]) * sc, color=POLICY_COLOR[p], linewidth=1.6, label=LABEL[p])
        ax.set_ylabel(lab, color=INK2, fontsize=9)
    axes[2].axhline(80, color=MUTED, linewidth=1, linestyle="--")
    axes[2].text(0.99, 79.0, "80 °C controller target", color=MUTED, fontsize=8, ha="right", va="top",
                 transform=axes[2].get_yaxis_transform())
    axes[2].axhline(85, color="#d03b3b", linewidth=1, linestyle=":")
    axes[2].text(0.99, 85.6, "85 °C hardware throttle", color="#d03b3b", fontsize=8, ha="right", va="bottom",
                 transform=axes[2].get_yaxis_transform())
    axes[2].set_xlabel("Time (h)", color=INK2, fontsize=9)
    axes[0].legend(frameon=False, ncol=3, fontsize=8.5, loc="upper right", labelcolor=INK)
    axes[0].set_title(f"E001 · {scenario}, seed 0: what each controller does over time (simulated)",
                      fontsize=10, color=INK, loc="left")
    fig.tight_layout()
    fig.savefig(out / "e001_timeseries.png", facecolor=SURF)
    plt.close(fig)


def fig_e002_tornado(R, out, key="joint_vs_independent", n=12):
    t = R["E002"]["tornado"][key]
    items = t["items"][:n][::-1]
    base = t["base"]
    fig, ax = plt.subplots(figsize=(10, 0.36 * len(items) + 1.4), dpi=150)
    fig.patch.set_facecolor(SURF)
    _style(ax)
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    for i, it in enumerate(items):
        lo, hi = it["at_low"] * 100, it["at_high"] * 100
        ax.plot([lo, hi], [i, i], color=AXIS, linewidth=2, zorder=1)
        ax.scatter([lo], [i], s=36, color=SLOTS[0], zorder=2, label="Parameter at low bound" if i == 0 else None)
        ax.scatter([hi], [i], s=36, color=SLOTS[1], zorder=2, label="Parameter at high bound" if i == 0 else None)
    ax.axvline(base * 100, color=INK2, linewidth=1)
    ax.axvline(0, color=MUTED, linewidth=1, linestyle="--")
    ax.set_yticks(range(len(items)), [f"{it['param']} [{it['evidence']}]" for it in items], fontsize=8.5)
    a, b = key.split("_vs_")
    ax.set_xlabel(f"{LABEL[a]} vs {LABEL[b]}: change in energy per successful task (%)", color=INK2, fontsize=9)
    ax.legend(frameon=False, fontsize=8.5, loc="lower right", labelcolor=INK)
    ax.set_title(f"E002 · Sensitivity of {LABEL[a]} vs {LABEL[b]} (mean of 3 seeds; solid line = default {base*100:+.2f}%)",
                 fontsize=10, color=INK, loc="left")
    fig.tight_layout()
    fig.savefig(out / f"e002_tornado_{key}.png", facecolor=SURF)
    plt.close(fig)


def fig_e003(R, out):
    rows = [r for r in R["E003"]["rows"] if r["false_accept"] == 0]
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(10, 4), dpi=150)
    fig.patch.set_facecolor(SURF)
    _style(ax)
    xs = sorted({round(r["rs_plus_rv"], 3) for r in rows})
    ana = [next(r for r in rows if round(r["rs_plus_rv"], 3) == x)["analytic_work_ratio"] - 1 for x in xs]
    ax.plot(xs, np.array(ana) * 100, color=MUTED, linewidth=2, linestyle="--", marker="o", markersize=5,
            label="Analytic change in work")
    for p in ("fixed", "joint"):
        pr = sorted([r for r in rows if r["policy"] == p], key=lambda r: r["rs_plus_rv"])
        x = [r["rs_plus_rv"] for r in pr]
        y = np.array([r["energy_change"] for r in pr]) * 100
        lo = np.array([r["energy_lo"] for r in pr]) * 100
        hi = np.array([r["energy_hi"] for r in pr]) * 100
        ax.plot(x, y, color=POLICY_COLOR[p], linewidth=2, marker="o", markersize=5,
                label=f"Simulated change in energy per successful task ({LABEL[p]})")
        ax.fill_between(x, lo, hi, color=POLICY_COLOR[p], alpha=0.15, linewidth=0)
    be = R["E003"]["break_even_rs_rv"]
    ax.axvline(be, color=INK2, linewidth=1)
    ax.text(be + 0.005, ax.get_ylim()[1] * 0.85, f"analytic break-even\nrs+rv = E[p_small] = {be:.3f}", fontsize=8, color=INK2)
    ax.axhline(0, color=AXIS, linewidth=1)
    ax.set_xlabel("Small-model + verifier cost, relative to the large model (rs + rv)", color=INK2, fontsize=9)
    ax.set_ylabel("Change vs large-model only (%)", color=INK2, fontsize=9)
    ax.legend(frameon=False, fontsize=8, loc="upper left", labelcolor=INK)
    ax.set_title("E003 · Model cascade: realised energy saving vs analytic work saving (S1, 10 seeds; hypothetical quality model)",
                 fontsize=10, color=INK, loc="left")
    fig.tight_layout()
    fig.savefig(out / "e003_routing.png", facecolor=SURF)
    plt.close(fig)


def fig_e006(R, out):
    e = R["E006"]
    rows = e["joint_vs_independent"]
    scen = sorted({r["scenario"] for r in rows})
    plants = ["quasi_steady", "dyn_40kg_1Kmin", "dyn_150kg_0.25Kmin"]
    names = {"quasi_steady": "Quasi-steady plant", "dyn_40kg_1Kmin": "40 kg loop, 1 K/min", "dyn_150kg_0.25Kmin": "150 kg loop, 0.25 K/min"}
    fig, ax = plt.subplots(figsize=(10, 3.8), dpi=150)
    fig.patch.set_facecolor(SURF)
    _style(ax)
    for j, pl in enumerate(plants):
        for i, sc in enumerate(scen):
            r = next((x for x in rows if x["scenario"] == sc and x["plant"] == pl), None)
            if not r:
                continue
            x = i + (j - 1) * 0.22
            ax.plot([x, x], [r["lo"] * 100, r["hi"] * 100], color=SLOTS[j], linewidth=2)
            ax.scatter([x], [r["mean"] * 100], color=SLOTS[j], s=40, zorder=3, label=names[pl] if i == 0 else None,
                       edgecolor=SURF, linewidth=1.5)
    ax.axhline(0, color=AXIS, linewidth=1)
    ax.axhline(-R["threshold"] * 100, color=MUTED, linewidth=1, linestyle="--")
    ax.text(-0.45, -R["threshold"] * 100 + 0.04, "practical threshold (1%)", color=MUTED, fontsize=8, ha="left", va="bottom")
    ax.set_xticks(range(len(scen)), [s_.split("_", 1)[1].replace("_", " ") for s_ in scen])
    ax.set_ylabel("Joint vs independent (%)", color=INK2, fontsize=9)
    ax.legend(frameon=False, fontsize=8.5, loc="lower left", labelcolor=INK)
    ax.set_title(f"E006 v{e['version']} · Joint vs independent energy per successful task under three plant models (mean, 95% CI, 10 seeds)",
                 fontsize=10, color=INK, loc="left")
    fig.tight_layout()
    fig.savefig(out / "e006_joint_vs_independent.png", facecolor=SURF)
    plt.close(fig)


def fig_e008(R, out):
    rows = [r for r in R["E008"]["rows"] if r["scenario"] == "S3_hot"]
    pols = ["independent", "joint", "joint_robust"]
    lab = {"independent": "Independent", "joint": "Joint", "joint_robust": "Joint, self-correcting"}
    fig, ax = plt.subplots(figsize=(10, 3.8), dpi=150)
    fig.patch.set_facecolor(SURF)
    _style(ax)
    x = np.arange(len(rows))
    w = 0.26
    for j, p in enumerate(pols):
        v = [r[p]["over"] or 0 for r in rows]
        ax.bar(x + (j - 1) * w, v, width=w * 0.92, color=SLOTS[[0, 4, 2][j]], label=lab[p], edgecolor=SURF, linewidth=1)
    ax.set_xticks(x, [r["variant"].replace("|", "\n") for r in rows], fontsize=7.5)
    ax.set_ylabel("Chip-seconds above 80 °C (mean of 5 seeds)", color=INK2, fontsize=9)
    ax.legend(frameon=False, fontsize=8.5, loc="upper left", labelcolor=INK)
    ax.set_title("E008 · Overheating under digital-twin mismatch, hot ambient (simulated)", fontsize=10, color=INK, loc="left")
    fig.tight_layout()
    fig.savefig(out / "e008_overheating.png", facecolor=SURF)
    plt.close(fig)


def fig_e001c(R, out):
    c = R["E001C"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), dpi=150)
    fig.patch.set_facecolor(SURF)
    panels = [("compute_vs_fixed_change", "Change in compute-only saving vs fixed (pp)", SLOTS[1], None),
              ("joint_vs_independent_change", "Change in joint vs independent (pp)", SLOTS[4], 0.5)]
    for ax, (key, title, col, band) in zip(axes, panels):
        _style(ax)
        rows = c[key]
        for i, r in enumerate(rows):
            ax.plot([i, i], [100 * r["lo"], 100 * r["hi"]], color=col, lw=2)
            ax.scatter([i], [100 * r["mean"]], color=col, s=40, zorder=3, edgecolor=SURF, linewidth=1.5)
        ax.axhline(0, color=AXIS, lw=1)
        if band:
            ax.axhspan(-band, band, color=GRID, alpha=0.6, zorder=0)
            ax.text(-0.4, band, " pre-registered +/-0.5 pp", color=MUTED, fontsize=8, va="bottom")
        ax.set_xticks(range(len(rows)), [r["scenario"].split("_", 1)[1].replace("_", "\n") for r in rows], fontsize=8)
        ax.set_title(title, fontsize=10, color=INK, loc="left")
    fig.suptitle("E001C vs E001 · seed-paired change after calibrating clock sensitivity (mean, 95% CI, 10 seeds)",
                 fontsize=10, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(out / "e001c_changes.png", facecolor=SURF)
    plt.close(fig)


def fig_e009(R, out):
    e = R["E009"]
    show = ["registry_leakage", "matched_k0.01", "matched_k0.02", "matched_k0.03"]
    names = {"registry_leakage": "Registry leakage", "matched_k0.01": "Matched, kappa 0.01",
             "matched_k0.02": "Matched, kappa 0.02", "matched_k0.03": "Matched, kappa 0.03"}
    rows = {(r["scenario"], r["variant"]): r for r in e["joint_vs_independent"]}
    fig, ax = plt.subplots(figsize=(10, 3.9), dpi=150)
    fig.patch.set_facecolor(SURF)
    _style(ax)
    for j, v in enumerate(show):
        for i, sc in enumerate(e["scenarios"]):
            r = rows.get((sc, v))
            if not r:
                continue
            x = i + (j - 1.5) * 0.18
            ax.plot([x, x], [100 * r["lo"], 100 * r["hi"]], color=SLOTS[j], lw=2)
            ax.scatter([x], [100 * r["mean"]], color=SLOTS[j], s=36, zorder=3, edgecolor=SURF, linewidth=1.5,
                       label=names[v] if i == 0 else None)
    ax.axhline(0, color=AXIS, lw=1)
    ax.axhspan(-100 * R["threshold"], 100 * R["threshold"], color=GRID, alpha=0.5, zorder=0)
    ax.text(-0.45, 100 * R["threshold"] - 0.05, "shaded: inside the 1% practical threshold", color=MUTED, fontsize=8, va="top")
    ax.set_xticks(range(len(e["scenarios"])), [s_.split("_", 1)[1].replace("_", "\n") for s_ in e["scenarios"]], fontsize=8)
    ax.set_ylabel("Joint vs independent (%)", color=INK2, fontsize=9)
    ax.legend(frameon=False, fontsize=8, loc="upper right", labelcolor=INK, ncol=4)
    ax.set_title("E009 · Joint vs independent energy per successful task, leakage matched to the measured slope "
                 "(mean, 95% CI, 5 seeds)", fontsize=10, color=INK, loc="left")
    fig.tight_layout()
    fig.savefig(out / "e009_matched_leakage.png", facecolor=SURF)
    plt.close(fig)


def fig_e010(R, out):
    e = R["E010"]
    pols = [("fixed", "Fixed baseline"), ("independent", "Independent"), ("joint", "Joint")]
    fig, axes = plt.subplots(2, 1, figsize=(10, 6.2), dpi=150, sharey=True)
    fig.patch.set_facecolor(SURF)
    for ax, (pl, ttl) in zip(axes, (("quasi", "Quasi-steady plant"), ("dyn40", "40 kg loop, 1 K/min ramp"))):
        _style(ax)
        conds = [c for c in e["conditions"] if c["plant"] == pl]
        for j, (pol, name) in enumerate(pols):
            xs = [i + (j - 1) * 0.26 for i in range(len(conds))]
            ys = [c["by_policy"].get(pol, {}).get("chip_s_over_target") or 0 for c in conds]
            thr = [c["by_policy"].get(pol, {}).get("chip_s_throttled") or 0 for c in conds]
            allzero = all((c["by_policy"].get(pol, {}).get("chip_s_over_target") or 0) == 0 for c in e["conditions"])
            ax.bar(xs, ys, width=0.24, color=POLICY_COLOR.get(pol, SLOTS[j]),
                   label=(name + (" (0 in every condition)" if allzero else "")) if pl == "quasi" else None)
            for x, y, t in zip(xs, ys, thr):
                if t > 0:
                    ax.text(x, y, f"{t:.0f}", ha="center", va="bottom", fontsize=7, color=INK2)
        ax.set_xticks(range(len(conds)), [f"{c['degradation']}\n{c['t_amb']:.0f} C" for c in conds], fontsize=8)
        ax.set_ylabel("chip-s above 80 C", color=INK2, fontsize=9)
        ax.set_title(ttl, fontsize=10, color=INK, loc="left")
    axes[0].legend(frameon=False, fontsize=8, loc="upper left", labelcolor=INK, ncol=3)
    fig.suptitle("E010 · Time above the 80 C target by cold-plate state and ambient (seed means; labels: chip-s throttled)",
                 fontsize=10, color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(out / "e010_thermal_safety.png", facecolor=SURF)
    plt.close(fig)


def fig_e011(R, out):
    e = R["E011"]
    pols = [("independent", "Independent", POLICY_COLOR["independent"]), ("joint", "Joint (steady-state plan)", POLICY_COLOR["joint"]),
            ("joint_lag", "Joint, lag-aware", SLOTS[2])]
    plants = [("quasi", "Quasi-steady plant"), ("dyn40", "40 kg loop, 1 K/min ramp"), ("dyn150", "150 kg loop, 0.25 K/min ramp")]
    fig, axes = plt.subplots(3, 1, figsize=(10, 8.4), dpi=150, sharey=True)
    fig.patch.set_facecolor(SURF)
    for ax, (pl, ttl) in zip(axes, plants):
        _style(ax)
        conds = [c for c in e["conditions"] if c["plant"] == pl]
        for j, (pol, name, col) in enumerate(pols):
            xs = [i + (j - 1) * 0.26 for i in range(len(conds))]
            ys = [c["by_policy"].get(pol, {}).get("chip_s_over_target") or 0 for c in conds]
            thr = [c["by_policy"].get(pol, {}).get("chip_s_throttled") or 0 for c in conds]
            allzero = all(y == 0 for c in e["conditions"] for y in [c["by_policy"].get(pol, {}).get("chip_s_over_target") or 0])
            ax.bar(xs, ys, width=0.24, color=col, label=(name + (" (0 everywhere)" if allzero else "")) if pl == "quasi" else None)
            for x, y, t in zip(xs, ys, thr):
                if t > 0:
                    ax.text(x, y, f"{t:.0f}", ha="center", va="bottom", fontsize=7, color=INK2)
        ax.set_xticks(range(len(conds)), [f"{c['degradation']}\n{c['t_amb']:.0f} C" for c in conds], fontsize=8)
        ax.set_ylabel("chip-s above 80 C", color=INK2, fontsize=9)
        ax.set_title(ttl, fontsize=10, color=INK, loc="left")
    axes[0].legend(frameon=False, fontsize=8, loc="upper left", labelcolor=INK, ncol=3)
    fig.suptitle("E011 · Time above 80 C: lag-aware joint control vs steady-state joint and independent "
                 "(seed means; labels: chip-s throttled)", fontsize=10, color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(out / "e011_lag_aware.png", facecolor=SURF)
    plt.close(fig)


# ------------------------------------------------------------------------ markdown
def md_assumptions(R) -> str:
    L = ["# 04 · Assumptions register", "",
         "Generated from `ueic/params.py` by `python -m ueic report`. Do not edit by hand.", "",
         "Evidence classes: **A** established physical principle/property · **B** published experimental result · "
         "**C** published simulation · **D** commercial capability · **E** engineering extrapolation · "
         "**F** unvalidated placeholder chosen for this study · **G** design/configuration choice.", "",
         "Classes E and F are *not measurements*. Every E/F value with a range is swept in E002.", "",
         "| Group | Parameter | Value | Unit | Class | Sensitivity range | Source / rationale |",
         "|---|---|---|---|---|---|---|"]
    for p in sorted(R["assumptions"], key=lambda x: (x["group"], x["name"])):
        rng = f"{p['low']:g} – {p['high']:g}" if p["low"] is not None else ""
        L.append(f"| {p['group']} | `{p['name']}` | {p['value']:g} | {p['unit']} | {p['evidence']} | {rng} | {p['source']} |")
    counts = {}
    for p in R["assumptions"]:
        counts[p["evidence"]] = counts.get(p["evidence"], 0) + 1
    L += ["", "Counts by class: " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())), ""]
    return "\n".join(L)


def md_results(R) -> str:
    thr = R["threshold"]
    L = ["# UEIC · Simulation results (generated)", "",
         f"Generated {R['generated_utc']} by `python -m ueic report` from `results/ueic.sqlite`. "
         f"Code SHA-256 `{R['code_sha256'][:16]}…`. Hash-chain check: **{'OK' if R['chain_ok'] else 'FAILED'}** "
         f"({R['chain_msg']}).", "",
         "> **Every number on this page is a simulator output** (provenance `simulator_output`) and is conditional on "
         "the parameter registry (`04_assumptions_register.md`), most of which is class E/F. E001C uses two parameters "
         "measured on a real GPU (M001); every other parameter is still a placeholder. The measurements themselves are "
         "reported in `10_calibration_results.md`. Energy boundary: grid → conversion → accelerators + pump + fans + "
         "chiller (see `00_problem_statement.md`).", ""]
    from .results import verdicts
    L += ["## Pre-registered hypotheses, evaluated mechanically", "", "| Experiment | Verdict | Detail |", "|---|---|---|"]
    for v in sorted(verdicts(R), key=lambda v: v["key"]):
        L.append(f"| {v['key']} | **{v['state']}** | {v['text']} |")
    L.append("")

    # E004
    e4 = R["E004"]
    if e4:
        L += ["## E004 · Time-step convergence", "",
              f"Experiment `{e4['id']}`. Pre-registered criterion: grid energy changes < 0.5% between dt = 0.5 s and 1 s.", "",
              "| Policy | Seed | dt | Change in grid energy vs dt = 0.5 s |", "|---|---|---|---|"]
        for r in e4["rows"]:
            L.append(f"| {r['policy']} | {r['seed']} | {r['variant']} | {pct(r['rel_change_vs_dt0.5'], 3)} |")
        L += ["", "Worst |change| at dt = 1 s: " + ", ".join(f"{k} {v*100:.3f}%" for k, v in e4["worst_abs_dt1_vs_dt05"].items())
              + f". **Criterion {'met' if e4['hypothesis_met'] else 'NOT met'}.**", ""]

    e = R["E001"]
    if e:
        L += ["## E001 · Policy benchmark", "",
              f"Experiment `{e['id']}`: {e['n_runs']} runs, {e['n_failed']} failed. 6 scenarios × 5 policies × 10 paired seeds.", "",
              "![Energy per successful task](../results/figures/e001_energy_per_task.png)", "",
              "### Energy per successful task (kJ, mean [95% CI])", "",
              "| Scenario | " + " | ".join(LABEL[p] for p in e["policies"]) + " |",
              "|---|" + "---|" * len(e["policies"])]
        for s in e["scenarios"]:
            cells = []
            for p in e["policies"]:
                v = e["table"][s][p]["E_per_success_kJ"]
                cells.append(f"{v['mean']:.2f} [{v['lo']:.2f}, {v['hi']:.2f}]")
            L.append(f"| {s} | " + " | ".join(cells) + " |")
        L += ["", "### Paired comparisons of energy per successful task", "",
              f"Practical threshold ±{thr:.0%}. Δ SLO = change in late-or-unfinished tasks per run (mean); "
              "Δ throttled = change in chip-seconds under hardware throttling.", "",
              "| Scenario | Comparison | Change [95% CI] | Verdict | Δ SLO | Δ success rate | Δ throttled |",
              "|---|---|---|---|---|---|---|"]
        for c in e["comparisons"]:
            L.append(f"| {c['scenario']} | {LABEL[c['a']]} vs {LABEL[c['b']]} | {ci(c, 2)} | {c['verdict']} | "
                     f"{c['d_slo_violations']:+.1f} | {c['d_success_rate']*100:+.3f} pp | {c['d_throttled']:+.0f} |")
        h1, h2 = e["H1"], e["H2"]
        L += ["", "### Hypotheses", "",
              f"* **H1** (joint < independent with CI below zero in ≥ {h1['required']} of 6 scenarios, guards held): "
              f"**{'supported' if h1['supported'] else 'not supported'}**. CI below zero in "
              f"{len(h1['scenarios_ci_below_zero'])}/6 ({', '.join(h1['scenarios_ci_below_zero']) or 'none'}); "
              f"beyond the {thr:.0%} practical threshold in {len(h1['scenarios_meaningful'])}/6 "
              f"({', '.join(h1['scenarios_meaningful']) or 'none'}).",
              f"* **H2** (every optimising policy below fixed in every scenario): energy criterion "
              f"**{'met' if h2['energy_criterion_met'] else 'not met'}**"
              + (f" (failures: {h2['energy_failures']})" if h2['energy_failures'] else "") + "; pre-registered quality guard "
              + ("**held**." if not h2["guard_failures"] else
                 f"**failed in {len(h2['guard_failures'])} of {len([c for c in e['comparisons'] if c['b']=='fixed'])} comparisons** "
                 "(SLO violations or success rate slightly worse than fixed; see table). "
                 "Formally, H2 is therefore **not supported as pre-registered**."), ""]
        L += ["### Thermal and quality guards by policy (means over seeds)", "",
              "| Scenario | Policy | Success rate | SLO violations | p95 latency (s) | Peak T_j (°C) | chip·s > 80 °C | chip·s throttled | Reusable heat ≥45 °C (kWh) |",
              "|---|---|---|---|---|---|---|---|---|"]
        for s in e["scenarios"]:
            for p in e["policies"]:
                t = e["table"][s][p]
                L.append(f"| {s} | {LABEL[p]} | {t['success_rate']['mean']:.4f} | {t['slo_violations']['mean']:.1f} | "
                         f"{t['latency_p95_s']['mean']:.1f} | {t['peak_T_j_C']['mean']:.1f} | {t['chip_s_over_target']['mean']:.0f} | "
                         f"{t['chip_s_throttled']['mean']:.0f} | {t['Q_reusable_kWh']['mean']:.2f} |")
        L += ["", "### Energy breakdown (kWh per run, means)", "", "![Breakdown](../results/figures/e001_breakdown.png)", "",
              "| Scenario | Policy | Grid | IT | Conversion | Pump | Fans | Chiller | Grid/IT |", "|---|---|---|---|---|---|---|---|---|"]
        for s in e["scenarios"]:
            for p in e["policies"]:
                t = e["table"][s][p]
                L.append(f"| {s} | {LABEL[p]} | {t['E_grid_kWh']['mean']:.3f} | {t['E_it_kWh']['mean']:.3f} | "
                         f"{t['E_conv_loss_kWh']['mean']:.3f} | {t['E_pump_kWh']['mean']:.3f} | {t['E_fan_kWh']['mean']:.3f} | "
                         f"{t['E_chiller_kWh']['mean']:.3f} | {t['grid_to_it_ratio']['mean']:.3f} |")
        L += ["", "![Time series](../results/figures/e001_timeseries.png)", "",
              f"Controller overhead (measured wall-clock on the simulation host, not modelled energy): joint "
              f"{e['table'][e['scenarios'][0]]['joint']['controller_wall_mean_ms']['mean']:.2f} ms per decision, "
              f"independent {e['table'][e['scenarios'][0]]['independent']['controller_wall_mean_ms']['mean']:.2f} ms.", ""]

    e2 = R["E002"]
    if e2:
        L += ["## E002 · One-at-a-time sensitivity", "",
              f"Experiment `{e2['id']}`: {e2['n_runs']} runs, {e2['n_failed']} failed. S1, 2 h window, 3 seeds per cell "
              "(CIs are wide; use for ranking).", "",
              "![Tornado joint vs independent](../results/figures/e002_tornado_joint_vs_independent.png)", "",
              "![Tornado joint vs fixed](../results/figures/e002_tornado_joint_vs_fixed.png)", ""]
        for key in ("joint_vs_independent", "joint_vs_fixed"):
            t = e2["tornado"][key]
            a, b = key.split("_vs_")
            L += [f"### {LABEL[a]} vs {LABEL[b]} (default {pct(t['base'], 2)})", "",
                  "| Rank | Parameter | Class | Range | At low | At high | Swing |", "|---|---|---|---|---|---|---|"]
            for i, it in enumerate(t["items"][:15], 1):
                L.append(f"| {i} | `{it['param']}` | {it['evidence']} | {it['low_value']:g} – {it['high_value']:g} {it['unit']} | "
                         f"{pct(it['at_low'], 2)} | {pct(it['at_high'], 2)} | {it['swing']*100:.2f} pp |")
            L.append("")
        L += [f"Variants where joint used **more** energy than independent (mean): "
              f"{', '.join(e2['joint_worse_mean']) or 'none'}. With CI entirely above zero: "
              f"{', '.join(e2['joint_worse_ci']) or 'none'}.", ""]
        thr_v = sorted({k.split('|')[0] for k, v in e2["throttled"].items() if v and v > 0})
        L += [f"Variants in which any policy triggered hardware throttling: {', '.join(thr_v) or 'none'}.", ""]

    e3 = R["E003"]
    if e3:
        L += ["## E003 · Model-routing cascade", "",
              f"Experiment `{e3['id']}`: {e3['n_runs']} runs, {e3['n_failed']} failed. **Quality model is a hypothetical "
              f"placeholder (class F)**; the transferable results are the break-even condition and the work-vs-energy gap.", "",
              "![Routing](../results/figures/e003_routing.png)", "",
              "| Variant | Policy | rs+rv | Analytic Δ work | Simulated Δ work [CI] | Δ energy per success [CI] | Verdict | Δ success rate | Δ p95 latency |",
              "|---|---|---|---|---|---|---|---|---|"]
        for r in e3["rows"]:
            L.append(f"| {r['variant']} | {LABEL[r['policy']]} | {r['rs_plus_rv']:.2f} | {pct(r['analytic_work_ratio']-1)} | "
                     f"{pct(r['sim_work_change'])} [{pct(r['sim_work_lo'])}, {pct(r['sim_work_hi'])}] | "
                     f"{pct(r['energy_change'])} [{pct(r['energy_lo'])}, {pct(r['energy_hi'])}] | {r['verdict']} | "
                     f"{r['d_success_rate']*100:+.2f} pp | {pct(r['p95_latency_change'])} |")
        L += ["", f"Analytic break-even with a perfect verifier: rs + rv = E[p_small] = {e3['break_even_rs_rv']:.3f}.", ""]

    e5 = R["E005"]
    if e5:
        L += ["## E005 · Digital-twin mismatch", "",
              f"Experiment `{e5['id']}`: {e5['n_runs']} runs, {e5['n_failed']} failed. 5 seeds.", "",
              "| Scenario | Truth \\| twin | Joint vs independent [CI] | Verdict | Joint chip·s > 80 °C | Independent chip·s > 80 °C | Joint throttled | Independent throttled | Joint peak T | Independent peak T |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for r in e5["rows"]:
            L.append(f"| {r['scenario']} | {r['variant']} | {pct(r['joint_vs_independent'], 2)} [{pct(r['lo'], 2)}, {pct(r['hi'], 2)}] | "
                     f"{r['verdict']} | {num(r['joint_chip_s_over_target'], 0)} | {num(r['independent_chip_s_over_target'], 0)} | "
                     f"{num(r['joint_chip_s_throttled'], 0)} | {num(r['independent_chip_s_throttled'], 0)} | "
                     f"{num(r['joint_peak_T_j_C'], 1)} | {num(r['independent_peak_T_j_C'], 1)} |")
        L.append("")

    e6 = R.get("E006")
    if e6:
        L += [f"## E006 · Dynamic coolant loop (v{e6['version']})", "",
              f"Experiment `{e6['id']}`: {e6['n_runs']} runs, {e6['n_failed']} failed"
              + (f"; supersedes `{e6['supersedes']}` (cold-start confound, see research log)" if e6["supersedes"] else "")
              + f". Runs with loop-storage change above 0.5% of grid energy: {e6['storage_warnings']}.", "",
              "![E006](../results/figures/e006_joint_vs_independent.png)", "",
              "| Scenario | Plant | Joint vs independent [95% CI] | Verdict |", "|---|---|---|---|"]
        for r in e6["joint_vs_independent"]:
            L.append(f"| {r['scenario']} | {r['plant']} | {ci(r, 2)} | {r['verdict']} |")
        L += ["", "| Scenario | Plant | Policy | chip·s > 80 °C | chip·s throttled | Peak T_j (°C) | Loop storage (% of grid) |",
              "|---|---|---|---|---|---|---|"]
        for t in e6["thermal"]:
            L.append(f"| {t['scenario']} | {t['plant']} | {t['policy']} | {num(t['over'], 0)} | {num(t['throttled'], 0)} | "
                     f"{num(t['peak'], 1)} | {t['storage_pct']:+.2f}% |")
        L.append("")
    e7 = R.get("E007")
    if e7:
        L += ["## E007 · Move suppression", "", f"Experiment `{e7['id']}`: {e7['n_runs']} runs, {e7['n_failed']} failed. Joint controller only.", "",
              "| Scenario | Threshold | dt (s) | Action changes | Clock | Flow | Supply temp | Energy per success (kJ) |",
              "|---|---|---|---|---|---|---|---|"]
        for x in e7["switching"]:
            L.append(f"| {x['scenario']} | {x['threshold']:.1%} | {x['dt']:g} | {x['action_changes']:.1f} | {x['clock_changes']:.1f} | "
                     f"{x['flow_changes']:.1f} | {x['tsup_changes']:.1f} | {x['E_per_success_kJ']:.3f} |")
        L += ["", "| Scenario | Threshold | Energy vs no threshold [95% CI] |", "|---|---|---|"]
        for x in e7["energy_vs_no_threshold"]:
            L.append(f"| {x['scenario']} | {x['variant']} | {ci(x, 3)} |")
        L += ["", "| Scenario | Threshold | Worst per-seed change dt 1 s vs 0.5 s | Mean | Seeds |", "|---|---|---|---|---|"]
        for d in e7["dt_sensitivity"]:
            L.append(f"| {d['scenario']} | {d['threshold']:.1%} | {d['max']:.3%} | {d['mean']:.3%} | {d['n']} |")
        L.append("")
    e8 = R.get("E008")
    if e8:
        L += ["## E008 · Self-correcting joint control under twin mismatch", "",
              f"Experiment `{e8['id']}`: {e8['n_runs']} runs, {e8['n_failed']} failed. 5 seeds.", "",
              "![E008](../results/figures/e008_overheating.png)", "",
              "| Scenario | Truth \\| twin | Self-correcting vs independent | vs joint | Joint vs independent | chip·s > 80 °C (I / J / J-sc) | throttled (I / J / J-sc) |",
              "|---|---|---|---|---|---|---|"]
        for r in e8["rows"]:
            c = lambda k: (f"{pct(r[k]['mean'], 2)} [{pct(r[k]['lo'], 2)}, {pct(r[k]['hi'], 2)}]" if r[k] else "n/a")
            L.append(f"| {r['scenario']} | {r['variant']} | {c('joint_robust_vs_independent')} | {c('joint_robust_vs_joint')} | "
                     f"{c('joint_vs_independent')} | {num(r['independent']['over'], 0)} / {num(r['joint']['over'], 0)} / "
                     f"{num(r['joint_robust']['over'], 0)} | {num(r['independent']['throttled'], 0)} / {num(r['joint']['throttled'], 0)} / "
                     f"{num(r['joint_robust']['throttled'], 0)} |")
        L.append("")

    c = R.get("E001C")
    if c:
        ov = c["spec"].get("calibration_source", {}).get("overrides", {})
        L += ["## E001C · Policy benchmark with measured clock sensitivity", "",
              f"Experiment `{c['id']}`: {c['n_runs']} runs, {c['n_failed']} failed. Same design, seeds and workloads as "
              f"E001 (`{c['original_id']}`), with " + ", ".join(f"`{k}` = {v['value']}" for k, v in ov.items())
              + " from M001. Changes are seed-paired against E001.", "",
              "![E001C](../results/figures/e001c_changes.png)", "",
              "| Scenario | Compute-only vs fixed: E001 | E001C | change (pp, 95% CI) | Joint vs independent: E001 | E001C | change (pp, 95% CI) |",
              "|---|---|---|---|---|---|---|"]
        ji = {r["scenario"]: r for r in c["joint_vs_independent_change"]}
        for r in c["compute_vs_fixed_change"]:
            j = ji.get(r["scenario"])
            pp = lambda x: f"{100 * x['mean']:+.2f} [{100 * x['lo']:+.2f}, {100 * x['hi']:+.2f}]"
            L.append(f"| {r['scenario']} | {pct(r['orig'])} | {pct(r['calibrated'])} | {pp(r)} | "
                     + (f"{pct(j['orig'], 2)} | {pct(j['calibrated'], 2)} | {pp(j)} |" if j else "n/a | n/a | n/a |"))
        L += ["", "### Energy per successful task in E001C (kJ, mean [95% CI])", "",
              "| Scenario | " + " | ".join(LABEL[p] for p in c["policies"]) + " |",
              "|---|" + "---|" * len(c["policies"])]
        for sc in c["scenarios"]:
            cells = []
            for p_ in c["policies"]:
                t = c["table"].get(sc, {}).get(p_, {}).get("E_per_success_kJ")
                cells.append(f"{t['mean']:.2f} [{t['lo']:.2f}, {t['hi']:.2f}]" if t else "n/a")
            L.append(f"| {sc} | " + " | ".join(cells) + " |")
        L.append("")

    e9 = R.get("E009")
    if e9:
        ms = e9["spec"].get("measurement_source", {})
        L += ["## E009 · Joint vs independent with leakage matched to the measured slope", "",
              f"Experiment `{e9['id']}`: {e9['n_runs']} runs, {e9['n_failed']} failed. Leakage set so the simulator's "
              f"chip power rises {100 * ms.get('target_rel_per_K', float('nan')):.3f}% per K at s = "
              f"{ms.get('operating_point', {}).get('s', float('nan')):.3f}, {ms.get('operating_point', {}).get('T_C', float('nan'))} °C, "
              f"as measured on the RTX 5070 (registry: {100 * ms.get('registry_rel_per_K', float('nan')):.3f}% per K). "
              "Clock sensitivity from M001 throughout.", "",
              "![E009](../results/figures/e009_matched_leakage.png)", "",
              "| Scenario | " + " | ".join(v.replace("_", " ") for v in e9["variants"]) + " |",
              "|---|" + "---|" * len(e9["variants"])]
        rows = {(r["scenario"], r["variant"]): r for r in e9["joint_vs_independent"]}
        for sc in e9["scenarios"]:
            L.append(f"| {sc} | " + " | ".join(
                (f"{pct(rows[(sc, v)]['mean'], 2)} [{pct(rows[(sc, v)]['lo'], 2)}, {pct(rows[(sc, v)]['hi'], 2)}]"
                 if (sc, v) in rows else "n/a") for v in e9["variants"]) + " |")
        th = {(t["scenario"], t["variant"], t["policy"], t["metric"]): t["mean"] for t in e9["thermal"]}
        L += ["", "### Thermal guards (seed means): chip·s above 80 °C, independent / joint", "",
              "| Scenario | " + " | ".join(v.replace("_", " ") for v in e9["variants"]) + " |",
              "|---|" + "---|" * len(e9["variants"])]
        for sc in e9["scenarios"]:
            L.append(f"| {sc} | " + " | ".join(
                f"{num(th.get((sc, v, 'independent', 'chip_s_over_target')), 0)} / {num(th.get((sc, v, 'joint', 'chip_s_over_target')), 0)}"
                for v in e9["variants"]) + " |")
        L.append("")

    e10 = R.get("E010")
    if e10:
        L += ["## E010 · Thermal safety under cooling degradation and heat", "",
              f"Experiment `{e10['id']}`: {e10['n_runs']} runs, {e10['n_failed']} failed. S6 load profile; leakage matched "
              "to the measured slope and clock sensitivity from M001 in every cell; the twin knows the true cold-plate "
              "state. Thermal values are seed means over 5 seeds; energy is paired.", "",
              "![E010](../results/figures/e010_thermal_safety.png)", "",
              "| Plant | Cold plate | Ambient | chip·s > 80 °C (F / I / J) | throttled (F / I / J) | peak °C (F / I / J) | Joint vs independent | Joint vs fixed |",
              "|---|---|---|---|---|---|---|---|"]
        for c in e10["conditions"]:
            b = c["by_policy"]
            t3 = lambda m, d: " / ".join(num(b.get(p_, {}).get(m), d) for p_ in ("fixed", "independent", "joint"))
            ji, jf = c["joint_vs_independent"], c["joint_vs_fixed"]
            L.append(f"| {c['plant']} | {c['degradation']} | {c['t_amb']:.0f} °C | {t3('chip_s_over_target', 0)} | "
                     f"{t3('chip_s_throttled', 0)} | {t3('peak_T_j_C', 1)} | "
                     + (f"{pct(ji['mean'], 2)} [{pct(ji['lo'], 2)}, {pct(ji['hi'], 2)}]" if ji else "n/a") + " | "
                     + (f"{pct(jf['mean'], 1)} [{pct(jf['lo'], 1)}, {pct(jf['hi'], 1)}]" if jf else "n/a") + " |")
        L.append("")

    e11 = R.get("E011")
    if e11:
        L += ["## E011 · Lag-aware joint control", "",
              f"Experiment `{e11['id']}`: {e11['n_runs']} runs, {e11['n_failed']} failed. As E010 plus a 150 kg loop with a "
              "0.25 K/min ramp; `joint_lag` checks thermal safety at the supply temperature the chips will actually see "
              "before the next decision. Thermal values are seed means over 5 seeds; energy is paired.", "",
              "![E011](../results/figures/e011_lag_aware.png)", "",
              "| Plant | Cold plate | Ambient | chip·s > 80 °C (I / J / JL) | throttled (I / J / JL) | late tasks (I / J / JL) | JL vs J | JL vs I |",
              "|---|---|---|---|---|---|---|---|"]
        for c in e11["conditions"]:
            b = c["by_policy"]
            t3 = lambda m, d: " / ".join(num(b.get(p_, {}).get(m), d) for p_ in ("independent", "joint", "joint_lag"))
            lj, li = c["lag_vs_joint"], c["lag_vs_independent"]
            L.append(f"| {c['plant']} | {c['degradation']} | {c['t_amb']:.0f} °C | {t3('chip_s_over_target', 0)} | "
                     f"{t3('chip_s_throttled', 0)} | {t3('slo_violations', 1)} | "
                     + (f"{pct(lj['mean'], 2)} [{pct(lj['lo'], 2)}, {pct(lj['hi'], 2)}]" if lj else "n/a") + " | "
                     + (f"{pct(li['mean'], 2)} [{pct(li['lo'], 2)}, {pct(li['hi'], 2)}]" if li else "n/a") + " |")
        L.append("")

    L += ["## Experiment register (including superseded and failed)", "",
          "| Id | Status | Runs | Title |", "|---|---|---|---|"]
    for x in R["experiments"]:
        L.append(f"| `{x['id']}` | {x['status']} | {json.dumps(x['summary']) if x['summary'] else ''} | {x['title']} |")
    L.append("")
    return "\n".join(L)


def md_log(R) -> str:
    L = ["# Research log", "", "Exported from the append-only `research_log` table. Do not edit by hand; add entries "
         "with `python -m ueic log \"...\"`.", ""]
    for utc, entry in R["research_log"]:
        L.append(f"* **{utc}** · {entry}")
    return "\n".join(L) + "\n"


def build_report(store, root: Path) -> str:
    R = compute_all(store)
    figs = root / "results" / "figures"
    figs.mkdir(parents=True, exist_ok=True)
    if R["E001"]:
        fig_e001_energy(R, figs)
        fig_e001_breakdown(R, figs)
        fig_e001_timeseries(R, figs)
    if R["E002"]:
        fig_e002_tornado(R, figs, "joint_vs_independent")
        fig_e002_tornado(R, figs, "joint_vs_fixed")
    if R["E003"]:
        fig_e003(R, figs)
    if R.get("E006"):
        fig_e006(R, figs)
    if R.get("E008"):
        fig_e008(R, figs)
    if R.get("E001C"):
        fig_e001c(R, figs)
    if R.get("E009"):
        fig_e009(R, figs)
    if R.get("E010"):
        fig_e010(R, figs)
    if R.get("E011"):
        fig_e011(R, figs)
    docs = root / "docs"
    (docs / "RESULTS.md").write_text(md_results(R))
    (docs / "04_assumptions_register.md").write_text(md_assumptions(R))
    (docs / "research_log.md").write_text(md_log(R))
    (root / "results" / "results_summary.json").write_text(json.dumps(R, indent=1, default=str))
    return str(docs / "RESULTS.md")
