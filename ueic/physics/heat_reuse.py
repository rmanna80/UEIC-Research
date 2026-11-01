"""Heat reuse accounting and value (Stage 1 component; used by E021).

A heat customer (e.g. a district-heating return or building loop) needs Q_demand (W) at
T_req (degC). Waste heat leaves the cooling loop at T_avail with rate Q_avail.

  Direct reuse        if T_avail >= T_req + dt_hx:  Q_used = min(Q_avail, Q_demand), W_hp = 0
  Heat-pump reuse     otherwise: the heat pump (``heat_pump.upgrade``) lifts source heat; it can
                      deliver at most Q_demand, using source heat Q_src = Q_del (1 - 1/COP)
  Displaced heating   the customer would otherwise buy heat; value = price_heat * Q_used

Every result names its boundary. Reused heat is not "negative energy": facility electricity is
unchanged by reuse (except heat-pump electricity, which is added), and the benefit appears as
displaced heat in a separate account. Economic value = price_heat * E_heat_used
- price_el * (E_el_facility + E_el_hp). A lower PUE-like ratio is not used as evidence of benefit.
"""
from __future__ import annotations

import numpy as np

from .heat_pump import upgrade


def reuse(Q_avail, T_avail, Q_demand, T_req, dt_hx: float = 2.0, hp_kwargs: dict | None = None):
    Q_avail, T_avail, Q_demand = (np.asarray(v, dtype=float) for v in (Q_avail, T_avail, Q_demand))
    if np.any(Q_avail < 0) or np.any(Q_demand < 0):
        raise ValueError("heat flows must be >= 0")
    direct = T_avail >= np.asarray(T_req, dtype=float) + dt_hx
    Q_direct = np.where(direct, np.minimum(Q_avail, Q_demand), 0.0)
    hp = upgrade(1.0, T_avail, np.asarray(T_req, dtype=float) + dt_hx, **(hp_kwargs or {}))
    frac_src = 1.0 / np.maximum(hp["Q_delivered"], 1e-12)                       # source share per delivered W
    Q_del_hp = np.where(direct, 0.0, np.minimum(Q_demand, Q_avail / np.maximum(frac_src, 1e-12)))
    Q_src_hp = Q_del_hp * frac_src
    W_hp = Q_del_hp - Q_src_hp
    return {"Q_used": Q_direct + Q_del_hp, "Q_src": Q_direct + Q_src_hp, "W_hp": W_hp, "direct": direct}


def heat_value(E_heat_used_kWh, E_el_kWh, price_heat, price_el):
    """Net cost (currency) at given prices; positive = cost. Separate from energy accounting."""
    return price_el * np.asarray(E_el_kWh, dtype=float) - price_heat * np.asarray(E_heat_used_kWh, dtype=float)
