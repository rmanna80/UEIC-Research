# 20 · Heat reuse and cooling economics (Stage 7)

**Status:** physics components implemented and tested in Stage 1 (`physics/dry_cooler.py`, `chiller.py`, `heat_pump.py`, `heat_reuse.py`, `thermal_storage.py`, `hydraulics.py`). E021 is pre-registered and run in simulation (§7). All parameters are class F placeholders.

## 1. Problem

* Warmer coolant does two things: it lets the dry cooler reject heat with less fan power and less chiller work, and it makes the return water hot enough to reuse.
* It also raises chip temperature, and with it leakage power.

Whether warmer water saves energy, and what reusable heat costs, depends on how fan power grows as the water approaches ambient. E012 could not answer this: in the legacy plant, fan power was a fixed fraction of the heat (audit finding).

## 2. Physics (see docs/13 for the full equations)

* **Dry cooler:**
  * crossflow ε-NTU effectiveness, with UA ∝ x^0.6 and fan power ∝ x³ in fan speed x;
  * the lowest fan speed that reaches the required outlet is found by bisection;
  * the chiller trims what the dry cooler cannot reach.
* **Chiller:** COP = η_II·T_evap/(T_cond − T_evap), capped at Carnot, with an EIR-fPLR part-load form (neutral by default).
* **Heat pump:** COP_h = η_II·T_cond/(T_cond − T_evap); delivered heat Q_del = Q_src + W.
* **Heat reuse:**
  * return water at or above t_reuse_min (45 °C) counts as reusable; it is assumed fully demanded, which is an upper bound on its value;
  * below that temperature, a heat pump would have to lift it;
  * heat value and electricity cost are kept in separate accounts. Reused heat is never subtracted from facility electricity.

## 3. The comparison E021 makes

For a supply floor that forces the return water above 45 °C, E021 compares:
* the extra grid electricity, per kWh of reusable heat gained (kWh_el/kWh_th);
* the electricity a heat pump would need to lift the no-floor return water to 47 °C, per kWh delivered.

Warm direct reuse is better than a heat pump in energy terms only if the first number is smaller.

**Break-even heat price.** At electricity price p_el and heat price p_th, the floor pays if p_th > p_el × (kWh_el/kWh_th). This is a price *ratio* statement, not a cost estimate.

## 4. Files, run, test

```bash
python -m pytest tests/test_stage1_physics.py
python -m ueic run experiments/E021_heat_reuse.json --workers 2
```

Analysis: `results.e021` (H1–H7, per-cell ratios and the heat-pump comparison).

## 5. Assumptions and failure modes

* One node, constant ambient per run, no seasonal heat demand, no heat-customer dynamics.
* Fan ratio variants (0.01, 0.02, 0.04 of design heat) are a sensitivity, not a calibration.
* The heat-pump comparison uses the run's *mean* return temperature.

## 6. Interpretation

The results show how the warm-water trade-off depends on heat-rejection physics, on leakage (the two parameter worlds) and on ambient temperature. They are not facility savings.

## 7. Results (E021)

Filled in after the run; see `PHASE_REPORT.md`.
