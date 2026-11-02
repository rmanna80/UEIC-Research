# 20 · Heat reuse and cooling economics (Stage 7)

**Status:** physics components implemented and tested in Stage 1 (`physics/dry_cooler.py`, `chiller.py`, `heat_pump.py`, `heat_reuse.py`, `thermal_storage.py`, `hydraulics.py`). E021 is pre-registered and complete in simulation (§7: H2, H5, H6 and H7 supported; H1, H3 and H4 not). All parameters are class F placeholders.

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

## 7. Results (E021, simulated)

Record `E021-20261101T212421-8b3d80`: 480 runs, 0 failed. It supersedes an aborted first attempt (`…202413-b92693`, stopped by an infrastructure time limit, kept as failed). The record was resumed twice under the checks in docs/24 §1. All runs share the registered core hash `f0274eb299ad`, and before each resumption completed runs were re-simulated and matched bit for bit (3 distinct runs, 4 checks).

| Hypothesis | Verdict | What happened |
|---|---|---|
| H1 the NTU plant moves the no-floor optimum ≥ 1 K warmer | **not supported, opposite sign** | NTU minus legacy mean supply: registry −0.8 / −1.9 / −1.9 K at 8 / 20 / 30 °C; RTX 5070 world −0.8 / −1.3 / −1.4 K |
| H2 but stays below 35 °C at 8 and 20 °C | supported | 12.2 and 23.1 °C (registry), 12.2 and 23.7 °C (RTX). At 8 °C the supply sat on its 12 °C lower limit |
| H3 the shift is larger in the RTX world | not supported | 8 °C: −0.8 vs −0.8 K; 20 °C: −1.3 vs −1.9 K (the shift is colder, and smaller in the RTX world) |
| H4 the 40 °C floor is cheaper with the NTU plant | not supported | NTU vs legacy cost of the 40 °C floor: registry 12.77 vs 12.86% (8 °C), 7.81 vs 7.70% (20 °C); RTX 4.41 vs 4.48%, 2.71 vs 2.74%. Differences ≤ 0.11 percentage points, one in the wrong direction |
| H5 supply orders by fan cost (0.04 ≥ 0.02 ≥ 0.01) | supported | e.g. RTX at 20 °C: 24.6 / 23.7 / 23.0 °C. The spread is ≤ 1.6 K |
| H6 the 44 °C floor costs < 0.10 kWh_el per kWh_th of reusable heat (RTX world) | supported | NTU 0.054 / 0.037, legacy 0.055 / 0.038 at 8 / 20 °C |
| H7 and is cheaper than a heat pump | supported | the heat pump needs 0.226 / 0.154 (NTU) and 0.221 / 0.147 (legacy) kWh_el per kWh_th delivered, about 4× more |

**Why H1 failed (descriptive, not a new hypothesis).**
* The legacy plant's optimum was set by its fixed 5 K dry-cooler approach, not by its fan law. Without a floor, the legacy plant ran at exactly ambient + 5 K (13, 25 and 35 °C), the coldest supply it can make without the chiller.
* The NTU dry cooler can reach a 3–4 K approach at modest fan speed. Mean fan energy over 4 h was 0.01–0.06 kWh, against 0.12–0.15 kWh for the legacy plant's fixed 2% ratio.
* So the optimiser cooled the chips further and saved leakage.
* The pre-registration's back-of-envelope estimate (optimum approach ~6–8 K, disclosed in the spec) was wrong for these class F parameters.

**What the floor costs is almost entirely chip leakage.**
* The chiller did no work in any of the 480 runs.
* Fan energy with the NTU plant was below 1% of grid energy.
* Raising the supply floor therefore costs IT energy (higher junction temperature, more leakage) and almost nothing else. That cost was about 3× higher in the registry world (44 °C floor: +10–16% energy per success at 8–20 °C) than in the RTX 5070 world (+3.4–5.4%).
* A 35 °C floor gave no reusable heat at all (return ~39 °C) and cost up to 9.9% (registry, 8 °C).

**Break-even heat price** (kWh_el per kWh_th, i.e. the heat price as a fraction of the electricity price above which the floor pays):

| World, 44 °C floor | 8 °C | 20 °C | 30 °C |
|---|---|---|---|
| RTX 5070, NTU | 0.054 | 0.037 | 0.020 |
| Registry, NTU | 0.143 | 0.100 | 0.054 |

At 30 °C ambient, the heat pump's COP hits its cap of 10 (0.100 kWh_el per kWh_th), so the heat-pump comparison there says nothing beyond the cap.

**Limits.**
* Everything here is simulated with class F plant parameters. The leakage slope in the RTX world rests on a 4 K window (M003 is pending).
* Reusable heat assumes the heat is fully demanded.
* The two sides of the heat-pump comparison are counted differently: the heat pump's denominator includes its own compressor work, and the warm loop's extra electricity becomes heat that is itself counted as reusable.
* The comparison uses the run's mean return temperature.
