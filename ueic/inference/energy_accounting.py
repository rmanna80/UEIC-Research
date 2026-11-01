"""Energy over a measurement window and its allocation to requests, with every boundary named.

Boundaries (never mixed):
  gpu_total      NVML board energy over the window: measured (sensor accuracy per the vendor; the
                 board sensor is not independently calibrated).
  gpu_dynamic    gpu_total - P_idle x duration, with P_idle from a separate idle measurement on the same
                 GPU, same clocks. Measured minus measured; carries both uncertainties.
  wall           an external wall-power meter, if one was logged (measured, whole host).
  facility_est   a boundary's energy x a *stated* overhead factor for cooling and conversion. Estimated,
                 never measured; the factor's source must be given.

Window energy: the GPU's cumulative energy counter (NVML total energy, J) when every sample has it and
it never decreases; otherwise trapezoidal integration of power. Coverage and the largest sampling gap
are reported; a gap > ``max_gap_s`` makes the window "incomplete".

Allocation to requests (the sum of allocations is conserved and reported):
  equal_inflight   each sampling interval's dynamic energy is split equally among the requests in
                   flight (submit..end) during that interval; dynamic energy while no request is in
                   flight is reported as "unattributed".
  token_share      dynamic energy split in proportion to each request's prompt + completion tokens.
Idle energy is never allocated to requests; it is reported as its own term, and so is the facility
overhead. Neither allocation is "true": they answer different questions and are labelled.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

import numpy as np

from .request_tracing import RequestTrace

J_PER_KWH = 3.6e6
_trapz = getattr(np, "trapezoid", None) or np.trapz      # numpy < 2 lacks trapezoid


def window_energy(t: Sequence[float], power_W: Sequence[float | None], energy_J: Sequence[float | None] | None,
                  t0: float, t1: float, max_gap_s: float = 1.0) -> dict[str, Any]:
    t = np.asarray(t, dtype=float)
    p = np.array([np.nan if x is None else float(x) for x in power_W])
    e = None if energy_J is None else np.array([np.nan if x is None else float(x) for x in energy_J])
    m = (t >= t0) & (t <= t1)
    if m.sum() < 2:
        return {"E_J": float("nan"), "method": "none", "complete": False, "n_samples": int(m.sum()),
                "reason": "fewer than 2 samples in the window"}
    tt, pp = t[m], p[m]
    gaps = np.diff(tt)
    edge = max(tt[0] - t0, t1 - tt[-1])
    max_gap = float(max(gaps.max(), edge))
    out: dict[str, Any] = {"n_samples": int(m.sum()), "max_gap_s": max_gap, "duration_s": t1 - t0,
                           "coverage": float((tt[-1] - tt[0]) / max(t1 - t0, 1e-12))}
    ee = None if e is None else e[m]
    if ee is not None and np.all(np.isfinite(ee)) and np.all(np.diff(ee) >= 0):
        E = float(ee[-1] - ee[0])
        # extend to the window edges with the edge powers (counter covers only [tt0, ttN])
        E += (tt[0] - t0) * (pp[0] if np.isfinite(pp[0]) else 0.0) + (t1 - tt[-1]) * (pp[-1] if np.isfinite(pp[-1]) else 0.0)
        out.update(E_J=E, method="energy_counter")
    else:
        ok = np.isfinite(pp)
        if ok.sum() < 2:
            return {**out, "E_J": float("nan"), "method": "none", "complete": False, "reason": "no power samples"}
        E = float(_trapz(pp[ok], tt[ok])) + (tt[ok][0] - t0) * pp[ok][0] + (t1 - tt[ok][-1]) * pp[ok][-1]
        out.update(E_J=E, method="trapezoid_power")
    out["complete"] = max_gap <= max_gap_s
    return out


def allocate(traces: Sequence[RequestTrace], t: Sequence[float], power_W: Sequence[float | None],
             idle_W: float, method: str = "equal_inflight") -> dict[str, Any]:
    """Allocate dynamic GPU energy (power - idle) to requests. Returns per-request joules and totals."""
    tr = [x for x in traces if np.isfinite(x.t_submit) and np.isfinite(x.t_end)]
    if not tr:
        return {"per_request_J": {}, "allocated_J": 0.0, "unattributed_J": 0.0, "method": method}
    t = np.asarray(t, dtype=float)
    p = np.array([np.nan if x is None else float(x) for x in power_W])
    lo, hi = min(x.t_submit for x in tr), max(x.t_end for x in tr)
    m = (t >= lo) & (t <= hi) & np.isfinite(p)
    tt, dyn = t[m], p[m] - idle_W
    per = {x.request_id: 0.0 for x in tr}
    if tt.size < 2:
        return {"per_request_J": per, "allocated_J": 0.0, "unattributed_J": 0.0, "method": method}
    e_int = 0.5 * (dyn[1:] + dyn[:-1]) * np.diff(tt)            # dynamic J in each sampling interval
    total = float(e_int.sum())
    if method == "token_share":
        w = np.array([(x.prompt_tokens or 0) + (x.completion_tokens or 0) for x in tr], dtype=float)
        if w.sum() <= 0:
            raise ValueError("token_share needs token counts")
        for x, wi in zip(tr, w):
            per[x.request_id] = total * wi / w.sum()
        return {"per_request_J": per, "allocated_J": total, "unattributed_J": 0.0, "dynamic_J": total, "method": method}
    if method != "equal_inflight":
        raise ValueError(f"unknown allocation method {method!r}")
    mid = 0.5 * (tt[1:] + tt[:-1])
    sub = np.array([x.t_submit for x in tr])
    end = np.array([x.t_end for x in tr])
    unattributed = 0.0
    for k, (tm, ek) in enumerate(zip(mid, e_int)):
        active = np.nonzero((sub <= tm) & (end >= tm))[0]
        if active.size == 0:
            unattributed += float(ek)
            continue
        share = float(ek) / active.size
        for j in active:
            per[tr[j].request_id] += share
    return {"per_request_J": per, "allocated_J": total - unattributed, "unattributed_J": unattributed,
            "dynamic_J": total, "method": method}


def useful_metrics(traces: Iterable[RequestTrace], E_boundary_J: float, boundary: str,
                   price_per_kWh: float | None = None) -> dict[str, Any]:
    """Efficiency metrics for one boundary. 'Useful' = scored correct AND deadline met (or no deadline)."""
    tr = list(traces)
    ok = [x for x in tr if x.status == "ok"]
    good = [x for x in ok if x.correct and x.deadline_met is not False]
    out_tok = sum(x.completion_tokens or 0 for x in ok)
    all_tok = out_tok + sum(x.prompt_tokens or 0 for x in ok)
    d = lambda a, b: a / b if b else float("nan")   # noqa: E731
    res = {"boundary": boundary, "E_J": E_boundary_J, "n_requests": len(tr), "n_ok": len(ok), "n_useful": len(good),
           "J_per_output_token": d(E_boundary_J, out_tok), "J_per_token_all": d(E_boundary_J, all_tok),
           "J_per_request": d(E_boundary_J, len(tr)), "J_per_useful_result": d(E_boundary_J, len(good)),
           "useful_fraction": d(len(good), len(tr))}
    if price_per_kWh is not None:
        res["cost_per_useful_result"] = d(E_boundary_J / J_PER_KWH * price_per_kWh, len(good))
        res["price_per_kWh"] = price_per_kWh
    return res
