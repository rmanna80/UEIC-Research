# 17 · Thermal capacity budgets and thermal-aware scheduling (Stage 5)

**Status:** implemented and tested (`ueic/scheduling/`, `tests/test_stage56_facility.py`). E018 is pre-registered and run in simulation; results are in §8.

## 1. Problem

A scheduler that sees only free GPUs and queue lengths can put a long, hot job where the coolant is already warm. Examples:
* the second plate of a series pair;
* a node at the far end of the manifold;
* a heterogeneous card with worse conduction.

The hardware then throttles, and the job runs late. Thermal-aware scheduling asks: *how much more heat can this GPU, and the GPUs sharing its coolant, absorb over the job's duration?*

## 2. Thermal capacity budget, from first principles

Each GPU's junction is a lumped node: heat capacity C (J/K), resistance R to its coolant inlet (K/W), inlet temperature T_in:

C dT/dt = P − (T − T_in)/R.

With constant power the solution is exponential, with time constant τ = RC, toward T_ss = T_in + R P:

T(t) = T_ss + (T₀ − T_ss) e^(−t/τ).

*Budget.* Ask what extra constant power ΔP keeps T(H) ≤ T_lim at the end of a horizon H. The temperature rises monotonically, so the end is the hottest point. Solving T(H) = T_lim:

ΔP_max(H) = [ (T_lim − T₀ e^(−H/τ)) / (1 − e^(−H/τ)) − T_in ] / R − P     (W)

The energy budget is E(H) = ΔP_max(H)·H (J). Two limits explain the physics:
* **Short horizon** (H ≪ τ): ΔP_max ≈ C(T_lim − T₀)/H. Only stored heat matters: the chip's heat capacity soaks up a burst.
* **Long horizon** (H ≫ τ): ΔP_max → (T_lim − T_in)/R − P. Only rejection matters: the steady headroom.

Neither the heat-capacity figure alone nor the steady headroom alone is the budget. Which one binds depends on the job's length relative to τ (~25 s per chip here; minutes for loops). The formula is checked against the exact integrator to 1e-6 K (test).

**Shared cooling.** In a series cold-plate chain, adding power p upstream raises every downstream inlet by p/(ṁ c_p). A placement's budget is therefore evaluated on *all affected GPUs*, with their shifted inlets:

credit = min over affected a of [ΔP_max,a(H; T_in,a + shift_a) − p_a] / P_ref.

credit ≥ 0 means no affected GPU is predicted to reach the effective limit T_lim − margin within H. Uncertainty is handled by that margin (2 K), stated rather than estimated.

**Admission** (`thermal_admission.py`, a stated rule):
1. Start the job if a placement has credit ≥ 0 at full clock.
2. Otherwise, start it at the highest reduced clock (0.9…0.6) that has credit ≥ 0 and still meets the deadline.
3. Otherwise, hold it if it can wait 60 s and still finish.
4. Otherwise, start it on the best placement and let the hardware throttle protect the chip.

## 3. Policies compared

| Policy | Rule |
|---|---|
| round_robin | Next eligible GPUs after a rotating pointer |
| least_loaded | Node with the most free GPUs |
| power_aware | Rack with the most power headroom, then the lowest-power node and GPUs |
| temperature_aware | Coolest node, then the coolest GPUs |
| thermal_credit | Placement with the largest credit; lower clock or hold by the admission rule |
| thermal_placement | Ablation: thermal_credit's placement at full clock, never holding |

All policies share EDF queue order with backfilling, and the same hardware throttle and power caps. Multi-GPU jobs stay inside one node when possible.

## 4. Also in `ueic/scheduling/` (Part 8)

* `phase_scheduler.py`: the clock per phase minimising energy per unit of work under a throughput floor. Memory-bound phases get lower clocks.
* `model_router.py`: routes among models using **measured** accuracy (Wilson lower bound) and energy only. It refuses models with no measured accuracy for the task. It rescales measured energy by the predicted leakage ratio at the current temperature and the plant's cooling overhead, and drops models whose peak power exceeds the electrical headroom. This shows how the energy-optimal route moves with temperature, cooling and caps (tested). Precision variants are just more measured profiles.
* `workload_optimizer.py`: the highest clock within a power budget, and deadline-aware EDF batching.

## 5. Files and data flow

```
FacilitySim._schedule ─ FacilityView (copies of T, T_in, R, C, P, busy, memory, topology)
        └─ scheduler.select(job, view, t) ─ thermal_capacity.power_budget ─ thermal_credits.placement_credit
                                           └─ thermal_admission.admit ─► (gpus, clock) | hold
```

## 6. Run and test

```bash
python -m pytest tests/test_stage56_facility.py
python -m ueic run experiments/E018_thermal_scheduling.json --workers 2
```

## 7. Assumptions and failure modes

* The budget uses each GPU's current power and folds leakage in at the current temperature. Near the limit, leakage grows, so budgets are slightly optimistic. The margin covers this.
* The duration estimate is the remaining work at full clock. Badly wrong durations make H wrong (capped at 600 s).
* Holding a job trades waiting time for thermal slack. With tight deadlines, holds turn into late jobs. E018's H3 checks this.

## 8. Results (E018)

Filled in after the run; see `PHASE_REPORT.md`.
