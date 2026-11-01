# 16 · Predictive control: thermal futures, safety filter, fallback (Stage 3)

**Status:** implemented and tested (`ueic/control/`, `tests/test_stage3_control.py`). E015 is pre-registered and run; its results are in `RESULTS.md` and `PHASE_REPORT.md`. Everything here is simulation.

## 1. Problem and why it matters

Liquid-cooled AI hardware has two actuators on very different time scales:
* **Clocks** change chip heat within seconds. The RTX 5070's die responded within one or two sensor updates (~1–2 s) in the M001/M002 warm-ups; see docs/15.
* **The coolant plant** changes the supply temperature at its ramp rate. Through a loop's thermal mass that takes minutes.

E010–E014 showed what goes wrong at each extreme:
* A steady-state optimiser that assumes a commanded setpoint has already arrived overheats chips.
* The fix that never credits cooling that has not arrived (`joint_meas`, `joint_lag`) is safe but never moves the coolant on a slow loop, so it gives up capacity.

The predictive controller plans with the cooling's arrival time.

## 2. Architecture

```
Observation ─► MPCPolicy._optimise ── proposal ─► SafetyFilter.validate ── approved action ─► plant
                 │  forecast.py (demand, ambient)          │ own setpoint tracker, telemetry checks,
                 │  futures.py  (supply trajectories)      │ supply upper bound, clock projection
                 └─ exceptions / time budget / infeasible ─┴─► fallback.fallback_action
```

* The **optimiser** proposes; the **safety filter** decides; the **fallback** handles every failure path.
* The filter keeps its own plant-setpoint tracker, built only from actions it approved, and shares no state with the optimiser.
* Policies register as `mpc` and `mpc_robust` in the usual `POLICIES` table (lazily, to avoid an import cycle). The experiment runner, store and analysis therefore work unchanged.

## 3. Equations and variables

**Plant futures** (`futures.trajectories`) use the same equations as the simulator:
* A command issued at t reaches the plant at t + d (`tsup_cmd_delay_s`).
* The plant setpoint moves toward it at no more than r (`tsup_ramp_K_per_min`/60, K/s).
* A well-mixed tank of water mass M follows:
  * plant active (sp < T + q/Ċ): T ← sp + (T − sp)·exp(−h·Ċ/(M c_p));
  * pass-through: T ← T + q·h/(M c_p).
* Over each control step the module reports the peak supply temperature, the mean supply temperature, the mean plant setpoint, and the heat released by the tank, Q_store = M c_p (T_start − T_end)/Δ.
* Predictions match the simulator's equations exactly at 1 s sub-steps (tested).

**Supply upper bound** (`futures.supply_upper_bound`), shared by the MPC's first step and the safety filter. The filter needs only installation ratings to compute it. Over the next interval Δ the supply cannot exceed:
* with a tank: min(T_up − (T_up − T_meas)·e^(−Δ Ċ/(M c_p)), T_meas + q_max Δ/(M c_p), T_up);
* without a tank: min(T_up, T_meas + r Δ).

Here:
* T_up is the highest plant target that can be in force during the interval;
* q_max is every chip at full clock at t_throttle plus the pump at maximum flow;
* the bound is never below the measured supply. Cooling that has not arrived is never credited.

**MPC decision.**

| Element | Definition |
|---|---|
| Candidates | Supply command c on the controller grid × flow f, held over the horizon (one move block) |
| Demand | D_k from the forecast; backlog B_k per class |
| Effective demand | D_eff = D_k + B_k/`backlog_clear_s` |
| Per step k, every clock pair | Utilisation u = D_eff,c/(N s_c^β_c) + D_eff,m/(N s_m^β_m). Chip temperatures and powers from the steady chip model at the step's peak supply. P_IT = N·(u_c P_c + u_m P_m + (1 − u) P_idle). Plant power at the step's mean plant setpoint with heat P_IT + P_pump + Q_store |
| Chosen pair | The cheapest pair with u ≤ u_max and all temperatures ≤ t_target. Otherwise the safe pair with the lowest u, serving D_eff·u_max/u. If no pair is safe, the candidate is rejected |
| Backlog | B_{k+1} = max(0, B_k + D_k Δ − served_k) |
| Objective | Σ_k [P_grid,k Δ + w·B_{k+1} Δ] + w·B_H·`backlog_clear_s` |
| Weight w | `mpc_backlog_weight`: an explicit price of queued work in W per work-second (class G, default 20) |
| Horizon | `mpc_horizon_steps` (15 × 60 s) |

