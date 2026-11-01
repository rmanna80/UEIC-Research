"""Discrete job workload for the facility simulator (synthetic; seeded).

Arrivals: Poisson with rate lambda(t) = lambda_0 (1 + amp sin(2 pi t / period)) plus scheduled bursts
(extra rate over a window), sampled by thinning. Each job: GPUs n in {1, 2, 4} (probabilities p_n), work
per GPU W ~ lognormal (mean ``work_mean_s`` full-clock seconds, log-sd ``work_sigma``), memory per GPU
~ U(mem_lo, mem_hi) GB, class memory-bound with probability ``frac_memory`` (else compute-bound), and a
deadline = arrival + slack x W + 60 s with slack ~ U(slack_lo, slack_hi). lambda_0 is chosen so that the
offered load (GPU-seconds of full-clock work per second) equals ``load`` x number of GPUs.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Job:
    id: int
    arrival: float
    n_gpus: int
    work: float              # full-clock seconds per GPU
    mem_GB: float
    memory_bound: bool
    deadline: float
    remaining: float = 0.0
    gpus: list = field(default_factory=list)
    s_req: float = 1.0
    start: float | None = None
    finish: float | None = None

    def __post_init__(self):
        self.remaining = self.work


@dataclass
class JobSpec:
    load: float = 0.7
    work_mean_s: float = 300.0
    work_sigma: float = 0.6
    p_n: tuple = (0.6, 0.3, 0.1)          # for 1, 2, 4 GPUs
    mem_lo: float = 10.0
    mem_hi: float = 70.0
    frac_memory: float = 0.3
    slack_lo: float = 1.5
    slack_hi: float = 4.0
    amp: float = 0.0
    period_s: float = 3600.0
    bursts: tuple = ()                     # ((t_start, duration, extra_load), ...)


def generate(spec: JobSpec, n_gpus_total: int, duration_s: float, seed: int) -> list[Job]:
    rng = np.random.default_rng(seed)
    sizes = np.array([1, 2, 4])
    p = np.asarray(spec.p_n, dtype=float) / np.sum(spec.p_n)
    mean_gpu_s = float((sizes * p).sum()) * spec.work_mean_s
    lam0 = spec.load * n_gpus_total / mean_gpu_s
    extra = lambda t: sum(e for (t0, d, e) in spec.bursts if t0 <= t < t0 + d)   # noqa: E731
    lam_max = lam0 * (1 + abs(spec.amp)) + max([e for (_, _, e) in spec.bursts] or [0.0]) * n_gpus_total / mean_gpu_s
    jobs, t, k = [], 0.0, 0
    mu = np.log(spec.work_mean_s) - 0.5 * spec.work_sigma ** 2
    while True:
        t += rng.exponential(1.0 / lam_max)
        if t >= duration_s:
            break
        lam = lam0 * (1 + spec.amp * np.sin(2 * np.pi * t / spec.period_s)) + extra(t) * n_gpus_total / mean_gpu_s
        u = rng.random()
        n = int(rng.choice(sizes, p=p))
        W = float(rng.lognormal(mu, spec.work_sigma))
        mem = float(rng.uniform(spec.mem_lo, spec.mem_hi))
        mb = bool(rng.random() < spec.frac_memory)
        slack = float(rng.uniform(spec.slack_lo, spec.slack_hi))
        if u < lam / lam_max:                       # thinning; draws above are made either way (stable streams)
            jobs.append(Job(k, t, n, W, mem, mb, t + slack * W + 60.0))
            k += 1
    return jobs
