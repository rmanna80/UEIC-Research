# 07 · Phased implementation plan

Each phase has an exit gate. A phase does not start until the previous gate is passed, or until its failure is documented and accepted.

| Phase | Scope | Exit gate | Status |
|---|---|---|---|
| **0 Research & feasibility** | Problem statement, RQs, evaluation criteria, architecture, assumptions register, risks, baseline method, literature matrix | Criteria fixed before results; every simulator number has provenance | **Done** (this package) |
| **1 Working simulation** | Workload, power, thermal, plant models; 5 policies; logging; benchmark; validation tests | Tests pass; energy balance closes; baseline reproducible; ≥2 strategies compared with CIs | **Done**, with a known gap: joint-controller results vary ~0.5% with decision path (E004) |
| **2 Interactive visualisation** | FastAPI service over the store; experiment manager; Three.js lab (cooling, facility, chip, photonic concept, energy flow) bound to registry parameters and stored runs | Every 3-D quantity traceable to a stored run or registry value and labelled conceptual / simulated / measured | **Done.** Plain JavaScript modules with vendored Three.js instead of React/TypeScript (no build step, works offline on Windows); see `03` |
| **3 Joint optimisation, extended** | Dynamic loop model; move suppression; self-correcting controller; *still open:* horizon MPC, routing integrated with clock and cooling, power cap, multi-node placement | Joint vs independent re-run under the dynamic plant; mismatch shows graceful degradation | **Partly done** (E006 v2, E007, E008). Lag-aware planning is the next item |
| **4 Real-hardware validation** | NVML telemetry logger (read-only); calibration sweeps and fits; ingestion as measurements; calibrated experiment versions | Predicted vs measured within stated error on held-out runs; claims limited to the measured boundary | **In progress.** M001/M002 (RTX 5070): clock sensitivity measured and used in E001C; power-vs-clock shape compared with the simulator (error up to 0.09 of top-clock values); voltage–frequency and leakage coefficient rejected; leakage temperature slope measured at two points, about a third of the registry's. E009: with that slope, joint control's energy advantage falls under 0.6% everywhere. E010: its thermal-safety benefit holds with an instant plant but fails under a slow loop in the hottest fouled conditions (`10`, `RESULTS`) |
| **5 Hardware feasibility** | Only if Phase 4 identifies a bottleneck that software and existing parts cannot fix | See gates in `08_hardware_feasibility.md` | Not justified by current evidence |
| **6 Publication** | Paper-format package separating new contributions from prior work | Prior-art review complete for every novelty claim | Not started |

## Immediate next steps (ordered)

1. **Lag-aware joint planning:** a short-horizon MPC using the tank and ramp model. E010: with a slow loop at 40 °C and fouled cold plates, steady-state joint planning overheated more than independent control. Re-run E010's dynamic half with it.
2. **Unnoticed degradation:** fouling the twin does not know about, with the self-correcting controller and the lag-aware planner.
3. **Measured voltage–frequency form** in the simulator, then re-run E001C, E009 and E010.
4. **Leakage over a wide temperature range**, only with a fixed fan speed.
5. **Routing in the joint optimiser,** plus a facility power-cap scenario.
6. **Operation-level energy model** (FLOPs and bytes per phase) to estimate the data-movement share, for gate 1 of `08`.
