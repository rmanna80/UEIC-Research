"""Generate results/dashboard.html: a self-contained research dashboard built
from the store. All data is embedded; charts are drawn in SVG by inline JS.

The cold-plate explorer is backed by a grid computed here with the same
physics module the simulator uses (steady state, all accelerators busy on
compute-bound work), so the page never re-implements the physics in JS.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import physics as ph
from .params import make_config
from .results import POLICY_ORDER, compute_all, verdicts


def explorer_grid(cfg=None) -> dict:
    cfg = cfg or make_config()
    S = np.round(np.arange(cfg.s_min, 1.0001, 0.1), 2)
    T = np.arange(cfg.t_sup_min, cfg.t_sup_max + 0.5, 1.0)
    F = np.array([0.5, 0.75, 1.0, 1.25, 1.5, 2.0])
    AMB = np.array([0.0, 8.0, 20.0, 28.0, 35.0])
    s = S[:, None, None, None]
    t = T[None, :, None, None]
    f = F[None, None, :, None]
    a = AMB[None, None, None, :]
    R = ph.r_total(f, cfg)
    A = ph.temp_independent_power(s, 1.0, cfg)
    L = cfg.p_leak_ref * ph.voltage_ratio(s, cfg)
    Tj, ok = ph.steady_temperature(t, R, A, L, cfg)
    Tj_b = np.broadcast_to(Tj, (len(S), len(T), len(F), 1))
    P = A + L * np.exp(cfg.kappa_leak * (np.where(ok, Tj, cfg.t_leak_ref) - cfg.t_leak_ref))
    P = np.broadcast_to(P, Tj_b.shape)
    N = cfg.n_accel
    P_pump = np.broadcast_to(ph.pump_power(f, cfg), Tj_b.shape)
    pl = ph.plant(N * P + P_pump, t, f, a, cfg)
    P_it = N * P
    P_grid = P_it / cfg.eta_conv + P_pump + pl["P_fan"] + pl["W_ch"]
    thr = N * s ** cfg.beta_compute               # nominal work-seconds per second
    J_per_work = P_grid / thr
    okb = np.broadcast_to(ok, P_grid.shape)
    def r(x, d):
        x = np.broadcast_to(x, P_grid.shape)
        return np.where(okb, np.round(x, d), np.nan).tolist()
    return {
        "s": S.tolist(), "t_sup": T.tolist(), "flow": F.tolist(), "t_amb": AMB.tolist(),
        "dims": "[clock][t_sup][flow][t_amb]",
        "Tj": r(Tj_b, 2), "P_chip": r(P, 1), "P_pump": r(P_pump, 1), "P_fan": r(pl["P_fan"], 1),
        "W_ch": r(pl["W_ch"], 1), "P_grid": r(P_grid, 1), "J_per_work": r(J_per_work, 2),
        "R_cond": cfg.r_cond, "R_conv": np.round(ph.r_conv(F, cfg), 5).tolist(),
        "R_cal": np.round(ph.r_caloric(F, cfg), 5).tolist(), "lpm": cfg.flow_design_lpm,
        "t_target": cfg.t_target, "t_throttle": cfg.t_throttle, "n": N,
    }


def _m001(m: dict | None) -> dict | None:
    """Measured curves plus the simulator's prediction at the same clocks and temperatures."""
    if not m or not m.get("energy_per_work"):
        return None
    from . import physics as ph
    from .params import make_config
    cfg = make_config()
    ec = m["energy_per_work"]["compute"]
    pts = ec["points"]
    top = pts[-1]
    p_top = float(ph.chip_power(1.0, top["temp_C"], 1.0, cfg))
    beta_cal = (m.get("accepted") or {}).get("beta_compute", {}).get("value", cfg.beta_compute)
    sim = [{"s": x["s"], "P_rel": float(ph.chip_power(x["s"], x["temp_C"], 1.0, cfg)) / p_top} for x in pts]
    for r in sim:
        r["E_rel"] = r["P_rel"] / r["s"] ** cfg.beta_compute
        r["E_rel_cal"] = r["P_rel"] / r["s"] ** beta_cal
    return {"id": m["id"], "device": m.get("device"), "accepted": m.get("accepted"), "rejected": m.get("rejected"),
            "compute": ec, "memory": m["energy_per_work"].get("memory"), "sim": sim}


def _slim(R: dict) -> dict:
    """Keep what the page needs; drop bulky fields."""
    D = {k: R[k] for k in ("generated_utc", "code_sha256", "chain_ok", "chain_msg", "threshold", "assumptions",
                           "research_log", "experiments", "E004")}
    e1 = R["E001"]
    if e1:
        ts = {}
        for sc, by in e1["timeseries"].items():
            ts[sc] = {p: {k: v[k] for k in ("t", "P_grid", "T_sup", "T_max", "flow", "s_c", "s_m") if k in v}
                      for p, v in by.items()}
        D["E001"] = {k: e1[k] for k in ("id", "scenarios", "policies", "scenario_info", "table", "comparisons",
                                        "H1", "H2", "n_runs", "n_failed")}
        D["E001"]["timeseries"] = ts
        D["E001"]["hypothesis"] = e1["spec"]["hypothesis"]
    else:
        D["E001"] = None
    for k in ("E006", "E007", "E008"):
        x = R.get(k)
        D[k] = ({kk: vv for kk, vv in x.items() if kk != "spec"} | {"hypothesis": x["spec"]["hypothesis"],
                 "disclosure": x["spec"].get("disclosure", "")}) if x else None
    for k in ("E002", "E003", "E005"):
        x = R[k]
        if x:
            D[k] = {kk: vv for kk, vv in x.items() if kk != "spec"}
            D[k]["hypothesis"] = x["spec"]["hypothesis"]
        else:
            D[k] = None
    D["M001"] = _m001(R.get("M001"))
    c = R.get("E001C")
    D["E001C"] = ({k: c[k] for k in ("id", "original_id", "n_runs", "n_failed", "compute_vs_fixed_change",
                                     "joint_vs_independent_change", "HC1", "HC2", "HC3", "H1", "H2")}
                  | {"hypothesis": c["spec"]["hypothesis"], "disclosure": c["spec"].get("disclosure", ""),
                     "overrides": c["spec"].get("calibration_source", {}).get("overrides", {})}) if c else None
    D["verdicts"] = sorted(verdicts(R), key=lambda v: v["key"])
    D["policy_order"] = POLICY_ORDER
    D["explorer"] = explorer_grid()
    return D


def build_dashboard(store, root: Path) -> str:
    R = compute_all(store)
    D = _slim(R)
    data = json.dumps(D, separators=(",", ":"), default=lambda o: None).replace("</", "<\\/")
    data = data.replace("NaN", "null")
    html = TEMPLATE.replace("/*__DATA__*/", data)
    out = root / "results" / "dashboard.html"
    out.write_text(html, encoding="utf-8")
    return str(out)


