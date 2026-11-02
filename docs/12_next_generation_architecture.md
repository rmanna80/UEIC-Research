# 12 · Next-generation architecture: baseline audit and integration plan

**Branch:** `research/ueic-next-generation`, created from `main` at `6096bb4ded46231bd3e91861c50af24cc078990c` on 2026-11-01. All next-generation work happens on this branch; nothing is merged into `main` without explicit authorisation.

This document records what the repository contained at that commit (the baseline) and how the next-generation systems attach to it without changing any recorded result.

## 1. Baseline audit (2026-11-01)

### 1.1 Tests and store

| Check | Result |
|---|---|
| `python -m pytest` | **123 passed, 0 failed** in 80 s. By file: api 6, calibration 47, params 8, phase3 21, physics 14, routing 3, sim 17, store 7. Slowest: bitwise reproduction of stored E001 runs (11 s) |
| `python -m ueic verify` | OK: 5,443 finalised runs, hash chain intact |
| Experiments in the store | 23 experiment records (including superseded and failed): E001–E014, E001C, E011B and M001/M002 calibration records |

There were no failing tests to separate from new problems. Every later stage reruns the full suite, which includes the bitwise E001 reproduction test.

### 1.2 What exists

| Area | Baseline implementation | Evidence |
|---|---|---|
| Accelerator power | `P = P_dyn·a·s·v(s)² + P_static + P_leak_ref·v·exp(κ(T−T_ref))`; v(s) linear, or a voltage floor with a knee (`vf_knee`, fitted to M001) | A (CMOS form) + E/F parameters; β_compute, β_memory and leakage slope measured on one RTX 5070 (M001, M002) |
| Chip thermal | One lumped RC node per accelerator, exact exponential step | A form; F parameters |
| Cold plate | `R = R_cond + R_conv_ref·f^(−n) + 1/(2ṁc_p)` | A + E |
| Loop | Quasi-steady, or one well-mixed tank with a ramp-limited plant setpoint (E006) | A form; F mass and ramp |
| Plant | Dry cooler to `T_amb + 5 K`, trim chiller at a fixed fraction of the Carnot COP, **fan power ∝ heat rejected** | E/F |
| Pump | `Δp = Δp_ref·f^m`, constant efficiency | A + F |
| Conversion | constant `eta_conv` | F |
| Workload | Synthetic Poisson arrivals, lognormal sizes, two classes (compute/memory), optional small-model cascade with verifier | F |
| Controllers | fixed, compute_only, cooling_only, independent, joint (steady-state grid search), joint_robust (one-sided bias correction), joint_lag, joint_fb, joint_meas | — |
| Calibration | Read-only NVML logger; clock sweep, warm-up and fan-sweep protocols; fits with acceptance rules R1–R3; in-run guard | Hardware: one RTX 5070 |
| Store | Append-only SQLite, frozen pre-registered specs, hash chain, corrections, supersession, bundles | — |
| Interfaces | CLI (`python -m ueic …`), FastAPI on 127.0.0.1, static dashboard, Three.js lab (`web/`) | — |

### 1.3 Measured vs assumed

* **Measured on hardware (RTX 5070, one card):**
  * compute clock sensitivity β_c = 0.983 ± 0.009;
  * memory-kernel clock sensitivity −0.056 ± 0.079, transferred as 0 (a bound for LLM decode);
  * power and energy per unit of work at five clocks;
  * leakage temperature slope 0.135 %/K (2.0 GHz) and ≤ 0.124 %/K (2.33 GHz), each over a ~4 K window.
* **Shape transferred, not measured:** the voltage-floor V–f form (class E). NVML does not report voltage.
* **Everything else is a registry value.** Of 68 parameters: 3 class A, 8 class E, 27 class F (placeholders), 30 class G (design choices).
* **M003 attempt 1 (2026-10-27)** produced no measurement. The clock lock was not active (the GPU ran at 2670–2692 MHz at its 250 W limit), and the fan was never changed between steps (47% reported). The fit correctly refused. The data was not pushed; the in-run guard added afterwards now stops such runs within ~30 s.

### 1.4 Known model limitations and bugs (carried into this plan)

1. **Dry-cooler fan power is proportional to heat rejected, independent of approach temperature.** Above the free-cooling limit, warmer water has no facility-side benefit, so E012's warm-water hypotheses could not pass.
2. **joint_lag is myopic.** On slow loops it never changed its setpoint (420 of 420 runs). It stays safe by never crediting cooling that has not arrived, and pays in capacity. There is no controller that plans *when* cooling arrives.
3. **Overload fallback.** joint and independent run every clock at maximum when demand exceeds planned capacity. This wastes 4.5–4.7% when memory-bound work is clock-insensitive (E011B).
4. **Plant and loop structure.**
   * single well-mixed tank;
   * no transport delay, actuator delay or pump curve;
   * constant chiller second-law efficiency (no part-load map);
   * constant conversion efficiency.
5. **Scenarios.**
   * constant ambient within a run;
   * smooth sinusoidal load (no bursts);
   * no power caps, prices or carbon signals.
6. **Single node:** 8 identical accelerators sharing one loop, FCFS dispatch, no placement, no rack or facility constraints.
7. **Synthetic workload and quality model** (class F). No real inference has been measured.
8. **Parameter uncertainty** is a range per parameter for one-at-a-time sweeps (E002). There are no joint distributions, correlations, validity ranges or extrapolation warnings.
9. **Decision-path sensitivity:** joint results move ~0.5% with time step and grid choices (E004).
10. **`code_hash()` covers only top-level package files.** It must cover subpackages once they exist.

