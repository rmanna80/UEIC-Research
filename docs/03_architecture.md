# 03 · System architecture

## 1. Physical system modelled in Phase 1

```
            ┌─────────────────────── control (every 60 s) ───────────────────────┐
            │  demand estimate (EWMA + backlog)   measured chip power   ambient   │
            │                 │                          │                │       │
            │        ┌────────▼─────────┐       ┌────────▼────────┐       │       │
            │        │ compute decision │       │ cooling decision│◄──────┘       │
            │        │ clock per class  │       │ T_supply, flow  │               │
            │        └────────┬─────────┘       └────────┬────────┘               │
            │   (joint: one optimiser over both, using the steady-state twin)     │
            └─────────────────┼──────────────────────────┼────────────────────────┘
                              ▼                          ▼
 tasks ─► FCFS queue ─► 8 accelerators ── heat ──► cold plates ──► coolant loop ──► dry cooler ──► trim chiller ──► ambient
                     (DVFS, leakage(T))   (RC per chip)   (R_cond+R_conv(flow)+caloric)   (fans)       (COP = η_II·Carnot)
                              ▲                                     │
                    hardware throttle at 85 °C               pump (dP ∝ flow^m)
                    (independent of controller)
```

Every equation, with its evidence class, is listed in the docstring of `ueic/physics.py`. The parts are:

| Component | Model | Validated by |
|---|---|---|
| Accelerator power | `P = P_dyn,max·a·s·(V/Vmax)² + P_leak,ref·(V/Vmax)·e^{κ(T−T_ref)} + P_static` | `test_dynamic_power_scales_as_s_v_squared`, monotonicity |
| Junction temperature | Lumped RC, exact exponential integrator (unconditionally stable, energy-exact) | `test_thermal_step_matches_analytic_solution`, `..._conserves_energy_exactly` |
| Leakage feedback | Steady state by monotone Newton on a concave residual; analytic runaway condition | `test_steady_temperature_matches_root_finder`, `test_thermal_runaway_boundary_is_detected` |
| Cold plate | `R_total = R_cond + R_conv,ref·f^(−n) + 1/(2·ṁ·c_p)` | hand calculation |
| Pump | `P = dP_ref·f^m·V̇/η` | `test_pump_power_hand_calculation_and_scaling` |
| Plant | Dry cooler to `T_amb + approach`; chiller trims the rest; fans on all rejected heat | `test_free_cooling_regimes`, `test_chiller_cop_never_exceeds_carnot` |
| Facility energy | `E_grid = E_IT/η_conv + E_pump + E_fan + E_chiller`; conservation residual checked every run | `test_energy_balance_closes_for_every_policy` |
| Workload | Non-homogeneous Poisson arrivals, lognormal sizes, compute- vs memory-bound classes (`throughput ∝ s^β`) | `test_work_is_conserved...` |
| Routing | Small model + verifier, escalate on reject | `test_simulated_escalation_rate_and_work_match_analytic` |
| Digital twin | Steady-state mean-field model sharing the physics module | `test_simulated_steady_state_matches_twin_prediction` |

## 2. Software architecture

```
ueic/
  params.py      parameter registry (value, unit, evidence class, source, sensitivity range) + validation
  physics.py     power, thermal, hydraulic, plant, exergy, Landauer — pure, vectorised
  workload.py    scenarios, task generation, routing analytic expectations
  twin.py        steady-state digital twin used by controllers
  policies.py    fixed / compute_only / cooling_only / independent / joint
  sim.py         time-stepped engine + energy accounting + hardware protection
  store.py       append-only SQLite store, hash chain, corrections, exports, bundles
  experiment.py  spec → cells → parallel runs → store
  analysis.py    paired statistics
  results.py     structured results + mechanical hypothesis verdicts from the store
  api.py         Phase 2 FastAPI service (127.0.0.1) over the store and physics; validated experiment POST
  telemetry.py   Phase 4 read-only NVML logger (no setter calls; enforced by a test)
  calibrate.py   Phase 4 calibration sessions, fits with standard errors, ingestion, calibrated specs
  report.py      RESULTS.md + figures from the store
  dashboard.py   self-contained HTML dashboard from the store
  __main__.py    CLI
web/             Phase 2 lab: index.html, lab.js (ES modules), lab.css, vendor/three (Three.js r185.1, MIT)
tests/           91 tests
experiments/     pre-registered specs (JSON) + generator
results/         ueic.sqlite, time series (gzip CSV), figures, exports, dashboard.html
docs/            this documentation set
```

