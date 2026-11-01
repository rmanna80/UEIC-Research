"""Choosing the next calibration experiment (Stage 2).

Given a model y = f(theta; design) with Gaussian noise sigma, candidate designs, a safety predicate and a
cost (minutes of operator time), the planner ranks candidates by expected information about the parameters
of interest per unit cost:

  information   I(design) = -log det of the Cramer-Rao covariance of the parameters of interest
                (D-optimality on that subset), from the Fisher information J^T J / sigma^2 at the current
                estimate theta (local; a Bayesian version would average over the prior)
  gain          I(design) - I(current evidence); candidates that are unsafe are dropped, not penalised
  score         gain / cost

The planner only *recommends*. Physical experiments run when an operator chooses to run them; nothing
here touches hardware.

``leakage_window_designs`` instantiates it for the open question of M001-M003: which temperature window
(by fan speed) best identifies the leakage coefficient kappa at one locked clock.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

from .identifiability import fisher_information, numerical_jacobian


@dataclass
class Candidate:
    name: str
    design: dict
    cost_min: float
    safe: bool = True
    notes: list = field(default_factory=list)


def information(model: Callable[[np.ndarray, dict], np.ndarray], theta, design: dict, sigma: float,
                interest: Sequence[int]) -> float:
    J = numerical_jacobian(lambda th: model(th, design), theta)
    F = fisher_information(J, sigma)
    try:
        cov = np.linalg.inv(F)
    except np.linalg.LinAlgError:
        return -np.inf
    sub = cov[np.ix_(interest, interest)]
    sign, logdet = np.linalg.slogdet(sub)
    return -logdet if sign > 0 else -np.inf


def rank(model, theta, candidates: Sequence[Candidate], sigma: float, interest: Sequence[int],
         baseline: float | None = None) -> list[dict]:
    out = []
    for c in candidates:
        if not c.safe:
            out.append({"name": c.name, "safe": False, "score": -np.inf, "gain": None, "cost_min": c.cost_min,
                        "notes": c.notes + ["excluded: unsafe"]})
            continue
        I = information(model, theta, c.design, sigma, interest)
        gain = I - (baseline if baseline is not None else 0.0)
        out.append({"name": c.name, "safe": True, "information": I, "gain": gain, "cost_min": c.cost_min,
                    "score": gain / max(c.cost_min, 1e-9), "notes": c.notes})
    return sorted(out, key=lambda r: -r["score"])


def _leak_model(theta, design):
    c, L, kappa = theta
    T = np.asarray(design["T_levels"], dtype=float)
    return c + L * np.exp(kappa * (T - 60.0))


def leakage_window_designs(P_mean: float = 168.0, leak_frac: float = 0.2, kappa: float = 0.02, sigma_W: float = 0.8,
                           T_max_safe: float = 83.0) -> dict:
    """Rank candidate fan-sweep designs for identifying kappa (one independent level per fan speed).

    Temperature levels per design are assumptions to be replaced by a measured fan-speed response; the
    current warm-ups (48-57 C and 63-64 C windows) are the baseline evidence."""
    theta = np.array([P_mean * (1 - leak_frac), P_mean * leak_frac, kappa])
    base = {"T_levels": list(range(48, 58))}
    designs = {
        "M001-like warm-up (48-57 C, auto fan)": (base, 25),
        "M003 plan, 5 fan speeds (~50-70 C)": ({"T_levels": [50, 55, 60, 65, 70]}, 55),
        "M003 plan + 2 repeats (~50-70 C)": ({"T_levels": [50, 55, 60, 65, 70] * 3}, 120),
        "aggressive, fan to 20% (~50-85 C)": ({"T_levels": [50, 58, 66, 74, 85]}, 55),
        "narrow high (60-66 C)": ({"T_levels": [60, 62, 64, 66]}, 45),
    }
    I0 = information(_leak_model, theta, base, sigma_W, [2])
    cands = [Candidate(n, d, cost, safe=max(d["T_levels"]) <= T_max_safe,
                       notes=[f"T levels {min(d['T_levels'])}-{max(d['T_levels'])} C (assumed)"]) for n, (d, cost) in designs.items()]
    ranked = rank(_leak_model, theta, cands, sigma_W, [2], baseline=I0)
    for r in ranked:
        if r["safe"]:
            d = designs[r["name"]][0]
            J = numerical_jacobian(lambda th: _leak_model(th, d), theta)
            cov = np.linalg.pinv(fisher_information(J, sigma_W))
            r["kappa_rel_se"] = float(np.sqrt(cov[2, 2]) / kappa)
    return {"theta": theta.tolist(), "baseline_information": I0, "ranking": ranked,
            "assumptions": "levels are assumed steady temperatures, one independent sample each; sigma = 0.8 W "
                           "(M001 residual); kappa = 0.02 /K and 20% leakage at mid-window are the E009 matched values"}
