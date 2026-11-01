"""Thermal credits for placement: the budget left on every GPU a placement would heat.

A placement puts power p_g on GPUs G. The affected set is G plus every GPU downstream of a placed GPU in a
series cold-plate chain (its inlet rises by the upstream power / (m_dot c_p)). The placement's credit is

    credit = min over affected GPUs a of  [ dP_max,a(H, T_in,a + shift_a) - p_a ]  / P_ref       (-)

i.e. the smallest remaining power budget, in units of a reference GPU power, after the job is added.
credit >= 0 means no affected GPU is predicted to reach the effective limit within H. The scheduler prefers
the placement with the largest credit (most thermal slack preserved), and treats credit < 0 as "would
throttle". H is the job's expected duration capped at ``horizon_cap_s`` (beyond a few tau the budget is
the steady headroom anyway).
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

from .thermal_capacity import power_budget


def placement_credit(view, gpus: Sequence[int], p_job: Sequence[float], H: float, T_lim: float,
                     P_ref: float) -> float:
    """``view`` exposes per-GPU arrays T, T_in, R, C, P (current), the series topology via
    ``downstream(g) -> list[int]`` and ``cdot(g) -> W/K`` of the coolant stream through g."""
    gpus = list(gpus)
    extra = {g: float(p) for g, p in zip(gpus, p_job)}
    shift: dict[int, float] = {}
    for g, p in extra.items():
        for d in view.downstream(g):
            shift[d] = shift.get(d, 0.0) + p / view.cdot(g)
    affected = sorted(set(extra) | set(shift))
    idx = np.array(affected)
    T_in = view.T_in[idx] + np.array([shift.get(a, 0.0) for a in affected])
    bud = power_budget(view.T[idx], T_in, view.R[idx], view.C[idx], view.P[idx], T_lim, H)
    rem = bud - np.array([extra.get(a, 0.0) for a in affected])
    return float(rem.min() / P_ref)
