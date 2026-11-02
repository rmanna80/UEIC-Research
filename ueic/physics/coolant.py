"""Coolant transport: plug-flow delay lines (Stage 1 component).

A pipe of internal volume V_pipe carrying volume flow V_dot delivers water that entered
tau = V_pipe / V_dot seconds earlier (plug flow, no axial mixing, adiabatic walls) [A/E].
With varying flow the delay is defined by volume, not time: the outlet sees the fluid parcel
whose cumulative volume equals the current cumulative volume minus V_pipe.

Energy: the outlet enthalpy flow is the delayed inlet enthalpy flow; the energy held in the pipe
is rho*c_p*integral(T dV) over the parcels inside it. ``DelayLine.stored_energy`` returns it so
balances can be checked (inflow - outflow = change in storage).

Limits: no dispersion (real pipes smear temperature fronts), no heat loss to the room, constant
water properties. Use the well-mixed tank (``thermal_storage``) to represent mixing volumes.
"""
from __future__ import annotations

from collections import deque


class DelayLine:
    """Volume-based plug-flow delay for a scalar temperature signal."""

    def __init__(self, volume_m3: float, T_init: float, rho: float = 997.0, cp: float = 4180.0):
        if volume_m3 < 0:
            raise ValueError("pipe volume must be >= 0")
        self.V = float(volume_m3)
        self.rho, self.cp = rho, cp
        self._parcels: deque[list[float]] = deque()      # [volume m^3, temperature degC], inlet at right
        if self.V > 0:
            self._parcels.append([self.V, float(T_init)])

    def step(self, T_in: float, V_dot: float, dt: float) -> float:
        """Push V_dot*dt of water at T_in; return the volume-weighted outlet temperature over the step."""
        if V_dot < 0 or dt <= 0:
            raise ValueError("need V_dot >= 0 and dt > 0")
        dV = V_dot * dt
        if self.V == 0 or dV == 0:
            return float(T_in) if self.V == 0 else (self._parcels[0][1] if self._parcels else float(T_in))
        self._parcels.append([dV, float(T_in)])
        out_v, out_vt = 0.0, 0.0
        while out_v < dV - 1e-15:
            v, T = self._parcels[0]
            take = min(v, dV - out_v)
            out_v += take
            out_vt += take * T
            if take >= v - 1e-15:
                self._parcels.popleft()
            else:
                self._parcels[0][0] = v - take
        return out_vt / out_v

    def stored_energy(self, T_ref: float = 0.0) -> float:
        """rho*c_p*sum(V_i*(T_i - T_ref)) of the water inside the pipe, J."""
        return self.rho * self.cp * sum(v * (T - T_ref) for v, T in self._parcels)

    def delay_s(self, V_dot: float) -> float:
        return float("inf") if V_dot <= 0 else self.V / V_dot