Data flow: `spec.json → register (frozen) → expand cells → simulate (worker processes) → store (main process only) → analysis → report/dashboard`.

## 3. Decisions and the alternatives considered

| Decision | Alternatives | Why this choice for Phase 1 |
|---|---|---|
| **Lumped RC per chip** for thermal | 2-D/3-D conduction grid (HotSpot-style); CFD | The charter says to start simple and validate analytically. A lumped model has an exact solution to test against. Spatial hot spots matter for Phase 5 (chip floorplan), not for loop-level setpoint decisions. Upgrade path: replace `thermal_step` and `r_total` without touching the rest. |
| **Quasi-steady plant** (no loop thermal mass) | Dynamic loop with tank capacitance and setpoint lag | Keeps the energy balance exact and simple. It makes setpoint changes look instantaneous, which favours aggressive controllers. Listed as a limitation; first candidate upgrade. |
| **Grid-search MPC on a steady-state twin** | Continuous NLP (SciPy SLSQP), dynamic MPC over a horizon, reinforcement learning | The grid search is exhaustive (no local minima), cheap (~1 ms per decision) and transparent. The charter puts RL after a stable baseline exists, and gradient NLP over discrete clocks adds failure modes without clear benefit at this size. |
| **Time-stepped simulation, dt = 1 s** | Pure discrete-event | The thermal coupling is continuous. The exact integrator makes dt a resolution choice, not a stability one (checked in E004). |
| **SQLite + gzip CSV** | PostgreSQL; Parquet | Zero-install, single file, works on Windows, enforces immutability with triggers. PostgreSQL becomes worthwhile for multi-user or hardware-in-the-loop logging. |
| **CLI + static HTML dashboard** | FastAPI + React + Three.js (charter §12) | The charter asks for the smallest scientifically useful system first. A static dashboard generated from the store shows real outputs with no server. The FastAPI/React/Three.js stack is Phase 2, when interactive 3-D and parameter editing need a backend. |
| **Paired seeds + t-intervals** | Unpaired comparisons; bootstrap | Pairing removes workload variance from policy comparisons and gives much tighter intervals at the same compute. Bootstrap adds little at n = 10. |

## 4. Security and data-integrity controls (charter §13)

* Input validation: unknown parameters and out-of-range values are rejected before registration.
* Immutability: SQLite triggers forbid UPDATE/DELETE of finalised runs, metrics, specs, corrections and the research log.
* Tamper evidence: SHA-256 hash chain over every finalised run's content and its time-series file (`python -m ueic verify`). It catches edits even if the triggers are dropped (tested).
* Reproducibility: per-run config hash, code hash, NumPy version and host recorded; bundles contain the code snapshot.
* Hardware control: none exists. Controllers act only on the simulator. Before any physical actuation (Phase 4+), controllers must run read-only or in shadow mode, behind independent hardware protection. That protection is modelled in `sim.py` as a separate layer the policy cannot override.

## 5. Phase 3 plant model (dynamic loop)

With `loop_mass_kg > 0`, a well-mixed supply tank of that water mass sits between the plant and the chips. It is updated with its exact first-order solution: `M c_p dT/dt = ṁ c_p (T_out − T)`. The plant outlet setpoint moves toward the controller's command at most `tsup_ramp_K_per_min`. When the setpoint is below the return temperature the plant holds its outlet there and removes `Q = Q_in − M c_p ΔT/Δt`. Otherwise it passes water through without heating it, and the tank accumulates the heat. Energy closes exactly; the loop-storage term is reported and flagged above 0.5% of grid energy.

With `loop_mass_kg = 0` the original quasi-steady plant runs unchanged. A test confirms that stored E001 results reproduce bitwise.

## 6. Phase 2 decision: no front-end build step

| Decision | Alternative | Why |
|---|---|---|
| Plain ES modules plus vendored Three.js (import map), served by FastAPI | React + TypeScript + bundler (charter suggestion) | No Node toolchain needed on the owner's Windows machine; the lab works offline; about 1,000 lines of front-end code do not justify a build pipeline. Revisit if the UI grows past a few views or needs shared component state. |
| 2-D energy-flow diagram | 3-D energy-flow model (charter model 5) | A flow diagram reads more accurately flat. The numbers come from the same stored accounting either way. |

