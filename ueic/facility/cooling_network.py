"""Shared coolant network: pump, parallel node branches with unequal resistance, valves, series plates.

Branch law (each node is one branch of the facility manifold):
    dp = dp_ref * h_n * (q_n / (q_d,n * v_n))^2
with q_d,n the node's design flow (plates per branch x branches x design flow per plate is not used:
each *plate* gets ``flow_design_lpm`` at q_d,n), h_n the node's hydraulic scale and v_n in (0, 1] its
valve opening. All branches see the same dp, so for a total pump flow F:
    sqrt(dp / dp_ref) = F / sum_n (q_d,n v_n / sqrt(h_n)),     q_n = q_d,n v_n sqrt(dp / (dp_ref h_n))
Pump electrical power = dp * F / eta_pump (all of it heats the coolant, as in the single-node model).
With h = v = 1 and F = sum q_d this reduces to the single-node design point (dp = dp_ref).

Valve modes: "equal" (all open) or "heat_proportional" (targets q_n proportional to max(Q_n, q_floor)
and opens the valves accordingly; the most demanding branch is fully open). Valves change flow
*distribution*; total flow is set by the pump.
"""
from __future__ import annotations

import numpy as np

LPM_TO_M3S = 1.0 / 60e3


def distribute(F_lpm: float, q_design_lpm: np.ndarray, h: np.ndarray, valve: np.ndarray, dp_ref: float):
    """Branch flows (lpm) and manifold pressure drop (Pa)."""
    w = q_design_lpm * valve / np.sqrt(h)
    root = F_lpm / w.sum()
    q = w * root
    return q, dp_ref * root ** 2


def pump_power(F_lpm: float, dp: float, eta_pump: float) -> float:
    return dp * F_lpm * LPM_TO_M3S / eta_pump


def heat_proportional_valves(Q_node: np.ndarray, q_design_lpm: np.ndarray, h: np.ndarray,
                             floor_frac: float = 0.3) -> np.ndarray:
    """Valve openings whose resulting flows are proportional to max(Q_n, floor x mean Q) per design flow."""
    target = np.maximum(Q_node, floor_frac * max(float(np.mean(Q_node)), 1.0))
    v = target / q_design_lpm * np.sqrt(h)
    return np.clip(v / v.max(), 0.05, 1.0)
