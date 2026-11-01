"""Thermal storage: well-mixed and stratified (multi-node) water tanks (Stage 1 component).

Well-mixed tank (legacy ``tank_step``, exact):
    M c_p dT/dt = C_dot (T_in - T)          ->  T(t+dt) = T_in + (T - T_in) exp(-C_dot dt / (M c_p))

Stratified tank (n equal, fully mixed layers in series; plug flow enters the first layer):
    (M/n) c_p dT_i/dt = C_dot (T_{i-1} - T_i),  T_0 = T_in
Each layer is advanced with its exact exponential solution, fed with the previous layer's
step-mean outlet held constant over the step. Energy is conserved to round-off; the dynamics are
exact for n = 1 and a first-order approximation in dt for n > 1. n = 1 is the well-mixed tank;
large n approaches a pure delay. Real tanks sit in between (thermocline mixing; class F).

Energy content relative to T_ref: E = sum(M/n * c_p * (T_i - T_ref)).
"""
from __future__ import annotations

import numpy as np


class StratifiedTank:
    def __init__(self, mass_kg: float, n_layers: int, T_init: float, cp: float = 4180.0):
        if mass_kg <= 0 or n_layers < 1:
            raise ValueError("need mass > 0 and at least one layer")
        self.m_layer = mass_kg / n_layers
        self.cp = cp
        self.T = np.full(int(n_layers), float(T_init))

    def step(self, T_in: float, C_dot: float, dt: float) -> float:
        """Advance dt with inflow capacity rate C_dot (W/K) at T_in; return the step-mean outlet temperature."""
        if C_dot < 0 or dt <= 0:
            raise ValueError("need C_dot >= 0 and dt > 0")
        if C_dot == 0:
            return float(self.T[-1])
        mc = self.m_layer * self.cp
        a = np.exp(-C_dot * dt / mc)
        T_feed = float(T_in)
        for i in range(self.T.size):
            T0 = self.T[i]
            T1 = T_feed + (T0 - T_feed) * a
            # outlet heat of this layer over the step = inflow heat - storage change
            out_mean = T_feed - mc * (T1 - T0) / (C_dot * dt)
            self.T[i] = T1
            T_feed = out_mean
        return float(T_feed)

    def energy(self, T_ref: float = 0.0) -> float:
        return float(self.m_layer * self.cp * np.sum(self.T - T_ref))

    @property
    def outlet(self) -> float:
        return float(self.T[-1])
