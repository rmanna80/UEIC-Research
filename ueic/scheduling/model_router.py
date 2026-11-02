"""Model routing from *measured* quality and energy (Stage 5, Part 8).

A ``ModelProfile`` carries what an E017-style session measured for one model at one operating point:
accuracy on a task (correct / scored, with n), GPU energy per request, p95 latency, peak power, the
temperature at which it was measured, and the session it came from. The router never invents a quality
score: a model without a measured accuracy for the task is not routable for it (KeyError).

Quality is judged conservatively by the lower Wilson 95% bound of the measured accuracy. Among models
meeting the quality floor and latency SLO, the router picks the lowest *predicted facility* energy per
request under the current conditions:

  E_fac = E_gpu,meas x leak_ratio(T_now, T_meas) x (1 + cooling_overhead)
  leak_ratio = P(s=1, T_now) / P(s=1, T_meas) from the registry power model (prediction, class F/B)
  cooling_overhead = plant electricity / IT heat at the current supply and ambient (physics.plant)

and drops models whose measured peak power exceeds the available electrical headroom. So the energy-optimal
route can change with GPU temperature, shared cooling state and power caps. These adjustments are model
predictions layered on measurements and are labelled as such in the decision record.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .. import physics as ph


@dataclass
class ModelProfile:
    name: str
    accuracy: dict[str, tuple[int, int]]        # task -> (n_correct, n_scored)
    J_per_request: float                        # measured, GPU boundary
    p95_latency_s: float
    peak_power_W: float
    T_meas_C: float
    source: str                                 # session directory or "synthetic"
    extra: dict = field(default_factory=dict)


def wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - r) / d


def cooling_overhead(cfg, Q_W: float, T_sup: float, T_amb: float, flow_factor: float = 1.0) -> float:
    pl = ph.plant(Q_W, T_sup, flow_factor, T_amb, cfg)
    return float((pl["P_fan"] + pl["W_ch"]) / max(Q_W, 1e-9))


def route(task: str, profiles: list[ModelProfile], cfg, *, quality_floor: float, latency_slo_s: float,
          T_gpu: float, T_sup: float, T_amb: float, power_headroom_W: float, Q_node_W: float) -> dict:
    cands, rejected = [], {}
    for p in profiles:
        if task not in p.accuracy:
            raise KeyError(f"{p.name} has no measured accuracy for {task!r}; refusing to route on an invented score")
        lo = wilson_lower(*p.accuracy[task])
        if lo < quality_floor:
            rejected[p.name] = f"quality lower bound {lo:.3f} < {quality_floor}"
        elif p.p95_latency_s > latency_slo_s:
            rejected[p.name] = f"p95 {p.p95_latency_s:.1f} s > SLO {latency_slo_s} s"
        elif p.peak_power_W > power_headroom_W:
            rejected[p.name] = f"peak {p.peak_power_W:.0f} W > headroom {power_headroom_W:.0f} W"
        else:
            leak = float(ph.chip_power(1.0, T_gpu, 1.0, cfg) / ph.chip_power(1.0, p.T_meas_C, 1.0, cfg))
            ovh = cooling_overhead(cfg, Q_node_W, T_sup, T_amb)
            cands.append((p.J_per_request * leak * (1 + ovh), p.name, leak, ovh))
    if not cands:
        return {"model": None, "rejected": rejected}
    E, name, leak, ovh = min(cands)
    return {"model": name, "predicted_facility_J": E, "leak_ratio": leak, "cooling_overhead": ovh,
            "rejected": rejected, "basis": "measured GPU energy x model-predicted leakage and cooling factors"}
