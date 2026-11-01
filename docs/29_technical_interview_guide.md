# 29 · Technical interview guide

Questions someone might ask about UEIC, with model answers. The answers state what the project actually shows and say so when something is only simulated or still pending.

## A. Purpose and framing

**1. What question does UEIC try to answer?**
Does controlling AI compute (clocks, routing, placement) jointly with cooling (supply temperature, flow) lower *facility* energy per *successful* task, without breaking thermal limits or service levels? Two things are in the denominator on purpose:
* success, because a cheap wrong or late answer is not useful work;
* facility energy, because lower GPU power does not imply lower facility energy.

**2. Why not just minimise GPU power?**
Slower clocks can raise energy per unit of work: static and leakage power are paid for longer. Cooling energy depends on supply temperature and plant state, not only on heat. And a slower answer can miss its deadline. GPU power is one term of a bigger sum.

**3. What has actually been measured, and what is simulated?**
* **Measured** (NVML board telemetry on an RTX 5070):
  * clock sensitivity of compute throughput (β ≈ 0.98);
  * the voltage-floor shape of power vs clock;
  * the energy-minimum clock of two kernels;
  * a narrow-window leakage slope (~0.13%/K of board power);
  * the fast thermal response.
* **Simulated:** everything about cooling plants, facilities, schedulers and faults.
* Every metric carries a provenance label.

## B. Architecture and code

**4. How is the code organised?**
`ueic/` contains:
* the original single-node simulator (`sim.py`, `policies.py`, `workload.py`), which is bitwise reproducible;
* `physics/`: chip, thermal, plant, NTU dry cooler, chiller part-load, pump, storage, heat pump, power delivery;
* `models/`: parameter uncertainty, identifiability, system identification, drift, adaptive twins;
* `control/`: forecasters, MPC, robust MPC, safety filter, fallback;
* `inference/`: serving adapters, traces, scoring, energy accounting;
* `scheduling/`: thermal budgets, placement, router, phase clocks;
* `facility/`: the multi-node simulator;
* `grid/`;
* `reliability/`;
* `hardware/`: mode-gated adapters;
* `integrations/`: kernel harness, ATLAS/KernelSmith stubs.

Experiments are JSON specs run into an append-only SQLite store with a hash chain.

**5. How do you keep old results valid while changing physics?**
* New physics is opt-in behind registry parameters whose defaults reproduce the old behaviour. For example, `plant_model = 0` keeps the legacy plant.
* A test re-simulates stored E001 runs and requires bitwise identical metrics.
* Each run stores the configuration hash. The "simulation core" hash covers only the modules that can change outputs.

**6. What does "append-only with a hash chain" buy you?**
* Every finished run's content is hashed together with the previous run's hash, so a silent edit anywhere breaks verification (`python -m ueic verify`).
* Failed and aborted runs stay in the database with reasons. When E021's first attempt was cut off by a session limit, it was aborted with that reason and re-run as a superseding experiment; nothing was deleted.

**7. Why is the safety filter separate from the MPC?**
* So an optimiser bug cannot approve its own unsafe action. The filter keeps its own record of approved setpoints and uses only installation ratings (maximum heat, loop mass, ramp) to bound the supply temperature over the next interval.
* It never credits cooling that has not arrived. It lowers clocks or falls back if the proposal is not safe at that bound.
* The simulated hardware throttle sits underneath it, independently.

**8. How do schedulers interact with the facility simulator?**
* Each scheduling step gets a read-only `FacilityView` (copies of temperatures, inlets, resistances, powers and topology), and the scheduler returns GPUs and a clock, or holds the job.
* The simulator validates the placement (free, enough memory, right count).
* Throttling and power caps are applied after any scheduler decision, so no scheduler can bypass them.

## C. Physics and mathematics

**9. Derive the thermal budget used for placement.**
Start from C dT/dt = P − (T − T_in)/R. With constant power P + ΔP, the solution is T(H) = T_ss + (T₀ − T_ss)e^(−H/τ), with T_ss = T_in + R(P + ΔP) and τ = RC. Set T(H) = T_lim and solve:

ΔP = [(T_lim − T₀e^(−H/τ))/(1 − e^(−H/τ)) − T_in]/R − P.

* For H ≪ τ this tends to C(T_lim − T₀)/H (stored heat).
* For H ≫ τ it tends to (T_lim − T_in)/R − P (steady headroom).

**10. Why does a series cold-plate chain matter for placement?**
The downstream plate's inlet is warmer by the upstream heat divided by ṁc_p. At 620 W and 1.2 L/min that is ~7.5 K. Placing a hot job upstream steals headroom from the downstream GPU. That is why the placement credit is taken as the minimum over *all affected* GPUs.

**11. Explain the NTU dry-cooler model and why it was needed.**
* The heat rejected is εC_min(T_w,in − T_amb). The effectiveness ε of a crossflow exchanger depends on NTU = UA/C_min and on Cr. Fan power scales with the cube of fan speed, and UA grows sub-linearly with it.
* Cooling water closer to ambient therefore needs disproportionately more fan power.
* The legacy plant charged fan power proportional to heat, independent of approach. That made warm water look pointless (the E012 audit finding). The NTU model fixes that structurally.
* Its parameters are still placeholders.