The tank's warming is predicted with q_max (conservative). The first step uses the filter's bound, so proposals pass the filter unless it sees something the optimiser did not.

**Robust MPC** (`mpc_robust`) requires each candidate's supply trajectory to be safe under the nominal loop model and with loop mass ×0.5 and ×2 and ramp ×0.5 and ×2 (hottest of the five). It also keeps an extra `mpc_robust_margin_K` below t_target. This is scenario robustness over a stated set, not a probabilistic guarantee. Chance-constrained control is not implemented, because no calibrated probability model of the uncertainties exists yet.

**Forecasts** (`forecast.py`):
* 0: persistence of the recent-arrival estimate.
* 1: the scenario's load function, including scheduled bursts, with optional bias and lognormal noise drawn from seeded generators.
* 2: as 1 but blind to bursts.

These are synthetic forecast-quality levels, not a forecasting model.

**Safety filter** (`safety_filter.py`), in order:
1. With a dynamic plant, the supply telemetry must be finite, and junction telemetry, if present, must be finite. Otherwise it falls back.
2. Out-of-range actions are clipped.
3. Steady junction temperatures at the proposed clocks and flow must be ≤ t_target − `safety_margin_K` at the supply bound.

Otherwise it lowers clocks to the highest-throughput safe pair (then raises flow), choosing the lowest clocks among equally useful pairs. If none is safe, it falls back.

**Fallback** (`fallback.py`): maximum flow, setpoint `t_sup_min`, and the highest-throughput clocks that are safe at the measured supply (or at `t_sup_max` when telemetry is missing). It is safe and simple, not efficient.

## 4. Simulator support added for Stage 3 (all opt-in; legacy runs reproduce bitwise)

* Scenario bursts: ((t_start, duration, extra load), …).
* Ambient profiles: ((t, T_amb), …).
* Setpoint command delay (`tsup_cmd_delay_s`).
* Per-run counts of fallback and filtered decisions (`decisions_fallback`, `decisions_filtered`).

## 5. How to run and test

```bash
python -m pytest tests/test_stage3_control.py
python -m ueic run experiments/E015_thermal_futures.json --workers 2
python -m ueic report && python -m ueic dashboard
```

The tests cover:
* trajectories against the simulator's equations;
* setpoint tracking with delay and ramp;
* the supply bound;
* the filter approving safe actions;
* the filter lowering clocks when cold water has not arrived;
* fallback on missing or invalid telemetry;
* fallback on injected solver exceptions and time-budget overruns, with safety kept;
* an instant-plant run;
* the robust scenario set;
* a regression of the pre-cooling behaviour seen in exploratory runs (disclosed in E015).

## 6. Assumptions and failure modes

* The controller knows the loop's mass, ramp and delay. E014 and E016 address model error; E015 does not.
* The steady chip model is shared by the optimiser and the filter. A shared-model error is not caught by the filter, and the simulated hardware throttle remains the last line of defence.
* The backlog price w trades service against energy. A different w gives a different controller. E015 uses the registry default without tuning.
* Holding the command over the horizon (one move block) cannot plan "cool now, warm later" within a horizon. Re-planning every interval partly compensates.
* Decision time is ~10–40 ms per decision here. The time budget (`mpc_time_budget_s`) turns slow decisions into fallbacks.

## 7. Interpreting results

E015 compares the MPC with the measured-state rule, steady-state joint control and independent control under bursts, rising ambient, overload and fouling, across loop inertia, command delay and forecast quality. Its hypotheses were fixed before it ran.
* A predictive benefit counts only if it clears the pre-registered thresholds.
* A failure is reported as a failure.
* A predictive benefit in simulation is not evidence that it would hold on a real loop. That needs the hardware-in-the-loop work in Stage 9.
