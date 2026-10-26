# 07 · Phased implementation plan

Each phase has an exit gate. A phase does not start until the previous gate is passed, or until its failure is documented and accepted.

| Phase | Scope | Exit gate | Status |
|---|---|---|---|
| **0 Research & feasibility** | Problem statement, RQs, evaluation criteria, architecture, assumptions register, risks, baseline method, literature matrix | Criteria fixed before results; every simulator number has provenance | **Done** (this package) |
| **1 Working simulation** | Workload, power, thermal, plant models; 5 policies; logging; benchmark; validation tests | Tests pass; energy balance closes; baseline reproducible; ≥2 strategies compared with CIs | **Done**, with a known gap: joint-controller results vary ~0.5% with decision path (E004) |
| **2 Interactive visualisation** | FastAPI service over the store; React dashboard with experiment manager; Three.js models (facility, chip, cold plate, hybrid accelerator, energy flow) bound to registry parameters and stored runs | Every 3-D quantity traceable to a stored run or registry value and labelled conceptual / simulated / measured | Not started. Static dashboard exists as a stopgap. |
| **3 Joint optimisation, extended** | Dynamic loop model (tank mass, setpoint ramps); horizon MPC; routing integrated with clock and cooling decisions; power-cap scenario; multi-node placement with migration cost; controller-chattering fix (hysteresis / move suppression) | Joint vs independent re-run under the dynamic plant model; E005-style mismatch shows graceful degradation | Not started |
| **4 Real-hardware validation** | NVML telemetry logger (read-only); wall-power meter; power-vs-temperature-at-fixed-clock sweep (calibrates `kappa_leak`, `p_leak_ref`); clock-vs-throughput sweep per kernel class (calibrates `beta_*`, `v_min_ratio`); real inference benchmarks with quality scoring | Predicted vs measured within stated error on held-out runs; claims limited to the measured boundary (a GPU-only measurement is not a facility measurement) | Needs the owner's GPU machine and a power meter |
| **5 Hardware feasibility** | Only if Phase 4 identifies a bottleneck that software and existing parts cannot fix: requirements spec, ≥3 architectures, block-level models, RTL of one kernel with Verilator/Yosys | See gates in `08_hardware_feasibility.md` | Not justified by current evidence |
| **6 Publication** | Paper-format package separating new contributions from prior work | Prior-art review complete for every novelty claim | Not started |

## Immediate next steps (ordered)

1. **Phase 4-lite on a single GPU** (highest information value). The two parameter groups that dominate E002 (see RESULTS.md) can be measured on one card with `nvidia-smi`/NVML:
   * clock vs throughput vs power for a compute-bound and a memory-bound inference kernel → `beta_compute`, `beta_memory`, V–f behaviour;
   * power at fixed clock and load while the card warms up → leakage–temperature slope.
   This replaces the most consequential class-F numbers with class-B numbers from your own hardware.
2. **Dynamic loop model.** Add coolant thermal mass and setpoint rate limits. Re-run E001/E005, since the quasi-steady plant favours aggressive setpoint moves.
3. **Controller stability.** Add move suppression (penalise setpoint changes) and quantify chattering. This also addresses the E004 decision-path sensitivity.
4. **Phase 2 backend.** FastAPI over `Store`, then the cold-plate 3-D model bound to `physics.r_total` / `plant` (first visual, because its physics already exists and is tested).
