"""Synthetic workload generation and scenario definitions.

The workload is synthetic (evidence class F). It is generated once per seed and
shared across policies so comparisons are paired: every policy sees the same
tasks, sizes, classes and pre-drawn outcome random numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np

COMPUTE, MEMORY = 0, 1


@dataclass(frozen=True)
class Scenario:
    name: str
    duration_s: float = 4 * 3600.0
    load_mean: float = 0.5          # mean offered utilisation at s=1 (fraction of cluster)
    load_amp: float = 0.25          # sinusoidal amplitude of offered utilisation
    load_period_s: float = 4 * 3600.0
    t_amb: float = 20.0             # ambient dry-bulb temperature, degC (held constant)
    routing: bool = False           # small-model cascade with verification
    param_overrides: dict = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Workload:
    arrival: np.ndarray
    work: np.ndarray        # nominal seconds of large-model work at s=1
    cls: np.ndarray         # 0 compute-bound, 1 memory-bound
    easy: np.ndarray        # bool, task within small model's competence
    u_small: np.ndarray     # pre-drawn uniforms for outcomes (pairing across policies)
    u_verify: np.ndarray
    u_large: np.ndarray
    slo: np.ndarray         # latency SLO per task, s

    @property
    def n(self) -> int:
        return len(self.arrival)


def offered_load(t, sc: Scenario):
    return np.clip(sc.load_mean + sc.load_amp * np.sin(2 * np.pi * np.asarray(t) / sc.load_period_s), 0.0, None)


def generate(cfg, sc: Scenario, seed: int) -> Workload:
    """Non-homogeneous Poisson arrivals (thinning) with lognormal job sizes."""
    rng = np.random.default_rng(seed)
    mean_w = cfg.job_work_mean
    lam_scale = cfg.n_accel / mean_w            # tasks/s per unit offered utilisation
    lam_max = (sc.load_mean + abs(sc.load_amp)) * lam_scale
    if lam_max <= 0:
        raise ValueError("Scenario has zero load")
    # thinning
    n_cand = int(rng.poisson(lam_max * sc.duration_s * 1.2) + 50)
    gaps = rng.exponential(1.0 / lam_max, size=n_cand)
    t = np.cumsum(gaps)
    while t[-1] < sc.duration_s:  # extremely unlikely; extend
        t = np.concatenate([t, t[-1] + np.cumsum(rng.exponential(1.0 / lam_max, size=n_cand))])
    t = t[t < sc.duration_s]
    keep = rng.random(t.size) < offered_load(t, sc) * lam_scale / lam_max
    arrival = t[keep]
    n = arrival.size
    sigma = cfg.job_work_sigma
    mu = np.log(mean_w) - sigma ** 2 / 2.0
    work = rng.lognormal(mu, sigma, size=n)
    cls = (rng.random(n) < cfg.frac_memory).astype(np.int8)
    easy = rng.random(n) < cfg.frac_easy
    u_small, u_verify, u_large = rng.random(n), rng.random(n), rng.random(n)
    slo = cfg.slo_base + cfg.slo_factor * work
    return Workload(arrival, work, cls, easy, u_small, u_verify, u_large, slo)


def routing_expectations(cfg) -> dict[str, float]:
    """Analytic expectations for the small-model cascade (per task, relative to large-only).

    Cascade: run small model + verifier (cost rs + rv); if the verifier rejects,
    escalate to the large model (cost 1). Large-only: cost 1.
      P_reject  = sum_d w_d [ p_d * fr + (1 - p_d) * (1 - fa) ]
      E[work]   = rs + rv + P_reject
      P_success = sum_d w_d [ p_d (1 - fr) ] + P_reject * pL      (accepted wrong answers fail)
    Break-even on work (perfect verifier, fr = fa = 0):  rs + rv < E[p_small]
    """
    w = {"easy": cfg.frac_easy, "hard": 1.0 - cfg.frac_easy}
    p = {"easy": cfg.p_small_easy, "hard": cfg.p_small_hard}
    fa, fr, pL = cfg.verifier_false_accept, cfg.verifier_false_reject, cfg.p_large
    p_rej = sum(w[d] * (p[d] * fr + (1 - p[d]) * (1 - fa)) for d in w)
    p_ok_small = sum(w[d] * p[d] * (1 - fr) for d in w)
    work = cfg.small_cost_ratio + cfg.verify_cost_ratio + p_rej
    succ = p_ok_small + p_rej * pL
    return {
        "p_reject": p_rej,
        "work_ratio": work,                       # cascade work / large-only work
        "success_cascade": succ,
        "success_large": pL,
        "work_per_success_ratio": (work / succ) / (1.0 / pL),
    }


# ----------------------------------------------------------------- benchmark suite
SCENARIOS: dict[str, Scenario] = {
    "S1_moderate": Scenario("S1_moderate", load_mean=0.50, load_amp=0.25, t_amb=20.0,
                            description="Moderate, varying load; mild ambient"),
    "S2_high_load": Scenario("S2_high_load", load_mean=0.75, load_amp=0.10, t_amb=20.0,
                             description="High sustained load; mild ambient"),
    "S3_hot": Scenario("S3_hot", load_mean=0.50, load_amp=0.25, t_amb=35.0,
                       description="Moderate load; hot ambient (chiller-dominated)"),
    "S4_cool": Scenario("S4_cool", load_mean=0.50, load_amp=0.25, t_amb=8.0,
                        description="Moderate load; cool ambient (free-cooling-dominated)"),
    "S5_memory_heavy": Scenario("S5_memory_heavy", load_mean=0.50, load_amp=0.25, t_amb=20.0,
                                param_overrides={"frac_memory": 0.75},
                                description="75% memory-bound jobs"),
    "S6_degraded_cooling": Scenario("S6_degraded_cooling", load_mean=0.65, load_amp=0.15, t_amb=28.0,
                                    param_overrides={"r_conv_ref": 0.030, "r_cond": 0.045},
                                    description="Thermal stress: fouled cold plates, warm ambient, high load"),
}
