"""Placement policies for the facility simulator (Stage 5). Interface:

    select(job, view, t) -> (gpus, clock) | None        None = leave the job queued

All policies see the same snapshot (``FacilityView``) and run under the same hardware layers (thermal
throttle, power caps), which they cannot bypass. Multi-GPU jobs are placed inside one node when any node
has enough eligible GPUs, otherwise across nodes (communication costs apply). Baselines are
work-conserving (never hold a job when a placement exists); the thermal-credit policy may hold a job or
lower its clock, by the stated admission rule (``thermal_admission.admit``).

  round_robin        next eligible GPUs after a rotating pointer
  least_loaded       node with the most free GPUs
  power_aware        rack with the most power headroom, then node and GPUs with the lowest current power
  temperature_aware  node with the coolest eligible GPUs, then the coolest GPUs
  thermal_credit     placement that keeps the most thermal budget over the job's duration (thermal_credits),
                     including inlet rises it causes downstream in series chains; lower clock or hold if
                     no placement stays within budget
  thermal_placement  ablation: the same placement rule at full clock, never holding a job
"""
from __future__ import annotations

import numpy as np

from .thermal_admission import admit
from .thermal_credits import placement_credit


def _node_groups(view, elig: np.ndarray, n: int, key: np.ndarray):
    """Per node with >= n eligible GPUs: the n GPUs with the smallest key."""
    out = []
    for nd in np.unique(view.node[elig]):
        g = np.nonzero(elig & (view.node == nd))[0]
        if g.size >= n:
            out.append((int(nd), g[np.argsort(key[g], kind="stable")[:n]]))
    return out


def _cross(elig: np.ndarray, n: int, key: np.ndarray):
    g = np.nonzero(elig)[0]
    return g[np.argsort(key[g], kind="stable")[:n]] if g.size >= n else None


class _Base:
    name = "base"

    def __init__(self, **kw):
        self.kw = kw

    def key(self, view, job):
        return np.arange(view.T.size, dtype=float)

    def node_score(self, view, nd, gpus):      # lower is better
        return 0.0

    def select(self, job, view, t):
        elig = view.eligible(job)
        key = self.key(view, job)
        groups = _node_groups(view, elig, job.n_gpus, key)
        if groups:
            nd, g = min(groups, key=lambda x: (self.node_score(view, x[0], x[1]), x[0]))
            return g, 1.0
        g = _cross(elig, job.n_gpus, key)
        return None if g is None else (g, 1.0)


class RoundRobin(_Base):
    name = "round_robin"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.ptr = 0

    def select(self, job, view, t):
        G = view.T.size
        order = (np.arange(G) + self.ptr) % G
        elig = view.eligible(job)
        pick = [int(g) for g in order if elig[g]][: job.n_gpus]
        if len(pick) < job.n_gpus:
            return None
        self.ptr = (pick[-1] + 1) % G
        return np.array(pick), 1.0


class LeastLoaded(_Base):
    name = "least_loaded"

    def node_score(self, view, nd, gpus):
        return float(view.busy[view.node == nd].sum())


class PowerAware(_Base):
    name = "power_aware"

    def key(self, view, job):
        return view.P

    def node_score(self, view, nd, gpus):
        r = view.rack[gpus[0]]
        head = view.rack_limits[r] - view.rack_power()[r]
        node_p = float(view.P[view.node == nd].sum())
        return (-head if np.isfinite(head) else 0.0, node_p)


class TemperatureAware(_Base):
    name = "temperature_aware"

    def key(self, view, job):
        return view.T

    def node_score(self, view, nd, gpus):
        return float(view.T[gpus].mean())


class ThermalCredit(_Base):
    """Maximise the minimum remaining thermal budget (thermal_credits.placement_credit)."""
    name = "thermal_credit"

    def __init__(self, horizon_cap_s: float = 600.0, margin_K: float = 2.0, clocks=(0.9, 0.8, 0.7, 0.6),
                 hold_s: float = 60.0, **kw):
        super().__init__(**kw)
        self.H_cap, self.margin, self.clocks, self.hold_s = horizon_cap_s, margin_K, tuple(clocks), hold_s
        self.decisions: dict[str, int] = {}

    def _best(self, job, view, cands, s):
        H = min(job.remaining / max(s ** 0.95, 1e-3), self.H_cap)
        T_lim = view.t_target - self.margin
        P_ref = float(view.cfg.p_dyn_max + view.cfg.p_static_other)
        best = None
        for g in cands:
            cr = placement_credit(view, g, view.job_power(g, job, s), H, T_lim, P_ref)
            if best is None or cr > best[0]:
                best = (cr, g, s)
        return best

    def select(self, job, view, t):
        elig = view.eligible(job)
        if elig.sum() < job.n_gpus:
            return None
        # candidate per node: GPUs with the largest individual budget; plus one cross-node set
        T_lim = view.t_target - self.margin
        from .thermal_capacity import power_budget
        H = min(job.remaining, self.H_cap)
        bud = power_budget(view.T, view.T_in, view.R, view.C, view.P, T_lim, H)
        cands = [g for _, g in _node_groups(view, elig, job.n_gpus, -bud)]
        if not cands:
            g = _cross(elig, job.n_gpus, -bud)
            cands = [g] if g is not None else []
        full = self._best(job, view, cands, 1.0)
        red = None
        if full is None or full[0] < 0:
            for s in self.clocks:
                r = self._best(job, view, cands, s)
                beta = view.cfg.beta_memory if job.memory_bound else view.cfg.beta_compute
                if r is not None and r[0] >= 0 and (job.deadline - t) >= job.remaining / s ** beta:
                    red = r
                    break
        nominal = job.remaining
        decision, pl = admit(full, red, job.deadline - t, nominal, self.hold_s)
        self.decisions[decision] = self.decisions.get(decision, 0) + 1
        return None if pl is None else (pl[1], pl[2])


class ThermalPlacement(ThermalCredit):
    """Ablation: thermal-credit placement only (full clock, never holds)."""
    name = "thermal_placement"

    def __init__(self, **kw):
        super().__init__(**{**kw, "clocks": (), "hold_s": float("inf")})


SCHEDULERS = {c.name: c for c in (RoundRobin, LeastLoaded, PowerAware, TemperatureAware, ThermalCredit,
                                  ThermalPlacement)}


def make_scheduler(name: str, **kw):
    if name not in SCHEDULERS:
        raise KeyError(f"unknown scheduler {name!r}; have {sorted(SCHEDULERS)}")
    return SCHEDULERS[name](**kw)
