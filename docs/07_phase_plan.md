# 07 · Phased implementation plan

Each phase has an exit gate. A phase does not start until the previous gate is passed, or until its failure is documented and accepted.

| Phase | Scope | Exit gate | Status |
|---|---|---|---|
| **0 Research & feasibility** | Problem statement, RQs, evaluation criteria, architecture, assumptions register, risks, baseline method, literature matrix | Criteria fixed before results; every simulator number has provenance | **Done** (this package) |
| **1 Working simulation** | Workload, power, thermal, plant models; 5 policies; logging; benchmark; validation tests | Tests pass; energy balance closes; baseline reproducible; ≥2 strategies compared with CIs | **Done**, with a known gap: joint-controller results vary ~0.5% with decision path (E004) |
| **2 Interactive visualisation** | FastAPI service over the store; experiment manager; Three.js lab (cooling, facility, chip, photonic concept, energy flow) bound to registry parameters and stored runs | Every 3-D quantity traceable to a stored run or registry value and labelled conceptual / simulated / measured | **Done.** Plain JavaScript modules with vendored Three.js instead of React/TypeScript (no build step, works offline on Windows); see `03` |
| **3 Joint optimisation, extended** | Dynamic loop model; move suppression; self-correcting controller; *still open:* horizon MPC, routing integrated with clock and cooling, power cap, multi-node placement | Joint vs independent re-run under the dynamic plant; mismatch shows graceful degradation | **Partly done** (E006 v2, E007, E008). Lag-aware planning is the next item |
| **4 Real-hardware validation** | NVML telemetry logger (read-only); calibration sweeps and fits; ingestion as measurements; calibrated experiment versions | Predicted vs measured within stated error on held-out runs; claims limited to the measured boundary | **In progress.** M001 (RTX 5070): clock sensitivity measured and used in E001C; power-vs-clock shape compared with the simulator (error up to 0.09 of top-clock values); voltage–frequency and leakage fits rejected (`10`). Next: leakage re-measurement |
| **5 Hardware feasibility** | Only if Phase 4 identifies a bottleneck that software and existing parts cannot fix | See gates in `08_hardware_feasibility.md` | Not justified by current evidence |
| **6 Publication** | Paper-format package separating new contributions from prior work | Prior-art review complete for every novelty claim | Not started |

## Immediate next steps (ordered)

1. **Re-measure leakage** with the improved warm-up (`09`, section 3) and record it as M002.
2. **Measured voltage–frequency form** in the simulator, then re-run E001C with it.
3. **Lag-aware joint planning:** a short-horizon MPC using the tank and ramp model. E006 v2 shows steady-state planning loses thermal margin under loop lag.
4. **Routing in the joint optimiser,** plus a facility power-cap scenario.
5. **Operation-level energy model** (FLOPs and bytes per phase) to estimate the data-movement share, for gate 1 of `08`.
