# 21 · Grid coordination: power caps, prices, carbon and flexible work (Stage 7)

**Status:**
* Implemented and tested (`ueic/grid/`, the grid features of `ueic/facility/facility_simulator.py`, `tests/test_stage56_facility.py`).
* E022 is pre-registered and run in simulation (§7).
* Tariff and carbon profiles are **illustrative shapes**, not market or grid data.

## 1. Problem

A grid operator may ask a facility to stay under a power cap for a while (demand response). Prices and carbon intensity change through the day. The facility has three levers:
* cap IT power, by lowering clocks;
* defer flexible work;
* use stored cold, so the chiller can stop.

Cooling cannot be switched off instantly, so cooling inertia affects compliance. Energy, cost and emissions are three different quantities: a lower bill is not lower energy.

## 2. Models

| Piece | Model | File |
|---|---|---|
| Cap | Windows (t₀, t₁, cap_W) on facility grid power | `power_cap.py` |
| Enforcement | IT limit = (cap − previous step's non-IT power)·η_conv, then the clock-capping layer. The one-step lag is the energy management system's reaction time | `facility_simulator.py` |
| Compliance | ∫ max(0, P − cap) dt, maximum exceedance, time over the cap, event energy | `power_cap.Compliance` |
| Flexibility | A job is deferrable during a window if deadline − window end ≥ 1.5 × remaining work | `workload_flexibility.py` |
| Storage | A cold reservoir E_s (J of heat it can absorb). Charging: extra chiller duty Q_c at the charging temperature's COP, electricity Q_c/COP, 5% loss. During a cap, stored cold replaces chiller duty: W_ch × (1 − used/Q_ch·dt) | `facility_simulator.py` |
| Price | Time-of-use: 0.10 off-peak, 0.30 from 16:00 to 21:00 (illustrative units) | `pricing.py` |
| Carbon | Flat, or a diurnal shape with a low midday and a high evening (illustrative gCO₂/kWh) | `carbon.py` |

Energy, cost and CO₂ are accumulated separately each step.

## 3. Why storage can raise energy and lower cost

Charging at 12 °C needs a larger temperature lift than running at the supply temperature, so the COP is lower. Each kWh of stored cold also loses 5%. Total energy therefore *rises*. If the charging happens off-peak and the stored cold displaces peak-period chiller power, the bill can still *fall*. E022's H4 tests exactly this separation.

## 4. Run and test

```bash
python -m pytest tests/test_stage56_facility.py -k "grid or cap"
python -m ueic run experiments/E022_grid_coordination.json --workers 2
```

## 5. Assumptions and failure modes

* The storage model has no tank temperatures, stratification or flow limits. It is a heat reservoir with a stated loss. The fan power to reject charging heat is ignored (small).
* Only IT power is capped. If cooling power alone exceeds the cap, compliance fails. That is reported, not hidden.
* The deferral rule uses the job's deadline and remaining work only. It does not know future windows beyond the active one.

## 6. Interpretation

* Compliance numbers describe this simulated EMS.
* Cost and carbon numbers describe how decisions respond to the shape of a signal, not real savings.

## 7. Results (E022, simulated)

Record `E022-20261102T013819-2b1ccf`: 50 runs, 0 failed, one session. Full tables are in `PHASE_REPORT.md`.

| Hypothesis | Verdict |
|---|---|
| H1 cap held | supported. 0.000 kWh above the cap; largest overshoot 2–12 W (one-step EMS lag) |
| H2 deferral keeps on-time | supported. 0.983 vs 0.972 and 0.969 |
| H3 storage adds ≥ 3% event work at 30 °C | **not supported**. +0.7% [−0.8, +2.1]. The null at 20 °C held |
| H4 storage: more energy, less cost | **not supported**. The seed means show less energy (−1.7%) *and* less cost (−3.3%) |
| H5 cap binds uncapped | supported. 1.05 and 1.89 kWh above, every seed |

**What this shows.**
* **H4:** the reasoning of §3 held per seed in 3 of 5 seeds: storage used 0.2–0.9 kWh more. In the other two, plain capping caused a backlog (on-time 0.947 and 0.918), which storage avoided, saving 2.1–3.0 kWh. The mean reflects that backlog, not storage thermodynamics. A fair test needs a store sized to the event's chiller duty (this one received 1.9 kWh_th) and more seeds.
* **Deferral** beat plain capping on energy, cost and on-time fraction at both ambients.
* **Enforcing the cap** cost 0.6–1.7% energy relative to ignoring it.