TEMPLATE = r"""<meta charset="utf-8">
<title>UEIC Research Dashboard</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
/* Layout: instrument-panel shell; header strip with provenance stamp and tabs, one working column per tab. */
:root{
  --bg:#f3f5f4; --surface:#fcfcfb; --sunk:#eaeeec; --ink:#101615; --ink2:#4a5452; --muted:#7a8582;
  --rule:#dde2e0; --axis:#c3c8c5; --accent:#0b6a6c; --accent-ink:#ffffff;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4;
  --good:#0ca30c; --warn:#fab219; --serious:#ec835a; --crit:#d03b3b; --good-ink:#006300;
  --seq1:#cde2fb; --seq2:#9ec5f4; --seq3:#6da7ec; --seq4:#3987e5; --seq5:#256abf; --seq6:#184f95; --seq7:#0d366b;
  --f-display:"IBM Plex Sans Condensed","Arial Narrow",system-ui,sans-serif;
  --f-body:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --f-mono:"IBM Plex Mono",ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;
  --r:6px;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#0e1211; --surface:#161b1a; --sunk:#1d2321; --ink:#edf1ef; --ink2:#b9c3c0; --muted:#808b88;
  --rule:#2a3230; --axis:#3a4341; --accent:#45b8b1; --accent-ink:#06201f;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; --good-ink:#0ca30c;
  --seq1:#104281; --seq2:#184f95; --seq3:#1c5cab; --seq4:#2a78d6; --seq5:#5598e7; --seq6:#86b6ef; --seq7:#cde2fb;
  color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#0e1211; --surface:#161b1a; --sunk:#1d2321; --ink:#edf1ef; --ink2:#b9c3c0; --muted:#808b88;
  --rule:#2a3230; --axis:#3a4341; --accent:#45b8b1; --accent-ink:#06201f;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; --good-ink:#0ca30c;
  --seq1:#104281; --seq2:#184f95; --seq3:#1c5cab; --seq4:#2a78d6; --seq5:#5598e7; --seq6:#86b6ef; --seq7:#cde2fb;
  color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:var(--f-body);font-size:14px;line-height:1.5;
  padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:0 48px}
.wrap{max-width:1180px;margin:0 auto}
header{display:flex;flex-direction:column;gap:12px;padding-block:20px 0}
.top{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:12px}
h1{font-family:var(--f-display);font-weight:600;font-size:28px;letter-spacing:.01em;margin:0;text-wrap:balance}
h1 small{display:block;font-family:var(--f-body);font-weight:400;font-size:13px;color:var(--ink2);letter-spacing:0}
.stamp{font-family:var(--f-mono);font-size:11.5px;color:var(--ink2);border:1px solid var(--rule);background:var(--surface);
  border-radius:var(--r);padding:6px 10px;display:flex;flex-wrap:wrap;gap:4px 14px}
.stamp b{color:var(--ink);font-weight:500}
.banner{display:flex;gap:10px;align-items:flex-start;background:var(--surface);border:1px solid var(--rule);
  border-left:4px solid var(--warn);border-radius:var(--r);padding:10px 14px;font-size:13px;color:var(--ink2)}
.banner strong{color:var(--ink)}
nav{display:flex;gap:2px;overflow-x:auto;border-bottom:1px solid var(--rule);scrollbar-width:thin}
nav button{font:500 13px var(--f-body);color:var(--ink2);background:none;border:0;border-bottom:2px solid transparent;
  padding:10px 12px;cursor:pointer;white-space:nowrap}
nav button[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--accent)}
nav button:hover{color:var(--ink)}
button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
main{padding-top:20px}
section.tab{display:flex;flex-direction:column;gap:18px}
h2{font-family:var(--f-display);font-weight:600;font-size:19px;margin:0;text-wrap:balance}
h3{font-family:var(--f-display);font-weight:500;font-size:15px;margin:0;color:var(--ink)}
p{margin:0;max-width:72ch}
.lede{color:var(--ink2);max-width:80ch}
.panel{background:var(--surface);border:1px solid var(--rule);border-radius:var(--r);padding:16px;display:flex;flex-direction:column;gap:12px;min-width:0}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
.verdicts{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.vcard{background:var(--surface);border:1px solid var(--rule);border-radius:var(--r);padding:12px 14px;display:flex;flex-direction:column;gap:6px}
.vcard .k{font-family:var(--f-mono);font-size:12px;color:var(--muted)}
.pill{display:inline-flex;align-items:center;gap:6px;font:500 12px var(--f-body);padding:2px 9px;border-radius:999px;
  border:1px solid var(--rule);background:var(--sunk);color:var(--ink);width:max-content}
.pill::before{content:"";width:8px;height:8px;border-radius:50%;background:var(--muted)}
.pill.good::before{background:var(--good)} .pill.warn::before{background:var(--warn)}
.pill.serious::before{background:var(--serious)} .pill.crit::before{background:var(--crit)}
ul.findings{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:8px;max-width:90ch}
ul.findings li::marker{color:var(--accent)}
.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.chip{font:500 12.5px var(--f-body);border:1px solid var(--rule);background:var(--surface);color:var(--ink2);
  border-radius:999px;padding:5px 11px;cursor:pointer}
.chip[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
label.ctl{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--ink2)}
select,input[type=search]{font:13px var(--f-body);color:var(--ink);background:var(--surface);border:1px solid var(--rule);border-radius:var(--r);padding:5px 8px}
input[type=range]{accent-color:var(--accent)}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--rule);vertical-align:top}
th{font-weight:600;color:var(--ink2);font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}
td.n,th.n{text-align:right;font-family:var(--f-mono);font-variant-numeric:tabular-nums;white-space:nowrap}
td.mono{font-family:var(--f-mono);font-size:12px}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;color:var(--ink)}
.legend button{font:inherit;color:inherit;background:none;border:0;padding:0;cursor:pointer;display:flex;align-items:center}
.legend button[aria-pressed="false"]{opacity:.35}
svg{display:block;overflow:visible}
svg text{font-family:var(--f-body);font-size:11px;fill:var(--ink2)}
svg .ax{stroke:var(--axis)} svg .gr{stroke:var(--rule)}
.tip{position:fixed;pointer-events:none;z-index:20;background:var(--surface);color:var(--ink);border:1px solid var(--rule);
  border-radius:var(--r);padding:8px 10px;font-size:12px;box-shadow:0 4px 18px rgba(0,0,0,.12);max-width:280px}
.tip .t{font-weight:600;margin-bottom:4px}
.tip .row{display:flex;justify-content:space-between;gap:12px;font-family:var(--f-mono);font-variant-numeric:tabular-nums}
.note{font-size:12.5px;color:var(--muted)}
.ladder text{font-size:11.5px}
.readout{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px}
.readout div{background:var(--sunk);border-radius:var(--r);padding:8px 10px;display:flex;flex-direction:column}
.readout span{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.readout b{font-family:var(--f-mono);font-weight:500;font-size:15px;font-variant-numeric:tabular-nums}
.log li{margin-bottom:8px}
.log time{font-family:var(--f-mono);font-size:11.5px;color:var(--muted);margin-right:8px}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>

<script type="application/json" id="data">/*__DATA__*/</script>

<div class="wrap">
<header>
  <div class="top">
    <h1>UEIC Research Dashboard<small>Unified Energy-Intelligent Computing · simulation study with a first hardware calibration</small></h1>
    <div class="stamp" id="stamp"></div>
  </div>
  <div class="banner"><span aria-hidden="true">⚠</span><div><strong>Simulated results, except the Hardware tab.</strong>
  Every other value comes from the UEIC simulator and depends on the assumptions register, where most hardware and plant values are
  class E (extrapolation) or F (placeholder); E001C uses two values measured on one real GPU. Energy boundary: grid → power conversion → accelerators, coolant pump, heat-rejection fans, trim chiller.
  The Hardware tab shows measurements of GPU board power only.</div></div>
  <nav role="tablist" id="tabs"></nav>
</header>
<main id="main"></main>
</div>
<div class="tip" id="tip" hidden></div>

<script>
const D = JSON.parse(document.getElementById('data').textContent);
const NS = 'http://www.w3.org/2000/svg';
const $ = (s, el = document) => el.querySelector(s);
const LABEL = {fixed:'Fixed baseline', compute_only:'Compute-only', cooling_only:'Cooling-only', independent:'Independent', joint:'Joint', joint_robust:'Joint, self-correcting'};
const PCOL = {fixed:'var(--s1)', compute_only:'var(--s2)', cooling_only:'var(--s3)', independent:'var(--s4)', joint:'var(--s5)', joint_robust:'var(--s3)'};
const fin = v => v !== null && v !== undefined && isFinite(v);
const fmt = (v, d = 1) => fin(v) ? Number(v).toFixed(d) : '–';
const pct = (v, d = 1) => fin(v) ? (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v * 100).toFixed(d) + '%' : '–';
const mag = (v, d = 1) => fin(v) ? Math.abs(v * 100).toFixed(d) + '%' : '–';
const scName = s => s.replace(/^S\d_/, '').replace(/_/g, ' ');
function el(tag, attrs = {}, html) { const e = document.createElement(tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (html !== undefined) e.innerHTML = html; return e; }
function S(tag, attrs = {}, parent) { const e = document.createElementNS(NS, tag); for (const k in attrs) { if (k === 'text') e.textContent = attrs[k]; else e.setAttribute(k, attrs[k]); } if (parent) parent.appendChild(e); return e; }
function lin(d0, d1, r0, r1) { const k = (r1 - r0) / ((d1 - d0) || 1); return v => r0 + (v - d0) * k; }
function ticks(lo, hi, n = 5) { const span = hi - lo || 1, s0 = span / n, mag = 10 ** Math.floor(Math.log10(s0)), e = s0 / mag;
  const st = (e >= 7.5 ? 10 : e >= 3.5 ? 5 : e >= 1.5 ? 2 : 1) * mag, out = []; for (let v = Math.ceil(lo / st) * st; v <= hi + st * 1e-6; v += st) out.push(+v.toFixed(10)); return out; }
const tip = $('#tip');
function showTip(ev, title, rows) {
  tip.innerHTML = `<div class="t">${title}</div>` + rows.map(([k, v]) => `<div class="row"><span>${k}</span><span>${v}</span></div>`).join('');
  tip.hidden = false; const w = tip.offsetWidth, h = tip.offsetHeight;
  let x = ev.clientX + 14, y = ev.clientY + 14; if (x + w > innerWidth - 8) x = ev.clientX - w - 14; if (y + h > innerHeight - 8) y = ev.clientY - h - 14;
  tip.style.left = Math.max(8, x) + 'px'; tip.style.top = Math.max(8, y) + 'px'; }
const hideTip = () => { tip.hidden = true; };
function stateClass(s) { s = (s || '').toLowerCase(); if (s.startsWith('supported') && !s.includes('small') && !s.includes('partly')) return 'good';
  if (s === 'met') return 'good'; if (s.includes('small') || s.includes('partly') || s.includes('guard')) return 'warn'; return 'crit'; }
function verdictClass(v) { v = v || ''; if (v.startsWith('meaningful reduction')) return 'good'; if (v.startsWith('detectable reduction')) return 'warn';
  if (v.startsWith('no detectable')) return ''; if (v.includes('increase')) return 'crit'; return ''; }
function legend(items, onToggle) { const L = el('div', {class: 'legend'});
  items.forEach(it => { const b = el('button', {'aria-pressed': it.on === false ? 'false' : 'true', type: 'button'}, `<span class="sw" style="background:${it.color}"></span>${it.label}`);
    if (onToggle) b.addEventListener('click', () => { const on = b.getAttribute('aria-pressed') !== 'true'; b.setAttribute('aria-pressed', on); onToggle(it.key, on); });
    else b.style.cursor = 'default'; L.appendChild(b); }); return L; }
function topRoundedBar(x, y0, y1, w, r = 3) { const top = Math.min(y0, y1), h = Math.abs(y1 - y0); r = Math.min(r, w / 2, h);
  return `M${x},${y0} L${x},${top + r} Q${x},${top} ${x + r},${top} L${x + w - r},${top} Q${x + w},${top} ${x + w},${top + r} L${x + w},${y0} Z`; }
function width(c) { return Math.max(300, c.clientWidth || 600); }

/* ---------------- charts ---------------- */
function groupedBars(host, {groups, series, get, yLabel, groupLabel, minW = 640, h = 300, extra}) {
  host.innerHTML = ''; const W = Math.max(minW, width(host)), m = {l: 54, r: 10, t: 10, b: 34}; const svg = S('svg', {viewBox: `0 0 ${W} ${h}`, width: W, height: h, role: 'img', 'aria-label': yLabel}, host);
  const vals = groups.flatMap(g => series.map(s => get(g, s)).filter(Boolean)); const ymax = Math.max(...vals.map(v => v.hi ?? v.mean)) * 1.08;
  const y = lin(0, ymax, h - m.b, m.t), gw = (W - m.l - m.r) / groups.length, bw = Math.min(22, gw * 0.8 / series.length);
  ticks(0, ymax).forEach(t => { S('line', {x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), class: 'gr'}, svg); S('text', {x: m.l - 8, y: y(t) + 4, 'text-anchor': 'end', text: t}, svg); });
  S('text', {x: 12, y: m.t + (h - m.b - m.t) / 2, transform: `rotate(-90 12 ${m.t + (h - m.b - m.t) / 2})`, 'text-anchor': 'middle', text: yLabel}, svg);
  groups.forEach((g, i) => { const gx = m.l + i * gw + (gw - bw * series.length) / 2;
    S('text', {x: m.l + i * gw + gw / 2, y: h - m.b + 18, 'text-anchor': 'middle', text: groupLabel(g)}, svg);
    series.forEach((s, j) => { const v = get(g, s); if (!v) return; const x = gx + j * bw;
      S('path', {d: topRoundedBar(x + 1, y(0), y(v.mean), bw - 2), style: `fill:${PCOL[s] || s}`}, svg);
      if (fin(v.lo)) S('line', {x1: x + bw / 2, x2: x + bw / 2, y1: y(v.lo), y2: y(v.hi), style: 'stroke:var(--ink);stroke-width:1.2'}, svg);
      const hit = S('rect', {x, y: m.t, width: bw, height: h - m.b - m.t, fill: 'transparent'}, svg);
      hit.addEventListener('mousemove', ev => showTip(ev, `${LABEL[s] || s} · ${groupLabel(g)}`, extra ? extra(g, s, v) : [['mean', fmt(v.mean, 2)], ['95% CI', `${fmt(v.lo, 2)} – ${fmt(v.hi, 2)}`]]));
      hit.addEventListener('mouseleave', hideTip); }); });
  S('line', {x1: m.l, x2: W - m.r, y1: y(0), y2: y(0), class: 'ax'}, svg); }

function lineChart(host, {series, yLabel, xLabel, h = 200, refs = [], yMin, yMax, xFmt = v => v, yFmt = v => fmt(v, 1), onHover}) {
  host.innerHTML = ''; const W = width(host), m = {l: 54, r: 12, t: 10, b: 30}; const svg = S('svg', {viewBox: `0 0 ${W} ${h}`, width: W, height: h, role: 'img', 'aria-label': yLabel}, host);
  const on = series.filter(s => s.on !== false); if (!on.length) return;
  const xs = on.flatMap(s => s.x), ys = on.flatMap(s => s.y).filter(fin).concat(refs.map(r => r.y));
  const x0 = Math.min(...xs), x1 = Math.max(...xs); let y0 = yMin ?? Math.min(...ys), y1 = yMax ?? Math.max(...ys); const pad = (y1 - y0) * 0.08 || 1; y0 -= yMin === undefined ? pad : 0; y1 += pad;
  const x = lin(x0, x1, m.l, W - m.r), y = lin(y0, y1, h - m.b, m.t);
  ticks(y0, y1, 4).forEach(t => { S('line', {x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), class: 'gr'}, svg); S('text', {x: m.l - 8, y: y(t) + 4, 'text-anchor': 'end', text: t}, svg); });
  ticks(x0, x1, 6).forEach(t => S('text', {x: x(t), y: h - m.b + 16, 'text-anchor': 'middle', text: xFmt(t)}, svg));
  S('line', {x1: m.l, x2: W - m.r, y1: h - m.b, y2: h - m.b, class: 'ax'}, svg);
  S('text', {x: 12, y: m.t + (h - m.b - m.t) / 2, transform: `rotate(-90 12 ${m.t + (h - m.b - m.t) / 2})`, 'text-anchor': 'middle', text: yLabel}, svg);
  if (xLabel) S('text', {x: W - m.r, y: h - 2, 'text-anchor': 'end', text: xLabel}, svg);
  refs.forEach(r => { S('line', {x1: m.l, x2: W - m.r, y1: y(r.y), y2: y(r.y), style: `stroke:${r.color};stroke-dasharray:4 3;stroke-width:1`}, svg);
    S('text', {x: W - m.r - 4, y: r.below ? y(r.y) + 12 : y(r.y) - 4, 'text-anchor': 'end', text: r.label, style: `fill:${r.color}`}, svg); });
  on.forEach(s => { if (s.band) { const pts = s.x.map((xv, i) => `${x(xv)},${y(s.band.hi[i])}`).concat(s.x.map((xv, i) => `${x(xv)},${y(s.band.lo[i])}`).reverse());
      S('polygon', {points: pts.join(' '), style: `fill:${s.color};opacity:.15`}, svg); }
    S('polyline', {points: s.x.map((xv, i) => fin(s.y[i]) ? `${x(xv)},${y(s.y[i])}` : null).filter(Boolean).join(' '), fill: 'none',
      style: `stroke:${s.color};stroke-width:${s.w || 2};${s.dash ? 'stroke-dasharray:' + s.dash : ''}`, 'stroke-linejoin': 'round'}, svg);
    if (s.markers) s.x.forEach((xv, i) => fin(s.y[i]) && S('circle', {cx: x(xv), cy: y(s.y[i]), r: 4, style: `fill:${s.color};stroke:var(--surface);stroke-width:2`}, svg)); });
  const cross = S('line', {y1: m.t, y2: h - m.b, style: 'stroke:var(--muted);stroke-width:1', visibility: 'hidden'}, svg);
  const hit = S('rect', {x: m.l, y: m.t, width: W - m.l - m.r, height: h - m.b - m.t, fill: 'transparent'}, svg);
  hit.addEventListener('mousemove', ev => { const r = svg.getBoundingClientRect(); const px = (ev.clientX - r.left) * W / r.width; const xv = x0 + (px - m.l) / (W - m.l - m.r) * (x1 - x0);
    const ref = on[0]; let i = 0, best = Infinity; ref.x.forEach((v, k) => { const d = Math.abs(v - xv); if (d < best) { best = d; i = k; } });
    cross.setAttribute('x1', x(ref.x[i])); cross.setAttribute('x2', x(ref.x[i])); cross.setAttribute('visibility', 'visible');
    showTip(ev, `${xLabel ? xLabel + ' ' : ''}${xFmt(ref.x[i])}`, on.map(s => [s.label, yFmt(s.y[Math.min(i, s.y.length - 1)])])); if (onHover) onHover(i); });
  hit.addEventListener('mouseleave', () => { cross.setAttribute('visibility', 'hidden'); hideTip(); }); }

/* ---------------- tabs ---------------- */
const TABS = [['overview', 'Overview'], ['energy', 'Energy'], ['thermal', 'Thermal'], ['sensitivity', 'Sensitivity'], ['routing', 'Model routing'],
  ['robustness', 'Twin mismatch'], ['phase3', 'Phase 3'], ['hardware', 'Hardware (M001)'], ['explorer', 'Cold-plate explorer'], ['assumptions', 'Assumptions'], ['log', 'Experiments & log']];
const nav = $('#tabs'), main = $('#main'), renderers = {}, sections = {};
TABS.forEach(([id, name]) => { const b = el('button', {role: 'tab', id: 'tab-' + id, 'aria-controls': id, 'aria-selected': 'false', type: 'button'}, name);
  b.addEventListener('click', () => show(id)); nav.appendChild(b); const sec = el('section', {class: 'tab', id, role: 'tabpanel', 'aria-labelledby': 'tab-' + id}); sec.hidden = true; main.appendChild(sec); sections[id] = sec; });
let current = null;
function show(id) { if (!sections[id]) id = 'overview'; current = id; TABS.forEach(([t]) => { sections[t].hidden = t !== id; $('#tab-' + t).setAttribute('aria-selected', t === id); });
  try { history.replaceState(null, '', '#' + id); } catch (e) {} renderers[id] && renderers[id](sections[id]); }
let rz; addEventListener('resize', () => { clearTimeout(rz); rz = setTimeout(() => current && renderers[current](sections[current]), 150); });

$('#stamp').innerHTML = `<span>generated <b>${D.generated_utc.replace('T', ' ').replace('+00:00', ' UTC')}</b></span><span>code <b>${D.code_sha256.slice(0, 12)}</b></span>
  <span>hash chain <b style="color:${D.chain_ok ? 'var(--good-ink)' : 'var(--crit)'}">${D.chain_ok ? 'verified' : 'FAILED'}</b></span><span>${D.chain_msg}</span>`;

const E1 = D.E001;
function cmp(a, b, sc) { return E1.comparisons.find(c => c.a === a && c.b === b && c.scenario === sc); }
function range(arr) { const v = arr.filter(fin); return [Math.min(...v), Math.max(...v)]; }

/* Overview */
renderers.overview = sec => { sec.innerHTML = '';
  sec.appendChild(el('p', {class: 'lede'}, 'Can coordinating clock frequency, coolant temperature, flow and heat rejection lower the facility energy needed per successful AI task? Phase 1 answers this inside a validated simulator of one 8-accelerator liquid-cooled node, under explicit assumptions. Hypotheses were registered before the runs.'));
  const vg = el('div', {class: 'verdicts'}); D.verdicts.forEach(v => vg.appendChild(el('div', {class: 'vcard'}, `<span class="k">${v.key}</span><span class="pill ${stateClass(v.state)}">${v.state}</span><span>${v.text}</span>`)));
  sec.appendChild(el('h2', {}, 'Pre-registered hypotheses')); sec.appendChild(vg);
  if (E1) { const P = E1.policies, SC = E1.scenarios;
    const r = p => range(SC.map(s => cmp(p, 'fixed', s)?.mean)); const [c0, c1] = r('compute_only'), [k0, k1] = r('cooling_only'), [j0, j1] = r('joint');
    const ji = SC.map(s => cmp('joint', 'independent', s)); const [a0, a1] = range(ji.map(c => c.mean));
    const t = (s, p, k) => E1.table[s][p][k].mean;
    const hotInd = SC.filter(s => t(s, 'independent', 'chip_s_over_target') > 0), hotJ = SC.filter(s => t(s, 'joint', 'chip_s_over_target') > 0);
    const cooler = SC.filter(s => t(s, 'joint', 'peak_T_j_C') < t(s, 'independent', 'peak_T_j_C')).length;
    const itLower = SC.filter(s => t(s, 'joint', 'E_it_kWh') < t(s, 'independent', 'E_it_kWh')).length;
    const coolHigher = SC.filter(s => t(s, 'joint', 'E_cooling_kWh') > t(s, 'independent', 'E_cooling_kWh')).length;
    const ul = el('ul', {class: 'findings'});
    [`Energy-aware clock control (compute-only) cut energy per successful task by ${mag(c1, 0)} to ${mag(c0, 0)} versus the fixed baseline. It is the largest single lever in this model, and E002 shows its size depends mostly on the assumed voltage–frequency curve and memory-boundness.`,
     `Optimising only the cooling plant (warmer supply water, more free cooling) saved ${mag(k1, 1)} to ${mag(k0, 1)}. The saving is largest in hot ambient, where the fixed 18 °C supply forces the chiller to run.`,
     `Joint optimisation beat running the two optimisers independently by ${mag(a1, 2)} to ${mag(a0, 2)}. That is statistically clear in all scenarios but beyond the 1% practical threshold in only ${E1.H1.scenarios_meaningful.length} of 6, and comparable to the ~0.5% decision-path sensitivity found in E004.`,
     `Mechanism: in ${cooler}/6 scenarios the joint controller ran chips cooler than independent control, with lower IT energy in ${itLower}/6 and higher cooling energy in ${coolHigher}/6. It buys down leakage with pump flow, a trade the independent controllers cannot see.`,
     hotInd.length ? `Independent control exceeded the 80 °C target in ${hotInd.map(scName).join(', ')}, and hardware protection throttled chips. Its cooling side treats chip power as fixed, so it does not anticipate the leakage rise its own warmer setpoint causes. Joint control exceeded the target in ${hotJ.length ? hotJ.map(scName).join(', ') : 'no scenario'}.` : 'No policy exceeded the thermal target in E001.',
     `Energy savings vs fixed came with slightly more late tasks in some scenarios (see Energy tab). Under the pre-registered quality guard, E001 H2 therefore does not pass as written.`].forEach(t => ul.appendChild(el('li', {}, t)));
    sec.appendChild(el('h2', {}, 'What the simulation shows')); sec.appendChild(ul);
    const p = el('div', {class: 'panel'}); p.appendChild(el('h3', {}, 'Energy per successful task, all scenarios (kJ, mean and 95% CI over 10 paired seeds)'));
    p.appendChild(legend(P.map(k => ({label: LABEL[k], color: PCOL[k]})))); const host = el('div', {class: 'scroll'}); p.appendChild(host); sec.appendChild(p);
    groupedBars(host, {groups: SC, series: P, get: (s, k) => E1.table[s][k].E_per_success_kJ, yLabel: 'kJ per successful task', groupLabel: scName,
      extra: (s, k, v) => { const c = cmp(k, 'fixed', s); return [['mean', fmt(v.mean, 2) + ' kJ'], ['95% CI', `${fmt(v.lo, 2)} – ${fmt(v.hi, 2)}`]].concat(c ? [['vs fixed', pct(c.mean, 1)]] : []); }}); }
  const oq = el('ul', {class: 'findings'});
  ['How temperature-sensitive is real leakage? The first warm-up on a real GPU could not separate leakage from its temperature coefficient. The slope it did measure suggests the registry overstates temperature sensitivity 2.5–4× (Hardware tab). If so, the benefit of colder coolant is overstated. A better warm-up is the next measurement.',
   'The simulator’s straight-line voltage–frequency model gets the shape of the measured power curve wrong: small clock cuts from the top save more than modelled, deep cuts less. DVFS magnitudes need a measured voltage–frequency form before they can be trusted.',
   'Under a slow coolant loop the joint controller loses thermal margin (E006). Planning over a short horizon with the loop model is the next controller change.',
   'Is there any workload where a custom accelerator would beat software and existing parts? Current evidence does not justify one; see docs/08_hardware_feasibility.md.'].forEach(t => oq.appendChild(el('li', {}, t)));
  sec.appendChild(el('h2', {}, 'Open questions')); sec.appendChild(oq); };

/* Energy */
let eScen = null;
renderers.energy = sec => { if (!E1) { sec.innerHTML = '<p>No E001 results.</p>'; return; } sec.innerHTML = ''; eScen = eScen || E1.scenarios[0];
  const ctr = el('div', {class: 'controls', role: 'group', 'aria-label': 'Scenario'}); E1.scenarios.forEach(s => { const b = el('button', {class: 'chip', 'aria-pressed': s === eScen, type: 'button'}, scName(s));
    b.addEventListener('click', () => { eScen = s; renderers.energy(sec); }); ctr.appendChild(b); }); sec.appendChild(ctr);
  const info = E1.scenario_info[eScen]; sec.appendChild(el('p', {class: 'lede'}, `${info.description}. Ambient ${info.t_amb} °C, mean offered load ${Math.round(info.load_mean * 100)}% ± ${Math.round(info.load_amp * 100)}%.`));
  const P = E1.policies, T = E1.table[eScen]; const g = el('div', {class: 'grid2'});
  const p1 = el('div', {class: 'panel'}); p1.appendChild(el('h3', {}, 'Grid energy by component (kWh per run, mean of 10 seeds)'));
  const parts = [['E_it_kWh', 'Accelerators (IT)', 'var(--s1)'], ['E_conv_loss_kWh', 'Conversion loss', 'var(--s2)'], ['E_pump_kWh', 'Pump', 'var(--s3)'], ['E_fan_kWh', 'Heat-rejection fans', 'var(--s4)'], ['E_chiller_kWh', 'Chiller', 'var(--s5)']];
  p1.appendChild(legend(parts.map(([k, l, c]) => ({label: l, color: c})))); const h1 = el('div'); p1.appendChild(h1); g.appendChild(p1);
  { const W = width(h1), rowH = 34, m = {l: 112, r: 84, t: 4, b: 22}, H = m.t + m.b + rowH * P.length; const svg = S('svg', {viewBox: `0 0 ${W} ${H}`, width: W, height: H}, h1);
    const tot = P.map(p => parts.reduce((a, [k]) => a + Math.max(0, T[p][k].mean), 0)); const x = lin(0, Math.max(...tot) * 1.02, m.l, W - m.r);
    ticks(0, Math.max(...tot), 4).forEach(t => { S('line', {x1: x(t), x2: x(t), y1: m.t, y2: H - m.b, class: 'gr'}, svg); S('text', {x: x(t), y: H - 6, 'text-anchor': 'middle', text: t}, svg); });
    P.forEach((p, i) => { let acc = 0; const yy = m.t + i * rowH + 6; S('text', {x: m.l - 8, y: yy + 15, 'text-anchor': 'end', text: LABEL[p], style: 'fill:var(--ink)'}, svg);
      parts.forEach(([k, l, c]) => { const v = Math.max(0, T[p][k].mean); if (v <= 0) return; const r = S('rect', {x: x(acc), y: yy, width: Math.max(0, x(acc + v) - x(acc) - 2), height: 20, rx: 2, style: `fill:${c}`}, svg);
        r.addEventListener('mousemove', ev => showTip(ev, `${LABEL[p]} · ${l}`, [['energy', fmt(v, 3) + ' kWh'], ['share of grid', fmt(100 * v / T[p].E_grid_kWh.mean, 1) + '%']])); r.addEventListener('mouseleave', hideTip); acc += v; });
      S('text', {x: x(acc) + 6, y: yy + 15, text: fmt(T[p].E_grid_kWh.mean, 2) + ' kWh', style: 'fill:var(--ink2)'}, svg); }); }
  const p2 = el('div', {class: 'panel'}); p2.appendChild(el('h3', {}, 'Energy per successful task (kJ, mean and 95% CI)')); const h2 = el('div'); p2.appendChild(h2); g.appendChild(p2); sec.appendChild(g);
  { const W = width(h2), rowH = 34, m = {l: 112, r: 76, t: 4, b: 22}, H = m.t + m.b + rowH * P.length; const svg = S('svg', {viewBox: `0 0 ${W} ${H}`, width: W, height: H}, h2);
    const mx = Math.max(...P.map(p => T[p].E_per_success_kJ.hi)); const x = lin(0, mx * 1.02, m.l, W - m.r);
    ticks(0, mx, 4).forEach(t => { S('line', {x1: x(t), x2: x(t), y1: m.t, y2: H - m.b, class: 'gr'}, svg); S('text', {x: x(t), y: H - 6, 'text-anchor': 'middle', text: t}, svg); });
    P.forEach((p, i) => { const v = T[p].E_per_success_kJ, yy = m.t + i * rowH + 6; S('text', {x: m.l - 8, y: yy + 15, 'text-anchor': 'end', text: LABEL[p], style: 'fill:var(--ink)'}, svg);
      S('rect', {x: m.l, y: yy, width: x(v.mean) - m.l, height: 20, rx: 3, style: `fill:${PCOL[p]}`}, svg);
      S('line', {x1: x(v.lo), x2: x(v.hi), y1: yy + 10, y2: yy + 10, style: 'stroke:var(--ink);stroke-width:1.2'}, svg);
      const c = cmp(p, 'fixed', eScen); S('text', {x: x(v.hi) + 6, y: yy + 15, text: fmt(v.mean, 2) + (c ? `  (${pct(c.mean, 1)})` : ''), style: 'fill:var(--ink2)'}, svg); }); }
  const p3 = el('div', {class: 'panel'}); p3.appendChild(el('h3', {}, 'Paired comparisons in this scenario'));
  const rows = E1.comparisons.filter(c => c.scenario === eScen);
  p3.appendChild(el('div', {class: 'scroll'}, `<table><thead><tr><th>Comparison</th><th class="n">Change</th><th class="n">95% CI</th><th>Verdict (±${(D.threshold * 100).toFixed(0)}% threshold)</th><th class="n">Δ late tasks</th><th class="n">Δ success</th><th class="n">Δ throttled chip·s</th></tr></thead><tbody>${
    rows.map(c => `<tr><td>${LABEL[c.a]} vs ${LABEL[c.b]}</td><td class="n">${pct(c.mean, 2)}</td><td class="n">${pct(c.lo, 2)} … ${pct(c.hi, 2)}</td><td><span class="pill ${verdictClass(c.verdict)}">${c.verdict}</span></td><td class="n">${c.d_slo_violations > 0 ? '+' : ''}${fmt(c.d_slo_violations, 1)}</td><td class="n">${fmt(c.d_success_rate * 100, 3)} pp</td><td class="n">${fmt(c.d_throttled, 0)}</td></tr>`).join('')}</tbody></table>`));
  p3.appendChild(el('p', {class: 'note'}, 'Change = mean of per-seed (A − B)/B on energy per successful task; negative means A uses less. Late tasks = finished after their latency SLO.'));
  sec.appendChild(p3); };

/* Thermal */
let tScen = null; const tOn = {fixed: true, compute_only: false, cooling_only: false, independent: true, joint: true};
renderers.thermal = sec => { if (!E1) return; sec.innerHTML = ''; tScen = tScen || (E1.scenarios.includes('S3_hot') ? 'S3_hot' : E1.scenarios[0]);
  const ctr = el('div', {class: 'controls'}); E1.scenarios.forEach(s => { const b = el('button', {class: 'chip', 'aria-pressed': s === tScen, type: 'button'}, scName(s)); b.addEventListener('click', () => { tScen = s; renderers.thermal(sec); }); ctr.appendChild(b); }); sec.appendChild(ctr);
  const ts = E1.timeseries[tScen] || {}; const pols = E1.policies.filter(p => ts[p]);
  const panel = el('div', {class: 'panel'}); panel.appendChild(el('h3', {}, `Seed 0 over time · ${scName(tScen)} (1-minute averages; hottest junction is the 1-minute maximum)`));
  panel.appendChild(legend(pols.map(p => ({key: p, label: LABEL[p], color: PCOL[p], on: tOn[p]})), (k, on) => { tOn[k] = on; draw(); }));
  const hosts = [el('div'), el('div'), el('div'), el('div')]; hosts.forEach(h => panel.appendChild(h)); sec.appendChild(panel);
  function draw() { const ser = k => pols.map(p => ({label: LABEL[p], color: PCOL[p], on: tOn[p], x: ts[p].t.map(v => v / 3600), y: ts[p][k]}));
    lineChart(hosts[0], {series: ser('P_grid').map(s => ({...s, y: s.y.map(v => v / 1000)})), yLabel: 'Grid power (kW)', xFmt: v => fmt(v, 1) + ' h', yFmt: v => fmt(v, 2) + ' kW', h: 170});
    lineChart(hosts[1], {series: ser('T_sup'), yLabel: 'Supply (°C)', xFmt: v => fmt(v, 1) + ' h', yFmt: v => fmt(v, 0) + ' °C', h: 150});
    lineChart(hosts[2], {series: ser('flow'), yLabel: 'Flow (× design)', xFmt: v => fmt(v, 1) + ' h', yFmt: v => fmt(v, 2) + '×', h: 130});
    lineChart(hosts[3], {series: ser('T_max'), yLabel: 'Hottest junction (°C)', xLabel: 'time', xFmt: v => fmt(v, 1) + ' h', yFmt: v => fmt(v, 1) + ' °C', h: 190,
      refs: [{y: 80, label: '80 °C controller target', color: 'var(--muted)', below: true}, {y: 85, label: '85 °C hardware throttle', color: 'var(--crit)'}]}); }
  draw();
  const g = el('div', {class: 'panel'}); g.appendChild(el('h3', {}, 'Thermal and quality guards (means over 10 seeds)'));
  g.appendChild(el('div', {class: 'scroll'}, `<table><thead><tr><th>Policy</th><th class="n">Peak T<sub>j</sub> °C</th><th class="n">chip·s &gt; 80 °C</th><th class="n">chip·s throttled</th><th class="n">Late tasks</th><th class="n">p95 latency s</th><th class="n">Success rate</th><th class="n">Heat ≥45 °C kWh</th><th class="n">Exergy above ambient kWh</th></tr></thead><tbody>${
    E1.policies.map(p => { const t = E1.table[tScen][p]; const bad = t.chip_s_throttled.mean > 0 ? 'crit' : t.chip_s_over_target.mean > 0 ? 'warn' : 'good';
      return `<tr><td><span class="sw" style="background:${PCOL[p]}"></span>${LABEL[p]}</td><td class="n">${fmt(t.peak_T_j_C.mean, 1)}</td><td class="n"><span class="pill ${bad}">${fmt(t.chip_s_over_target.mean, 0)}</span></td><td class="n">${fmt(t.chip_s_throttled.mean, 0)}</td><td class="n">${fmt(t.slo_violations.mean, 1)}</td><td class="n">${fmt(t.latency_p95_s.mean, 1)}</td><td class="n">${fmt(t.success_rate.mean, 4)}</td><td class="n">${fmt(t.Q_reusable_kWh.mean, 2)}</td><td class="n">${fmt(t.Ex_rejected_kWh.mean, 3)}</td></tr>`; }).join('')}</tbody></table>`));
  g.appendChild(el('p', {class: 'note'}, 'Heat ≥45 °C is heat rejected while return water was at least 45 °C, a plausible threshold for reuse. Exergy is the work potential of rejected coolant heat above ambient temperature. Neither is subtracted from consumption, because no heat user is modelled.'));
  sec.appendChild(g); };

/* Sensitivity */
let sKey = 'joint_vs_independent';
renderers.sensitivity = sec => { const E2 = D.E002; sec.innerHTML = ''; if (!E2) { sec.appendChild(el('p', {}, 'E002 has not been run yet.')); return; }
  sec.appendChild(el('p', {class: 'lede'}, 'Each row moves one uncertain parameter to the low or high end of its registry range, holding the rest at defaults (S1 scenario, 2 h, 3 seeds per cell). Long rows mark the assumptions the conclusion hinges on, and those are what Phase 4 should measure first.'));
  const ctr = el('div', {class: 'controls'}); [['joint_vs_independent', 'Joint vs independent'], ['joint_vs_fixed', 'Joint vs fixed'], ['independent_vs_fixed', 'Independent vs fixed']].forEach(([k, l]) => {
    const b = el('button', {class: 'chip', 'aria-pressed': k === sKey, type: 'button'}, l); b.addEventListener('click', () => { sKey = k; renderers.sensitivity(sec); }); ctr.appendChild(b); }); sec.appendChild(ctr);
  const T = E2.tornado[sKey], items = T.items.slice(0, 16); const p = el('div', {class: 'panel'});
  p.appendChild(el('h3', {}, `Change in energy per successful task · default ${pct(T.base, 2)}`));
  p.appendChild(legend([{label: 'parameter at low end of range', color: 'var(--s1)'}, {label: 'parameter at high end of range', color: 'var(--s2)'}])); const host = el('div', {class: 'scroll'}); p.appendChild(host); sec.appendChild(p);
  const W = Math.max(560, width(host)), rowH = 26, m = {l: 170, r: 20, t: 6, b: 26}, H = m.t + m.b + rowH * items.length; const svg = S('svg', {viewBox: `0 0 ${W} ${H}`, width: W, height: H}, host);
  const vals = items.flatMap(i => [i.at_low, i.at_high]).concat([0, T.base]); let [lo, hi] = [Math.min(...vals), Math.max(...vals)]; const pd = (hi - lo) * 0.06; lo -= pd; hi += pd;
  const x = lin(lo, hi, m.l, W - m.r); ticks(lo * 100, hi * 100, 6).forEach(t => { S('line', {x1: x(t / 100), x2: x(t / 100), y1: m.t, y2: H - m.b, class: 'gr'}, svg); S('text', {x: x(t / 100), y: H - 8, 'text-anchor': 'middle', text: t + '%'}, svg); });
  S('line', {x1: x(0), x2: x(0), y1: m.t, y2: H - m.b, style: 'stroke:var(--muted);stroke-dasharray:4 3'}, svg); S('line', {x1: x(T.base), x2: x(T.base), y1: m.t, y2: H - m.b, style: 'stroke:var(--ink2)'}, svg);
  items.forEach((it, i) => { const yy = m.t + i * rowH + rowH / 2; S('text', {x: m.l - 8, y: yy + 4, 'text-anchor': 'end', text: `${it.param} [${it.evidence}]`, style: 'fill:var(--ink)'}, svg);
    S('line', {x1: x(it.at_low), x2: x(it.at_high), y1: yy, y2: yy, style: 'stroke:var(--axis);stroke-width:3'}, svg);
    [['at_low', 'var(--s1)', it.low_value], ['at_high', 'var(--s2)', it.high_value]].forEach(([k, c, pv]) => { const dot = S('circle', {cx: x(it[k]), cy: yy, r: 5.5, style: `fill:${c};stroke:var(--surface);stroke-width:2`}, svg);
      const hit = S('circle', {cx: x(it[k]), cy: yy, r: 11, fill: 'transparent'}, svg);
      hit.addEventListener('mousemove', ev => showTip(ev, it.param, [['set to', `${pv} ${it.unit}`], ['default', `${it.default_value} ${it.unit}`], ['result', pct(it[k], 2)], ['class', it.evidence]])); hit.addEventListener('mouseleave', hideTip); }); });
  const flips = E2.joint_worse_mean; sec.appendChild(el('p', {class: 'note'}, flips.length ? `Variants where joint used more energy than independent (mean over 3 seeds): ${flips.join(', ')}.` : 'Joint used no more energy than independent in any variant.')); };

/* Routing */
renderers.routing = sec => { const E3 = D.E003; sec.innerHTML = ''; if (!E3) { sec.appendChild(el('p', {}, 'E003 has not been run yet.')); return; }
  sec.appendChild(el('p', {class: 'lede'}, `A small model answers first and a verifier checks it. Rejected answers go to the large model. With a perfect verifier, theory says the cascade saves work only when small-model plus verifier cost is below the small model’s expected success rate (${fmt(E3.break_even_rs_rv, 3)} here). The quality model is a hypothetical placeholder, so the break-even condition and the gap between work and energy are what transfer, not the percentages.`));
  const clean = E3.rows.filter(r => r.false_accept === 0); const xs = [...new Set(clean.map(r => r.rs_plus_rv))].sort((a, b) => a - b);
  const p = el('div', {class: 'panel'}); p.appendChild(el('h3', {}, 'Change versus large-model-only, by cascade cost'));
  const ser = [{label: 'Analytic change in work', color: 'var(--muted)', dash: '5 4', markers: true, x: xs, y: xs.map(x => 100 * (clean.find(r => r.rs_plus_rv === x).analytic_work_ratio - 1))}];
  ['fixed', 'joint'].forEach(pol => { const rr = clean.filter(r => r.policy === pol).sort((a, b) => a.rs_plus_rv - b.rs_plus_rv);
    ser.push({label: `Energy per successful task · ${LABEL[pol]}`, color: PCOL[pol], markers: true, x: rr.map(r => r.rs_plus_rv), y: rr.map(r => 100 * r.energy_change), band: {lo: rr.map(r => 100 * r.energy_lo), hi: rr.map(r => 100 * r.energy_hi)}}); });
  p.appendChild(legend(ser.map(s => ({label: s.label, color: s.color})))); const host = el('div'); p.appendChild(host); sec.appendChild(p);
  lineChart(host, {series: ser, yLabel: 'Change (%)', xLabel: 'rs + rv', xFmt: v => fmt(v, 2), yFmt: v => (v > 0 ? '+' : '') + fmt(v, 1) + '%', h: 260, refs: [{y: 0, label: 'no change', color: 'var(--muted)', below: true}]});
  const be = el('p', {class: 'note'}, `The two solid lines diverge from the dashed one in opposite directions. Under the fixed baseline, energy falls less than work because static, idle, conversion and cooling power do not scale with work. Under joint control, energy falls more than work at intermediate cascade costs and rises more than work above break-even, because lighter load lets the controller lower clocks and heavier load forces them up. Every cascade variant also shows about +1.9 pp task success. That is an artifact of the placeholder: the verifier is perfect and checks only the small model, so it filters failures the large-only baseline keeps. It is not evidence that cascades improve quality.`); p.appendChild(be);
  const t = el('div', {class: 'panel'}); t.appendChild(el('h3', {}, 'All routing variants'));
  t.appendChild(el('div', {class: 'scroll'}, `<table><thead><tr><th>Variant</th><th>Policy</th><th class="n">Analytic Δ work</th><th class="n">Simulated Δ work</th><th class="n">Δ energy / success</th><th>Verdict</th><th class="n">Δ success</th><th class="n">Δ p95 latency</th></tr></thead><tbody>${
    E3.rows.map(r => `<tr><td class="mono">${r.variant}</td><td>${LABEL[r.policy]}</td><td class="n">${pct(r.analytic_work_ratio - 1)}</td><td class="n">${pct(r.sim_work_change)}</td><td class="n">${pct(r.energy_change)} <span class="note">[${pct(r.energy_lo)}, ${pct(r.energy_hi)}]</span></td><td><span class="pill ${verdictClass(r.verdict)}">${r.verdict}</span></td><td class="n">${fmt(r.d_success_rate * 100, 2)} pp</td><td class="n">${pct(r.p95_latency_change)}</td></tr>`).join('')}</tbody></table>`));
  sec.appendChild(t); };

/* Robustness */
renderers.robustness = sec => { const E5 = D.E005; sec.innerHTML = ''; if (!E5) { sec.appendChild(el('p', {}, 'E005 has not been run yet.')); return; }
  sec.appendChild(el('p', {class: 'lede'}, 'The joint controller is only as good as its digital twin. Here the true plant differs from what the controller believes: more leakage than modelled, fouled cold plates, or a weaker chiller. Each wrong-twin case is paired with the same true plant and a correct twin.'));
  const p = el('div', {class: 'panel'}); p.appendChild(el('div', {class: 'scroll'}, `<table><thead><tr><th>Scenario</th><th>True plant | twin</th><th class="n">Joint vs independent</th><th>Verdict</th><th class="n">Joint chip·s &gt;80 °C</th><th class="n">Indep. chip·s &gt;80 °C</th><th class="n">Joint throttled</th><th class="n">Indep. throttled</th><th class="n">Joint peak °C</th><th class="n">Indep. peak °C</th></tr></thead><tbody>${
    E5.rows.map(r => `<tr><td>${scName(r.scenario)}</td><td class="mono">${r.variant}</td><td class="n">${pct(r.joint_vs_independent, 2)} <span class="note">[${pct(r.lo, 2)}, ${pct(r.hi, 2)}]</span></td><td><span class="pill ${verdictClass(r.verdict)}">${r.verdict}</span></td><td class="n">${fmt(r.joint_chip_s_over_target, 0)}</td><td class="n">${fmt(r.independent_chip_s_over_target, 0)}</td><td class="n">${fmt(r.joint_chip_s_throttled, 0)}</td><td class="n">${fmt(r.independent_chip_s_throttled, 0)}</td><td class="n">${fmt(r.joint_peak_T_j_C, 1)}</td><td class="n">${fmt(r.independent_peak_T_j_C, 1)}</td></tr>`).join('')}</tbody></table>`));
  sec.appendChild(p); };

/* Phase 3 */
function ciDots(host, rows, groups, series, colors, labels, yLabel) {
  host.innerHTML = ''; const W = Math.max(520, width(host)), H = 240, m = {l: 58, r: 12, t: 12, b: 30};
  const svg = S('svg', {viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', 'aria-label': yLabel}, host);
  const vals = rows.flatMap(r => [r.lo, r.hi]).filter(fin).concat([0, -D.threshold]); const lo = Math.min(...vals) * 1.1, hi = Math.max(0.001, Math.max(...vals) * 1.1);
  const y = lin(lo, hi, H - m.b, m.t), gw = (W - m.l - m.r) / groups.length;
  ticks(lo * 100, hi * 100, 5).forEach(t => { S('line', {x1: m.l, x2: W - m.r, y1: y(t / 100), y2: y(t / 100), class: 'gr'}, svg); S('text', {x: m.l - 8, y: y(t / 100) + 4, 'text-anchor': 'end', text: t + '%'}, svg); });
  S('line', {x1: m.l, x2: W - m.r, y1: y(0), y2: y(0), class: 'ax'}, svg);
  S('line', {x1: m.l, x2: W - m.r, y1: y(-D.threshold), y2: y(-D.threshold), style: 'stroke:var(--muted);stroke-dasharray:4 3'}, svg);
  S('text', {x: m.l + 4, y: y(-D.threshold) - 4, text: `practical threshold (${(D.threshold * 100).toFixed(0)}%)`, style: 'fill:var(--muted)'}, svg);
  S('text', {x: 12, y: m.t + (H - m.b - m.t) / 2, transform: `rotate(-90 12 ${m.t + (H - m.b - m.t) / 2})`, 'text-anchor': 'middle', text: yLabel}, svg);
  groups.forEach((g, i) => { S('text', {x: m.l + i * gw + gw / 2, y: H - 8, 'text-anchor': 'middle', text: scName(g)}, svg);
    series.forEach((sr, j) => { const r = rows.find(x => x.g === g && x.s === sr); if (!r) return; const x = m.l + i * gw + gw / 2 + (j - (series.length - 1) / 2) * 22;
      S('line', {x1: x, x2: x, y1: y(r.lo), y2: y(r.hi), style: `stroke:${colors[j]};stroke-width:2.5`}, svg);
      const c = S('circle', {cx: x, cy: y(r.mean), r: 5, style: `fill:${colors[j]};stroke:var(--surface);stroke-width:2`}, svg);
      const hit = S('circle', {cx: x, cy: y(r.mean), r: 12, fill: 'transparent'}, svg);
      hit.addEventListener('mousemove', ev => showTip(ev, `${labels[j]} · ${scName(g)}`, [['mean', pct(r.mean, 2)], ['95% CI', `${pct(r.lo, 2)} … ${pct(r.hi, 2)}`]])); hit.addEventListener('mouseleave', hideTip); }); }); }
renderers.phase3 = sec => { sec.innerHTML = ''; const E6 = D.E006, E7 = D.E007, E8 = D.E008;
  sec.appendChild(el('p', {class: 'lede'}, 'Phase 3 upgraded the simulator: a coolant loop with thermal mass and setpoint ramp limits, move suppression for the joint controller, and a joint controller that corrects its plan with measured temperatures. All three experiments were pre-registered; E006 was re-run after a confound was found (see disclosure).'));
  if (E6) { const p = el('div', {class: 'panel'}); p.appendChild(el('h3', {}, `E006 · Joint vs independent under three plant models (v${E6.version})`));
    const plants = ['quasi_steady', 'dyn_40kg_1Kmin', 'dyn_150kg_0.25Kmin'], pl = ['Quasi-steady', '40 kg loop, 1 K/min', '150 kg loop, 0.25 K/min'], cols = ['var(--s1)', 'var(--s2)', 'var(--s3)'];
    p.appendChild(legend(pl.map((l, i) => ({label: l, color: cols[i]})))); const h = el('div', {class: 'scroll'}); p.appendChild(h);
    if (E6.disclosure) p.appendChild(el('p', {class: 'note'}, 'Disclosure: ' + E6.disclosure.replace(/</g, '&lt;')));
    sec.appendChild(p);
    ciDots(h, E6.joint_vs_independent.map(r => ({g: r.scenario, s: r.plant, mean: r.mean, lo: r.lo, hi: r.hi})), [...new Set(E6.joint_vs_independent.map(r => r.scenario))], plants, cols, pl, 'Joint vs independent');
    const t = el('div', {class: 'panel'}); t.appendChild(el('h3', {}, 'Thermal guards by plant model (means over 10 seeds)'));
    t.appendChild(el('div', {class: 'scroll'}, `<table><thead><tr><th>Scenario</th><th>Plant</th><th>Policy</th><th class="n">chip·s &gt; 80 °C</th><th class="n">throttled</th><th class="n">Peak °C</th><th class="n">Loop storage</th></tr></thead><tbody>${
      E6.thermal.filter(r => r.policy !== 'fixed').map(r => `<tr><td>${scName(r.scenario)}</td><td class="mono">${r.plant}</td><td>${LABEL[r.policy] || r.policy}</td><td class="n"><span class="pill ${r.throttled > 0 ? 'crit' : r.over > 0 ? 'warn' : 'good'}">${fmt(r.over, 0)}</span></td><td class="n">${fmt(r.throttled, 0)}</td><td class="n">${fmt(r.peak, 1)}</td><td class="n">${fmt(r.storage_pct, 2)}%</td></tr>`).join('')}</tbody></table>`));
    t.appendChild(el('p', {class: 'note'}, 'Loop storage is the change in heat held by the coolant loop over the run, as a share of grid energy. Runs above 0.5% are flagged; a large value means the start and end states differ.'));
    sec.appendChild(t); }
  if (E8) { const p = el('div', {class: 'panel'}); p.appendChild(el('h3', {}, 'E008 · Overheating under twin mismatch, hot ambient (chip·s above 80 °C)'));
    const pols = ['independent', 'joint', 'joint_robust']; p.appendChild(legend(pols.map(k => ({label: LABEL[k], color: k === 'joint_robust' ? 'var(--s3)' : PCOL[k]}))));
    const h = el('div', {class: 'scroll'}); p.appendChild(h); sec.appendChild(p);
    const rows = E8.rows.filter(r => r.scenario === 'S3_hot');
    groupedBars(h, {groups: rows.map(r => r.variant), series: pols, get: (g, k) => { const r = rows.find(x => x.variant === g); return r ? {mean: r[k].over || 0, lo: null, hi: null} : null; },
      yLabel: 'chip·s above 80 °C', groupLabel: g => g.replace('|', ' · '), minW: 760, h: 260, extra: (g, k, v) => { const r = rows.find(x => x.variant === g); return [['above target', fmt(v.mean, 0) + ' chip·s'], ['throttled', fmt(r[k].throttled, 0) + ' chip·s'], ['peak', fmt(r[k].peak, 1) + ' °C']]; }});
    const t = el('div', {class: 'panel'}); t.appendChild(el('div', {class: 'scroll'}, `<table><thead><tr><th>Scenario</th><th>Truth | twin</th><th class="n">Self-correcting vs independent</th><th class="n">vs joint</th><th>Verdict vs independent</th></tr></thead><tbody>${
      E8.rows.map(r => `<tr><td>${scName(r.scenario)}</td><td class="mono">${r.variant}</td><td class="n">${pct(r.joint_robust_vs_independent.mean, 2)} <span class="note">[${pct(r.joint_robust_vs_independent.lo, 2)}, ${pct(r.joint_robust_vs_independent.hi, 2)}]</span></td><td class="n">${pct(r.joint_robust_vs_joint.mean, 2)}</td><td><span class="pill ${verdictClass(r.joint_robust_vs_independent.verdict)}">${r.joint_robust_vs_independent.verdict}</span></td></tr>`).join('')}</tbody></table>`)); sec.appendChild(t); }
  if (E7) { const t = el('div', {class: 'panel'}); t.appendChild(el('h3', {}, 'E007 · Move suppression: switching and time-step sensitivity'));
    t.appendChild(el('div', {class: 'scroll'}, `<table><thead><tr><th>Scenario</th><th class="n">Threshold</th><th class="n">dt</th><th class="n">Action changes</th><th class="n">Clock</th><th class="n">Flow</th><th class="n">Supply</th></tr></thead><tbody>${
      E7.switching.map(x => `<tr><td>${scName(x.scenario)}</td><td class="n">${(x.threshold * 100).toFixed(1)}%</td><td class="n">${x.dt} s</td><td class="n">${fmt(x.action_changes, 1)}</td><td class="n">${fmt(x.clock_changes, 1)}</td><td class="n">${fmt(x.flow_changes, 1)}</td><td class="n">${fmt(x.tsup_changes, 1)}</td></tr>`).join('')}</tbody></table>`));
    t.appendChild(el('div', {class: 'scroll'}, `<table><thead><tr><th>Scenario</th><th class="n">Threshold</th><th class="n">Worst change, dt 1 s vs 0.5 s</th><th class="n">Mean</th></tr></thead><tbody>${
      E7.dt_sensitivity.map(d => `<tr><td>${scName(d.scenario)}</td><td class="n">${(d.threshold * 100).toFixed(1)}%</td><td class="n">${(d.max * 100).toFixed(3)}%</td><td class="n">${(d.mean * 100).toFixed(3)}%</td></tr>`).join('')}</tbody></table>`));
    t.appendChild(el('p', {class: 'note'}, 'Most switching is clock changes that track demand, not chattering; supply temperature barely moves. Thresholds up to 2% cost almost nothing but also do not change time-step sensitivity, which is already under 0.5% on 4-hour runs.'));
    sec.appendChild(t); } };

/* Hardware (M001) */
renderers.hardware = sec => { sec.innerHTML = ''; const M = D.M001, C = D.E001C;
  if (!M) { sec.appendChild(el('p', {}, 'No hardware measurement has been recorded yet.')); return; }
  const dev = M.device || {};
  sec.appendChild(el('p', {class: 'lede'}, `First real-hardware measurement: ${dev.name || 'GPU'}, NVML power limit ${fmt(dev.power_limit_W, 0)} W. Compute-bound (FP16 matrix multiply) and memory-bound (FP32 streaming) kernels ran at five locked clocks, one session each, plus a warm-up at a fixed clock. Boundary: GPU board power as reported by NVML, not the host or the cooling plant. These are measurements (class B); the simulator lines are its predictions at the same clocks and temperatures, normalised to the highest clock.`));
  const c = M.compute, mm = M.memory, xs = c.points.map(p => p.s);
  const g = el('div', {class: 'grid2'});
  const p1 = el('div', {class: 'panel'}); p1.appendChild(el('h3', {}, 'Energy per unit of work vs clock (relative to the top clock)'));
  const e1 = [{label: 'Measured, compute kernel', color: 'var(--s1)', x: xs, y: c.points.map(p => p.energy_rel_top), markers: true},
    {label: 'Measured, memory kernel', color: 'var(--s2)', x: xs, y: mm ? mm.points.map(p => p.energy_rel_top) : [], markers: true},
    {label: 'Simulator, registry', color: 'var(--muted)', x: xs, y: M.sim.map(r => r.E_rel), dash: '5 4'},
    {label: 'Simulator, calibrated clock sensitivity', color: 'var(--ink2)', x: xs, y: M.sim.map(r => r.E_rel_cal), dash: '2 3'}];
  p1.appendChild(legend(e1.map(s => ({label: s.label, color: s.color})))); const h1 = el('div'); p1.appendChild(h1);
  p1.appendChild(el('p', {class: 'note'}, `Compute: lowest at ${fmt(c.min_at_clock_MHz, 0)} MHz, ${fmt(100 * c.saving_vs_top, 0)}% below the top clock. Memory: ${mm ? `lowest at ${fmt(mm.min_at_clock_MHz, 0)} MHz, ${fmt(100 * mm.saving_vs_top, 0)}% below, with no loss of throughput` : 'n/a'}.`));
  g.appendChild(p1);
  const p2 = el('div', {class: 'panel'}); p2.appendChild(el('h3', {}, 'Board power vs clock (relative to the top clock)'));
  const e2 = [{label: 'Measured, compute kernel', color: 'var(--s1)', x: xs, y: c.points.map(p => p.power_rel_top), markers: true},
    {label: 'Simulator, registry', color: 'var(--muted)', x: xs, y: M.sim.map(r => r.P_rel), dash: '5 4'}];
  p2.appendChild(legend(e2.map(s => ({label: s.label, color: s.color})))); const h2 = el('div'); p2.appendChild(h2);
  p2.appendChild(el('p', {class: 'note'}, 'The measured curve is flat, then steep. The simulator’s straight-line voltage model cannot follow that, so its voltage fit was rejected; small clock cuts from the top save more than it predicts, deep cuts less.'));
  g.appendChild(p2); sec.appendChild(g);
  requestAnimationFrame(() => { lineChart(h1, {series: e1, yLabel: 'energy / top', xLabel: 'clock / top', h: 230, xFmt: v => fmt(v, 2), yFmt: v => fmt(v, 3), refs: [{y: 1, label: 'top clock', color: 'var(--muted)'}]});
    lineChart(h2, {series: e2, yLabel: 'power / top', xLabel: 'clock / top', h: 230, xFmt: v => fmt(v, 2), yFmt: v => fmt(v, 3)}); });
  const t = el('div', {class: 'panel'}); t.appendChild(el('h3', {}, 'What goes into the simulator'));
  const rows = Object.entries(M.accepted || {}).map(([k, v]) => `<tr><td class="mono">${k}</td><td><span class="pill good">${v.status}</span></td><td class="n">${v.value}${v.measured !== undefined ? ` <span class="note">(measured ${v.measured})</span>` : ''}</td><td>${v.se ? '± ' + fmt(1.96 * v.se, 3) + ' (95% CI)' : ''}</td></tr>`)
    .concat(Object.entries(M.rejected || {}).map(([k, v]) => `<tr><td class="mono">${k}</td><td><span class="pill crit">rejected</span></td><td class="n note">not used</td><td>${v.reason.replace(/</g, '&lt;')}</td></tr>`));
  t.appendChild(el('div', {class: 'scroll'}, `<table><thead><tr><th>Parameter</th><th>Status</th><th class="n">Value</th><th>Detail</th></tr></thead><tbody>${rows.join('')}</tbody></table>`));
  t.appendChild(el('p', {class: 'note'}, 'Acceptance rules: a fit that ends at an edge of its allowed range is rejected (R1); a value less precise than the range the sensitivity study already covers is rejected (R2); a value outside its physical range is moved to the limit only if its 95% CI reaches it (R3). Full report: docs/10_calibration_results.md.'));
  sec.appendChild(t);
  if (C) { const p = el('div', {class: 'panel'}); p.appendChild(el('h3', {}, 'E001C · The benchmark re-run with the measured clock sensitivity (seed-paired change vs E001)'));
    const ji = Object.fromEntries(C.joint_vs_independent_change.map(r => [r.scenario, r]));
    const pp = r => `${(100 * r.mean).toFixed(2)} <span class="note">[${(100 * r.lo).toFixed(2)}, ${(100 * r.hi).toFixed(2)}]</span>`;
    p.appendChild(el('div', {class: 'scroll'}, `<table><thead><tr><th>Scenario</th><th class="n">Compute-only vs fixed, E001</th><th class="n">E001C</th><th class="n">Change (pp)</th><th class="n">Joint vs independent, E001</th><th class="n">E001C</th><th class="n">Change (pp)</th></tr></thead><tbody>${
      C.compute_vs_fixed_change.map(r => { const j = ji[r.scenario]; return `<tr><td>${scName(r.scenario)}</td><td class="n">${pct(r.orig, 1)}</td><td class="n">${pct(r.calibrated, 1)}</td><td class="n">${pp(r)}</td><td class="n">${j ? pct(j.orig, 2) : '–'}</td><td class="n">${j ? pct(j.calibrated, 2) : '–'}</td><td class="n">${j ? pp(j) : '–'}</td></tr>`; }).join('')}</tbody></table>`));
    p.appendChild(el('p', {class: 'note'}, 'Only the two accepted values changed; every other parameter is still a placeholder. Hypotheses were committed before the run. Disclosure: ' + C.disclosure.replace(/</g, '&lt;')));
    sec.appendChild(p); } };

/* Explorer */
const X = D.explorer; const xs = {s: X.s.indexOf(1) >= 0 ? X.s.indexOf(1) : X.s.length - 1, a: X.t_amb.indexOf(20), t: null, f: null};
renderers.explorer = sec => { sec.innerHTML = '';
  sec.appendChild(el('p', {class: 'lede'}, `Steady state of the node with all ${X.n} accelerators busy on compute-bound work. Every cell comes from the same physics module the simulator uses, precomputed for this page. Pick a clock and an ambient temperature, then hover or tap a cell to see the thermal-resistance stack behind it. Colour shows grid energy per unit of work; the ringed cell is the cheapest setting that keeps junctions at or below ${X.t_target} °C.`));
  const ctr = el('div', {class: 'controls'});
  ctr.appendChild(el('label', {class: 'ctl', for: 'xs-s'}, 'Clock')); const sS = el('select', {id: 'xs-s'}); X.s.forEach((v, i) => sS.appendChild(el('option', {value: i}, `${Math.round(v * 100)}% of max`))); sS.value = xs.s; ctr.appendChild(sS);
  ctr.appendChild(el('label', {class: 'ctl', for: 'xs-a'}, 'Ambient')); const sA = el('select', {id: 'xs-a'}); X.t_amb.forEach((v, i) => sA.appendChild(el('option', {value: i}, `${v} °C`))); sA.value = xs.a; ctr.appendChild(sA);
  sS.addEventListener('change', () => { xs.s = +sS.value; draw(); }); sA.addEventListener('change', () => { xs.a = +sA.value; draw(); }); sec.appendChild(ctr);
  const g = el('div', {class: 'grid2'}); const p1 = el('div', {class: 'panel'}); p1.appendChild(el('h3', {}, 'Grid energy per nominal work-second (J), by supply temperature and flow')); const hm = el('div', {class: 'scroll'}); p1.appendChild(hm);
  const lg = el('div', {class: 'legend'}); p1.appendChild(lg); g.appendChild(p1);
  const p2 = el('div', {class: 'panel'}); p2.appendChild(el('h3', {}, 'Thermal-resistance stack for the selected cell')); const ld = el('div'); p2.appendChild(ld); const ro = el('div', {class: 'readout'}); p2.appendChild(ro); g.appendChild(p2); sec.appendChild(g);
  const seq = ['var(--seq1)', 'var(--seq2)', 'var(--seq3)', 'var(--seq4)', 'var(--seq5)', 'var(--seq6)', 'var(--seq7)'];
  function cell(ti, fi) { const q = k => X[k][xs.s][ti][fi][xs.a]; return {Tj: q('Tj'), P: q('P_chip'), pump: q('P_pump'), fan: q('P_fan'), ch: q('W_ch'), grid: q('P_grid'), J: q('J_per_work')}; }
  function best() { let b = null; X.t_sup.forEach((t, ti) => X.flow.forEach((f, fi) => { const c = cell(ti, fi); if (fin(c.J) && c.Tj <= X.t_target && (!b || c.J < b.c.J)) b = {ti, fi, c}; })); return b; }
  function draw() { hm.innerHTML = ''; const B = best(); if (xs.t === null && B) { xs.t = B.ti; xs.f = B.fi; }
    const all = []; X.t_sup.forEach((t, ti) => X.flow.forEach((f, fi) => { const c = cell(ti, fi); if (fin(c.J)) all.push(c.J); })); const lo = Math.min(...all), hi = Math.max(...all);
    const band = v => seq[Math.min(seq.length - 1, Math.floor((v - lo) / ((hi - lo) || 1) * seq.length))];
    const m = {l: 122, t: 6, b: 34, r: 6}; const cw = Math.max(9, Math.floor((width(hm) - m.l - m.r) / X.t_sup.length)), chh = 30;
    const W = m.l + m.r + cw * X.t_sup.length, H = m.t + m.b + chh * X.flow.length;
    const svg = S('svg', {viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', 'aria-label': 'Energy per work heat map'}, hm);
    X.flow.forEach((f, fi) => { const yy = m.t + (X.flow.length - 1 - fi) * chh; S('text', {x: m.l - 6, y: yy + chh / 2 + 4, 'text-anchor': 'end', text: `${f}× · ${fmt(f * X.lpm, 1)} L/min`, style: 'font-family:var(--f-mono);font-size:10.5px'}, svg);
      X.t_sup.forEach((t, ti) => { const c = cell(ti, fi), xx = m.l + ti * cw; let fill = 'var(--sunk)'; if (fin(c.J)) fill = band(c.J);
        S('rect', {x: xx + 1, y: yy + 1, width: cw - 2, height: chh - 2, rx: 2, style: `fill:${fill}`}, svg);
        if (!fin(c.J) || c.Tj > X.t_throttle) S('text', {x: xx + cw / 2, y: yy + chh / 2 + 4, 'text-anchor': 'middle', text: '×', style: 'fill:var(--crit);font-weight:600'}, svg);
        else if (c.Tj > X.t_target) S('rect', {x: xx + 2, y: yy + 2, width: cw - 4, height: chh - 4, rx: 2, style: 'fill:none;stroke:var(--warn);stroke-width:1.5'}, svg);
        if (B && B.ti === ti && B.fi === fi) S('circle', {cx: xx + cw / 2, cy: yy + chh / 2, r: 6, style: 'fill:none;stroke:var(--ink);stroke-width:2'}, svg);
        if (xs.t === ti && xs.f === fi) S('rect', {x: xx, y: yy, width: cw, height: chh, style: 'fill:none;stroke:var(--accent);stroke-width:2'}, svg);
        const hit = S('rect', {x: xx, y: yy, width: cw, height: chh, fill: 'transparent', style: 'cursor:pointer'}, svg);
        const pick = ev => { xs.t = ti; xs.f = fi; detail(); if (ev) showTip(ev, `${t} °C supply · ${f}× flow`, [['junction', fin(c.Tj) ? fmt(c.Tj, 1) + ' °C' : 'runaway'], ['J per work-s', fmt(c.J, 1)], ['node grid power', fmt(c.grid / 1000, 2) + ' kW']]); };
        hit.addEventListener('mousemove', pick); hit.addEventListener('click', ev => { pick(ev); draw(); }); hit.addEventListener('mouseleave', hideTip); }); });
    X.t_sup.forEach((t, ti) => { if (t % 5 === 0) S('text', {x: m.l + ti * cw + cw / 2, y: H - m.b + 14, 'text-anchor': 'middle', text: t}, svg); });
    S('text', {x: m.l + (W - m.l) / 2, y: H - 4, 'text-anchor': 'middle', text: 'Coolant supply temperature (°C)'}, svg);
    lg.innerHTML = `<span><span class="sw" style="background:var(--seq1)"></span>${fmt(lo, 0)} J (lowest)</span><span><span class="sw" style="background:var(--seq7)"></span>${fmt(hi, 0)} J (highest)</span><span><span class="sw" style="background:transparent;outline:1.5px solid var(--warn)"></span>junction &gt; ${X.t_target} °C</span><span style="color:var(--crit);font-weight:600">× above ${X.t_throttle} °C or runaway</span><span>◯ cheapest setting within target</span>`;
    detail(); }
  function detail() { const ti = xs.t, fi = xs.f; if (ti === null) return; const c = cell(ti, fi), t = X.t_sup[ti], f = X.flow[fi];
    const Rcal = X.R_cal[fi], Rconv = X.R_conv[fi], Rcond = X.R_cond; ld.innerHTML = '';
    const W = Math.max(300, width(ld)), H = 150; const svg = S('svg', {viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: 'ladder'}, ld);
    if (!fin(c.Tj)) { S('text', {x: 10, y: 40, text: 'No steady state: leakage grows faster than cooling can remove it (thermal runaway).', style: 'fill:var(--crit)'}, svg); ro.innerHTML = ''; return; }
    const P = c.P, T1 = t + P * Rcal, T2 = T1 + P * Rconv;
    const rows = [['Coolant warming (caloric)', Rcal, t, T1, 'var(--s3)'], ['Convection to coolant', Rconv, T1, T2, 'var(--s1)'], ['Conduction + TIM to junction', Rcond, T2, c.Tj, 'var(--s2)']];
    const H2 = 44 + rows.length * 40; svg.setAttribute('viewBox', `0 0 ${W} ${H2}`); svg.setAttribute('height', H2);
    const m = {l: 8, r: 12}, x = lin(t - 2, Math.max(c.Tj, X.t_throttle) + 3, m.l, W - m.r);
    [[X.t_target, 'var(--warn)', `${X.t_target} °C target`, 'end', -4], [X.t_throttle, 'var(--crit)', `${X.t_throttle} °C throttle`, 'start', 4]].forEach(([v, col, lab, anc, dx]) => {
      S('line', {x1: x(v), x2: x(v), y1: 18, y2: H2 - 4, style: `stroke:${col};stroke-dasharray:3 3`}, svg); S('text', {x: x(v) + dx, y: 12, 'text-anchor': anc, text: lab, style: `fill:${col}`}, svg); });
    rows.forEach(([lab, R, a, b, col], i) => { const yy = 30 + i * 40;
      S('text', {x: m.l, y: yy, text: `${lab} · ${fmt(R * 1000, 1)} mK/W · ΔT ${fmt(b - a, 1)} K`, style: 'fill:var(--ink2)'}, svg);
      S('rect', {x: x(a), y: yy + 6, width: Math.max(2, x(b) - x(a)), height: 14, rx: 3, style: `fill:${col}`}, svg);
      S('text', {x: x(b) + 5, y: yy + 17, text: `${fmt(b, 1)} °C`, style: 'fill:var(--ink)'}, svg); });
    S('text', {x: x(t), y: H2 - 4, 'text-anchor': 'middle', text: `${fmt(t, 0)} °C in`, style: 'fill:var(--muted)'}, svg);
    ro.innerHTML = [['Junction', fmt(c.Tj, 1) + ' °C'], ['Power per accelerator', fmt(c.P, 0) + ' W'], ['Pump', fmt(c.pump, 0) + ' W'], ['Fans', fmt(c.fan, 0) + ' W'], ['Chiller', fmt(c.ch, 0) + ' W'], ['Node grid power', fmt(c.grid / 1000, 2) + ' kW'], ['Energy per work-second', fmt(c.J, 1) + ' J']]
      .map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join(''); }
  draw(); };

/* Assumptions */
let aFilter = '', aClass = 'all';
renderers.assumptions = sec => { sec.innerHTML = '';
  sec.appendChild(el('p', {class: 'lede'}, 'Every number the simulator uses, with its evidence class. A: established physics · B: published experiment · C: published simulation · D: commercial capability · E: engineering extrapolation · F: placeholder chosen for this study · G: design choice. Classes E and F are not measurements; every E/F value with a range is swept in E002.'));
  const ctr = el('div', {class: 'controls'}); const inp = el('input', {type: 'search', id: 'a-q', placeholder: 'Filter parameters', 'aria-label': 'Filter parameters'}); inp.value = aFilter; ctr.appendChild(inp);
  ['all', 'A', 'E', 'F', 'G'].forEach(c => { const b = el('button', {class: 'chip', 'aria-pressed': c === aClass, type: 'button'}, c === 'all' ? 'All classes' : 'Class ' + c); b.addEventListener('click', () => { aClass = c; renderers.assumptions(sec); }); ctr.appendChild(b); });
  sec.appendChild(ctr); const host = el('div', {class: 'panel scroll'}); sec.appendChild(host);
  const draw = () => { const q = aFilter.toLowerCase(); const rows = D.assumptions.filter(p => (aClass === 'all' || p.evidence === aClass) && (!q || (p.name + p.source + p.group).toLowerCase().includes(q)));
    host.innerHTML = `<table><thead><tr><th>Group</th><th>Parameter</th><th class="n">Value</th><th>Unit</th><th>Class</th><th class="n">Range swept</th><th>Source / rationale</th></tr></thead><tbody>${
      rows.map(p => `<tr><td>${p.group}</td><td class="mono">${p.name}</td><td class="n">${p.value}</td><td>${p.unit}</td><td><span class="pill ${p.evidence === 'A' ? 'good' : p.evidence === 'F' ? 'warn' : ''}">${p.evidence}</span></td><td class="n">${p.low !== null ? p.low + ' – ' + p.high : ''}</td><td>${p.source}</td></tr>`).join('')}</tbody></table>`; };
  inp.addEventListener('input', () => { aFilter = inp.value; draw(); }); draw(); };

/* Log */
renderers.log = sec => { sec.innerHTML = '';
  const p = el('div', {class: 'panel'}); p.appendChild(el('h3', {}, 'Experiment register (superseded and failed experiments are kept)'));
  p.appendChild(el('div', {class: 'scroll'}, `<table><thead><tr><th>Id</th><th>Status</th><th>Runs</th><th>Title</th></tr></thead><tbody>${
    D.experiments.map(x => `<tr><td class="mono">${x.id}</td><td><span class="pill ${x.status === 'completed' ? 'good' : x.status === 'failed' ? 'crit' : 'warn'}">${x.status}</span></td><td class="mono">${x.summary ? JSON.stringify(x.summary) : ''}</td><td>${x.title}</td></tr>`).join('')}</tbody></table>`));
  sec.appendChild(p);
  const l = el('div', {class: 'panel'}); l.appendChild(el('h3', {}, 'Research log (append-only)')); const ul = el('ul', {class: 'log'});
  D.research_log.forEach(([t, e]) => ul.appendChild(el('li', {}, `<time>${t.replace('T', ' ').replace('+00:00', '')}</time>${e.replace(/</g, '&lt;')}`))); l.appendChild(ul); sec.appendChild(l); };

const start = (location.hash || '').slice(1); show(TABS.some(t => t[0] === start) ? start : 'overview');
</script>
"""