### 1.5 Open scientific questions at baseline

* Does a controller that credits arriving cooling (multi-step MPC) recover the capacity the measured-state rule gives up, without losing safety? (`PHASE_REPORT.md`, next step 3)
* With an approach-dependent dry cooler, when, if ever, is warm water the energy optimum, and what does heat reuse change? (E012 limitation)
* How large is the real leakage slope over a wide temperature window? (M003, user-run)
* Under what conditions does joint control add negligible value over independent control? Partly answered: under 0.6% energy with measured leakage (E009); value is in thermal safety (E010–E014).

## 2. Integration principles

1. **No recorded result changes.** Every new physical model is opt-in through a registry parameter whose default reproduces the baseline path exactly. The bitwise E001 reproduction test, and a new test that runs the legacy plant through the new package API, gate every commit.
2. **`ueic.physics` becomes a package without changing behaviour.** `ueic/physics.py` moves verbatim to `ueic/physics/__init__.py`, so `from ueic import physics as ph` and every existing call keep working. New components live in submodules (`dry_cooler.py`, `chiller.py`, `hydraulics.py`, `coolant.py`, `thermal_storage.py`, `heat_reuse.py`, `heat_pump.py`, `power_delivery.py`, `gpu.py`, `thermal.py`). `CORE_MODULES` and `code_hash()` are updated to cover the package (a documented change to the hash *definition*; hashes are provenance labels, not checked against stored runs).
3. **Separation of concerns:**
   * physics: pure, vectorised and unit-documented;
   * models: parameters with uncertainty, identification, validation;
   * control: optimisers that *propose* actions, plus an independent safety filter and fallback;
   * scheduling, inference, facility, grid, reliability and hardware: separate packages behind small interfaces, with mocks for tests.
4. **Experiments stay pre-registered.** New experiments (E015 onward) are written as specs and committed before any cell runs. Exploratory runs are labelled exploratory and kept out of confirmatory claims.
5. **Hardware stays read-only by default.** Any future active control needs an explicit authorisation object, capability checks, limits and restoration (`ueic/hardware/permissions.py`). Experiments that need hardware are registered with status *pending*, never filled with synthetic data.

## 3. Target layout (built incrementally; status in `TASK_LEDGER.md`)

```
ueic/
  physics/            __init__ (legacy, unchanged) + dry_cooler, chiller, hydraulics, coolant,
                      thermal_storage, heat_reuse, heat_pump, power_delivery, gpu, thermal
  models/             parameter_registry, uncertainty, identifiability, model_validation,
                      gpu_power_surface, gpu_performance_surface, workload_characterization,
                      energy_attribution, system_identification, adaptive_twin,
                      parameter_estimator, model_drift, active_experiment_design
  control/            forecast, futures, predictive_mpc, robust_mpc, safety_filter, fallback
  scheduling/         thermal_capacity, thermal_credits, thermal_admission, model_router,
                      phase_scheduler, placement, workload_optimizer
  inference/          adapters/{vllm,sglang,ollama}, request_tracing, workload_generator,
                      quality_evaluation, energy_accounting, latency_metrics
  facility/           node, rack, cluster, cooling_network, power_network, networking,
                      facility_simulator
  grid/               power_cap, pricing, carbon, workload_flexibility
  reliability/        anomaly_detection, fault_injection, sensor_validation,
                      degradation_detection, recovery, safety_monitor
  hardware/           gpu_adapter, telemetry, power_meter, coolant_sensor, flow_sensor,
                      pump_adapter, cooling_controller, hardware_registry, permissions
```

The existing modules (`sim.py`, `twin.py`, `policies.py`, `params.py`, `workload.py`, `store.py`, `experiment.py`, `calibrate.py`, `telemetry.py`, reporting and API) stay where they are. New controllers register in the same `POLICIES` table, so the experiment runner, store and analysis work unchanged.

## 4. Stage order and acceptance criteria

The prompt's dependency order is kept, with one deviation: Stage 3 (predictive control) runs before most of Stage 2. It answers the open question left by E011–E014 and depends only on Stage 1. Stage 2's identification work is then evaluated with both the existing and the new controllers.

| Stage | Acceptance criteria (set before implementation) |
|---|---|
| 0 Audit | Baseline tests recorded; this document; task ledger; branch pushed |
| 1 Physics | Package conversion with legacy outputs bitwise unchanged (E001 reproduction passes). Each new component documents equations, units, assumptions, parameters, provenance and range, and has tests for energy conservation and rejection of non-physical states. The NTU dry cooler reproduces the legacy floor at its design point and gives fan power that falls with approach. Parameter registry with uncertainty, validity ranges and extrapolation warnings |
| 3 Control | Multi-step MPC that credits arriving cooling. An independent safety filter that alone can veto. A fallback exercised by tests for solver exception, timeout, NaN telemetry and infeasibility. E015 pre-registered before running, run, and analysed against its stated criteria |
| 2 Identification | Estimators return uncertainty and diagnostics. Identifiability is checked from the Fisher information. Recovery of known parameters on synthetic data is tested. Application to the RTX 5070 telemetry reports what is and is not identifiable. E016 pre-registered and run in simulation |
| 4–9 | Interfaces, mocks and tests first. Hardware-dependent experiments registered as *pending* with full protocols. Simulation-only parts run where possible |
| 10 | Integrated evaluation and documentation updated only from recorded runs |