**12. Why is the leakage curvature κ not identifiable from the warm-ups?**
* The warm-ups span ~10 independent temperature levels over 9 K, with whole-degree readings.
* The Fisher information for κ in P = c + L e^(κ(T−60)) is tiny there, so its Cramér–Rao bound exceeds its value.
* A wider window (M003, 50–70 °C) shrinks it about fivefold. The planner ranked designs this way before M003 was run.

**13. What is a CUSUM, and why use the upper bound of σ?**
* A CUSUM accumulates standardised deviations beyond a slack k and alarms past a threshold h. It is a sequential likelihood-ratio test for a mean shift.
* With σ estimated from a few points, it is often too small, which inflates false alarms. Using the 90% upper χ² bound of σ made the measured false-alarm rate acceptable (7% over 180 samples) at almost no cost in detection speed for large faults.

**14. How is energy attributed to individual inference requests?**
* Idle energy (idle power × window) is never spread over requests. It is its own term.
* Dynamic energy is split either equally among requests in flight in each sampling interval, or in proportion to tokens. Both conserve the total, and energy with nothing in flight is reported as unattributed.
* Neither is "true". They answer different questions, so both are reported.

## D. Experiments and results

**15. What did E015 show?**
* The MPC with an independent safety filter was the only arm that never exceeded 80 °C in any of 24 conditions and 5 forecast variants. Steady-state joint control exceeded it in 10 conditions, independent control in 18, and even the conservative measured-state rule in 2.
* The MPC also used 2–5% less energy per successful task where inertia or fouling mattered.
* Its benefit to late tasks could not be shown, because the scenarios were too easy (baseline ~1 late task). The hypothesis therefore failed on its pre-registered "at least 1 fewer" criterion.
* A burst-blind forecast caused 12× the late tasks of plain persistence.

**16. Why report hypotheses that failed?**
* They were registered before the run, and changing them afterwards would turn a test into a story.
* Failures are informative: E015 H3 failing says part of the MPC's advantage is not anticipation, which points to the next experiment.

**17. What did E016 show about adaptive models?**
* Online resistance estimation eliminated time above the limit under gradual fouling.
* It did not remove it after an abrupt step at 35 °C ambient (−33%), because the estimator needs several intervals to move. That motivated a direct residual-based fault layer (E019).

**18. What are E018–E024 testing?**
* E018: thermal-credit placement against four standard policies, including a condition where no benefit is expected.
* E019: nominal vs fault-aware supervision under 13 faults.
* E020: joint supply, valve and placement control from 1 to 16 nodes.
* E021: heat reuse with an approach-dependent dry cooler.
* E022: grid caps, with energy vs cost vs carbon kept separate.
* E024: a 2⁴ factorial ablation.

Each has numeric criteria in its spec. Results and verdicts are in `PHASE_REPORT.md` and `25_research_findings.md`.

**19. How do you avoid fooling yourself with simulations?**
* Pre-registration.
* Paired seeds and practical thresholds.
* Explicit "expected null" conditions.
* Independent audits of claims against files.
* Provenance labels.
* Bitwise reproduction tests.
* Conservation and analytic checks on every new simulator.
* Disclosure of every exploratory run made before registration.

## E. Limitations and judgement

**20. What is the biggest weakness?**
Physical validation. One GPU's board sensor is the only measured hardware. Plant and facility physics are placeholders, and the facility simulator has an instant plant.

**21. Is any of this novel?**
No novelty claim is made. Close prior work exists (ETCInfer for joint cooling and frequency control in LLM inference; TAPAS for thermal- and power-aware placement; the Emerald AI field demonstration for GPU demand response; older thermal-aware scheduling and MPC papers). UEIC's contribution is a transparent, pre-registered simulation platform with separated boundaries. See docs/26.

**22. What would you measure next, and why that order?**
1. M003 (leakage over a wide window): every warm-water result scales with it.
2. E017 (real serving energy per correct answer): replaces synthetic workloads.
3. A thermal test vehicle with flow and temperature sensors: physical validation of the control and safety claims.

## F. Practical data-centre applications

**23. If a data-centre operator asked what to take from this today, what would you say?**
* Judge efficiency by energy per useful, on-time result, never by GPU power or J/token alone.
* Never let an optimiser credit cooling that has not arrived. Keep an independent filter, plus hardware protection underneath.
* Validate forecasters by how they fail, not only by their average error.
* Treat warm-water and heat-reuse benefits as dependent on the fan and chiller physics of the specific plant.
* All of these are simulation-backed heuristics, not measured savings.

**24. How would you deploy the control stack safely?**
1. Read-only monitoring first.
2. Then replay of recorded telemetry.
3. Then simulation against the replay.
4. Then operator-approved control with narrow grants, restore-on-exit, independent interlocks and a human present.

UEIC's hardware layer enforces this order: read-only adapters have no write path, and no GPU setter exists anywhere.

**25. How does the router decide which model serves a request?**
* It uses only measured accuracy per task (with a Wilson lower bound) and measured energy per request.
* It adjusts energy by the predicted leakage at the current temperature and by the plant's current cooling overhead, and drops models whose peak power exceeds the electrical headroom.
* It refuses to route on a model with no measured accuracy. Self-reported confidence is never used.
