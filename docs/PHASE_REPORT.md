# UEIC · Phase report (Phases 0–4)

*All results are simulator outputs. They are conditional on the assumptions register, most of which is class E/F. Exact figures, confidence intervals and the experiment IDs behind them are in `RESULTS.md`, which is generated from the database.*

## What was built

* **Phase 0 documents:** problem statement and measurement boundary (`00`), research questions mapped to experiments and the evaluation criteria fixed before running (`01`), a verified literature matrix of 43 sources with synthesis (`02`), architecture and the alternatives considered (`03`), an assumptions register generated from code (`04`), risks and dependencies (`05`), a phase plan with exit gates (`07`), and a hardware feasibility assessment (`08`).
* **A simulator** of one 8-accelerator liquid-cooled node. It models DVFS and temperature-dependent leakage, lumped RC junction temperatures with an exact integrator, cold plate, pump, dry cooler, trim chiller and power conversion, with energy conservation checked on every run. It also models a synthetic phase-mixed workload, a small-model cascade, and hardware thermal protection the controllers cannot override.
* **Five controllers:** fixed baseline, compute-only DVFS, cooling-only plant optimisation, both running independently, and a joint model-predictive controller planning against a steady-state digital twin.
* **An experiment platform.** Experiments are pre-registered, run in parallel, and stored in an append-only SQLite store with database-enforced immutability, a SHA-256 hash chain, versioned supersession, a corrections table and CSV/JSON/bundle export. The report and a self-contained HTML dashboard are generated from the database.

## What was tested

45 validation tests cover the following:
* the analytic RC transient and exact energy conservation of the thermal step;
* the leakage steady state against a root finder, and the analytic thermal-runaway boundary;
* coolant and pump hand calculations, the Carnot bound on chiller COP, and the free-cooling regimes;
* exergy bounds and the Landauer value;
* energy closure for every policy, bitwise reproducibility, and work conservation;
* simulator vs twin at steady state, hardware protection bounds, and time-step convergence;
* routing vs analytic expectations;
* store immutability, corrections, tamper detection and failure preservation, and parameter provenance and validation;
* two regression tests for bugs found during analysis (below).

## What the results show

**1. Clock control is the dominant lever in this model.** Energy-aware DVFS alone cut facility energy per successful task by 14–35% versus the fixed baseline (E001). The magnitude depends mostly on the assumed voltage–frequency curve: the joint-vs-fixed saving ranged from 24% to 39% across the `v_min_ratio` range (E002). It also depends on the memory-bound share of work and on static power. The literature supports the direction (L03, L09, L10). The registry's memory-boundness range is, if anything, conservative for LLM decode (L09).

**2. Warm-water free cooling is a smaller, reliable lever.** Optimising only the plant saved 0.8% (cool ambient, where the 18 °C baseline is already free-cooled) to 7.3% (hot ambient). It removes nearly all chiller energy at the cost of higher IT energy from leakage.

**3. Joint optimisation beats independent optimisation, but only slightly.** The gain is 0.3–1.4% (E001). The paired CI excludes zero in all 6 scenarios, but the whole CI clears the pre-registered 1% practical threshold in only 2 (cool ambient, degraded cooling). The joint controller runs chips cooler, trading pump energy for lower leakage. The gain scales with leakage. It nearly disappears when leakage is small (E002: −0.03% to −0.04% at the low bound of `kappa_leak` or `p_leak_ref`) and grows to 2–4% when leakage is high and the twin is correct (E005). The sign never reversed in 50 one-at-a-time variations. This trade-off is prior art (L24–L27). The project does not claim it as new.

**4. Uncoordinated control can be unsafe, and so can a wrong model.** In hot ambient and with degraded cold plates, the independent cooling controller raised supply temperature while treating chip power as fixed. Leakage rose, junctions exceeded the 80 °C target (425 and 1,240 chip·s), and hardware protection throttled chips (E001). The joint controller stayed within target in every E001 scenario. But when its twin underestimated leakage in hot ambient, the joint controller did worse than independent control on energy (+0.7%) and on thermal safety (4,021 chip·s over target, 314 throttled; E005). Model accuracy matters at least as much as coordination.

**5. Routing saves energy below its break-even point, but energy does not track work one-to-one.** Simulated work matched the analytic cascade expectation exactly. Under the fixed baseline, energy fell less than work, because static, idle, conversion and cooling power do not scale. Under joint control, energy fell *more* than work at intermediate cascade costs (rs+rv = 0.45–0.60: −26% energy vs −22% work at 0.45) and rose more than work above break-even (+17% vs +13% at 0.80). Lighter load lets the controller lower clocks; heavier load forces them up (E003). A verifier that accepts 10% of wrong answers still saved ~32–38% energy while cutting success by ~1.1 pp. That is the quality–energy trade-off a real evaluation must measure.

**6. Heat reuse competes with leakage control.** Return water reached the 45 °C reuse threshold only in hot ambient. There the joint controller, running cooler, offered less reusable heat (2.1 kWh) than cooling-only (6.1 kWh). No heat user is modelled, so no net benefit is claimed.

## What remains uncertain

* Every hardware and plant number in classes E/F, above all the leakage–temperature relation, the V–f curve, and clock sensitivity by workload phase. These drive conclusions 1 and 3.
* Plant dynamics. The loop has no thermal mass and setpoints move instantly, which flatters controllers that move setpoints aggressively.
* The workload and quality model is synthetic. Routing percentages are not transferable; the break-even condition and the work-vs-energy gap are.
* Whether conclusions hold beyond one node: placement, network and power-delivery limits are not modelled.

## What failed (kept in the database and the report)

| Item | What happened |
|---|---|
| **Plant bug (E001 v1)** | Chiller work came out slightly negative (≈ −0.001 kWh) when supply water was above an idle chip's temperature. Fixed, regression-tested, and all experiments re-run as superseding versions. v1 records and the aborted E003 v1 are preserved. |
| **Metric bug (E001 v2)** | Exergy of rejected heat was negative when supply water was below ambient. Redefined as work potential above ambient, regression-tested, and E001 re-run as v3. |
| **E004 convergence criterion** | Not met for the joint controller: grid energy changed by up to 0.52% between dt = 1 s and 0.5 s (fixed policy: 0.02%). The cause is decision-path sensitivity of the grid-search controller, not discretisation error. Joint differences under ~0.5% are therefore not resolvable by this simulator. |
| **E001 H2 quality guard** | All DVFS policies produced slightly more late tasks than fixed (+0.2 to +1.8 per run, at most about 0.04 pp of tasks). As pre-registered, H2 is not supported despite large energy savings. |
| **E002, second half** | Predicted `beta_memory` among the top two drivers of joint-vs-fixed savings; it ranked 6th. |
| **E003, one clause** | Predicted energy savings smaller than work savings; false under joint control at rs+rv = 0.45–0.60. |
| **E005, half the cases** | Predicted thermal-target violations under every leakage or cold-plate twin error; they occurred only in hot ambient (2 of 4 cases). |
| **Disclosure** | One smoke run preceded registration of the hypotheses and the 1% threshold (research log). |

## Phases 2–4 (second session)

### What was built

* **Phase 3 simulator upgrades.**
  * A coolant loop with thermal mass (a well-mixed supply tank) and a ramp limit on the plant's outlet temperature. The plant can no longer heat water: if the setpoint is above the return temperature, water passes through and the tank absorbs the heat.
  * Move suppression for the joint controller (`joint_switch_rel`).
  * A self-correcting joint controller (`joint_robust`). It compares measured peak junction temperature with its twin's prediction and tightens its own target by a one-sided running estimate of the error.
  * A `warm_start` option (see failures).
  * Action-change metrics and per-chip temperature series.
  * With all new options at their defaults, every stored E001–E005 result still reproduces bitwise (a test reads the database).
* **Phase 4 tooling (needs your GPU to run).**
  * Read-only NVML telemetry. A test enforces that no setter is ever called.
  * Calibration sessions and fits for clock sensitivity, the voltage–frequency form and leakage–temperature, each with standard errors and range checks.
  * Ingestion into the store as a measurement experiment (`physical_measurement` provenance), and `run --calibration` to create traced, calibrated experiment versions.
  * The fits are validated by recovering known parameters from synthetic sessions. Protocol: `09_calibration_protocol.md`.
* **Phase 2 lab.**
  * A local FastAPI service (127.0.0.1) over the store and the physics module.
  * A Three.js lab with these views:
    * a cooling system bound to the physics model, with assumption sliders and an exploded view;
    * facility playback of stored runs, with per-chip temperatures and before/after comparison;
    * an exploded accelerator package whose blocks link to model parameters;
    * a conceptual photonic accelerator showing qualitative energy sinks;
    * a per-run energy-flow diagram;
    * an experiment manager that registers and runs experiments through the same append-only path.

### What was tested

102 tests in total (45 from Phases 0–1). New coverage:
* bitwise legacy reproduction;
* dynamic-loop energy closure, ramp bound, steady state against the twin, pass-through, and the quasi-steady limit;
* the exact tank response;
* move suppression;
* self-correction under mismatch;
* the warm-start regression;
* telemetry read-only enforcement;
* fit recovery on synthetic data, including a GPU whose NVML clock maximum is far above the clock it sustains and one with a low-clock voltage floor;
* environment diagnosis before any session folder is created, unheld clock locks, and probe-based sweep clocks;
* API values against the twin and the store;
* the experiment POST path.

The lab was checked in a headless browser on desktop and phone, in light and dark themes, with no JavaScript errors.

### What the results show (E006 v2, E007, E008; simulated)

**7. A dynamic coolant loop does not change the picture.** Joint still beats independent control by 0.4–1.5% under both dynamic plants, every CI below zero (E006 v2). That is the same order as with the instant plant, and clears the 1% threshold only with degraded cooling.

**8. Loop lag erodes joint control's thermal margin.** With degraded cold plates, the joint controller exceeded the 80 °C target under both dynamic plants: 131 chip·s with the 40 kg loop and 421 with the 150 kg loop, versus 0 with the instant plant. It never triggered throttling. It plans against a steady state the slow plant needs minutes to reach. Independent control was worse throughout (1,168–1,256 chip·s, 139–152 throttled).

**9. Move suppression fixes nothing that needed fixing.** Most switching is clock changes that track demand; supply temperature barely moves. A 5% threshold cut switching by 16–25% but cost 0.4–0.5% energy. On 4-hour runs, time-step sensitivity was already under 0.5% without suppression (worst 0.39%), and a 2% threshold did not change it (E007). E004's 0.52% came from short 1-hour runs.

**10. Feeding measured temperatures back restores most of the safety lost to a wrong twin.** In both cases where plain joint control overheated under mismatch, the self-correcting controller cut chip-seconds over target by 84–85% and eliminated throttling. With a correct twin it matched plain joint to within 0.06% (E008). Under the leakage mismatch it ended level with independent control on energy (+0.07%, CI −0.17% to +0.31%), where plain joint was 0.7% worse. It did **not** help with loop lag: it slightly increased overshoot in E006 (176 vs 131 and 464 vs 421 chip·s). Its correction targets model error, not delay.

### What failed (second session)

| Item | What happened |
|---|---|
| **E006 v1 confound** | With a cold start, the joint controller's first decision (zero demand) chose 12 °C, and the dynamic plant used that as the initial tank temperature. Joint runs then used up that stored coldness (up to 4.9 kWh per run), making joint look 4.8% better than independent in hot ambient. Found by examining v1's energy breakdown. Fixed with `warm_start` and a run warning when loop-storage change exceeds 0.5% of grid energy; regression-tested. Re-run as v2 with unchanged hypotheses; v1 is kept. |
| **E006 H4** | Predicted the self-correcting controller would never overheat more than plain joint; false under loop lag (two cases). |
| **E008 H2** | Predicted the self-correcting controller would be no worse than independent on energy in every case. In the hot leakage-mismatch case the CI (−0.17% to +0.31%) does not exclude a small loss. |
| **E007 H2** | Met as written (worst 0.38–0.39% at a 2% threshold), but equally met with no threshold. Suppression is not the reason. |
| **Residual storage** | 13 E006 v2 runs (independent control, degraded cooling) still changed loop storage by more than 0.5% of grid energy. Up to 0.85% of grid energy ends up stored rather than rejected, which flatters independent control by at most a few tenths of a percent. |
| **Disclosures** | One exploratory move-suppression run and one self-correction unit test preceded registration of E007 and E008; E006 v1 results were seen before v2 was registered. All are stated in the specs. |

### Calibration attempt 1 (2026-10-26, RTX 4060 Laptop GPU)

| Item | What happened |
|---|---|
| **Clock locking** | `nvidia-smi -lgc 1500,1500` was accepted. Many laptop GPUs refuse it, so the clock sweep is possible on this device. |
| **Run stopped before measuring** | The warm-up stopped with "PyTorch cannot see a CUDA GPU". The Administrator window had no virtual environment active, so the likely cause is a different Python or a CPU-only PyTorch build; not yet confirmed. No data was recorded, but an empty session folder was left. Fixed: PyTorch and NVML are now checked before the folder exists, `calib check` names the exact cause, and errors print without a traceback. |
| **Clock reference (found in review, before any data)** | The fit scaled clocks by NVML's maximum SM clock. On this GPU that is 3105 MHz, the top of the driver table, which it does not sustain under load. The planned 900–1800 MHz sweep would have sat at s = 0.29–0.58, mostly below the simulator's s_min = 0.5, so the `v_min_ratio` fit would have been an extrapolation. Fixed: s is now relative to the highest measured compute clock, and the power fit uses only s ≥ 0.5 and needs at least 4 clocks there (3 clocks leave no standard error). `calib probe` suggests sweep clocks from the clock the GPU sustains at default settings. Unheld locks and power- or thermal-limited sessions are flagged. |

### First real-hardware measurement: M001 (2026-10-26, RTX 5070)

Twelve sessions on the user's desktop GPU (probe, warm-up, compute and memory kernels at five locked clocks); full report in `10_calibration_results.md`. These are physical measurements of GPU board power, not facility energy.

| Result | Status |
|---|---|
| **Clock sensitivity.** Compute throughput scales with clock to the power 0.983 ± 0.009. Memory-bound throughput does not depend on the core clock (measured −0.056 ± 0.079). | Accepted; used in E001C (memory value transferred as 0) |
| **Energy per unit of work.** The compute kernel used least energy per FP16 TFLOP at 1657 MHz, 32% below the top clock; the memory kernel used least at the lowest clock, 31% below, with no throughput loss. | Model-free measurement |
| **Simulator check.** With registry defaults the simulator gets the size of that saving roughly right (35% predicted) but the shape wrong: at 88% of the top clock it predicts a 13% saving where 22% was measured. Small clock cuts save more than modelled, deep cuts less. | Phase 4 comparison; error up to 0.09 of top-clock values |
| **Voltage–frequency form.** The registry's straight-line form cannot follow the measured flat-then-steep power curve; the fit ran to its bound. | Rejected (R1) |
| **Leakage.** The fan held the warm-up at 53–57 °C, too narrow to separate leakage from its temperature coefficient, and the load was unsteady for several minutes. The slope it did measure (0.09–0.15% of board power per K) is 2.5–4× below the registry's 0.37%/K. | Rejected (R1); slope indicative only |

**E001C: the benchmark with measured clock sensitivity (pre-registered, 300 runs, 0 failed).** Same seeds and workloads as E001, seed-paired.

| Hypothesis | Verdict | Result |
|---|---|---|
| HC1: compute-only saves more vs fixed than in E001, all 6 scenarios | **supported** | 4.1 to 8.7 percentage points more; saving vs fixed now 20.5–43.4% (E001: 14.4–34.8%) |
| HC2: largest change in the memory-heavy scenario | **supported** | −8.67 pp [−9.16, −8.17] in S5_memory_heavy |
| HC3: joint vs independent moves by < 0.5 pp in ≥ 5 of 6 scenarios | **supported** | at most 0.15 pp in all 6; joint still beats independent everywhere, beyond 1% in 2 of 6 |
| H1, H2 inherited from E001 | same as E001 | H1 supported; H2 energy met, quality guard failed in the same 18 comparisons (slightly more late tasks, at most 1.4 per ~2,900) |

What this means: with clock sensitivity measured rather than assumed, energy-aware clock control looks *more* valuable, because memory-bound work loses no speed at lower clocks. The joint-control result does not move. Both statements still rest on the simulator's voltage–frequency and leakage placeholders, and on beta_memory = 0 from a pure streaming kernel, which is a bound for LLM decode.

**E009: joint vs independent with leakage matched to the measured slope (pre-registered, 360 runs, 0 failed).** The warm-ups could not identify the leakage coefficient, but they measured how fast board power rises with temperature: 0.135% per K at 75% of the top clock, against 0.366% per K in the registry. E009 sets the simulator's leakage power so that its slope matches, for leakage coefficients of 0.01, 0.02 and 0.03 per K and at both ends of the slope's 95% CI.

| Hypothesis | Verdict | Result |
|---|---|---|
| H1: joint's advantage shrinks vs registry leakage, all 6 scenarios | **supported** | by 0.29–1.22 percentage points |
| H2: with matched leakage (κ 0.02), joint vs independent inside ±1% in all 6 | **supported** | −0.03% to −0.43% (registry: −0.32% to −1.45%); still below zero in 6 of 6 |
| H3: H2 holds for every matched variant | **supported** | largest −0.56%, in degraded cooling and cool ambient |
| H4: independent's overheating falls wherever it had any | **supported** | hot ambient 559 → 0 chip·s above 80 °C; degraded cooling 1,263 → 395, throttled 186 → 20. Joint stayed at 0 throughout |

What this means for the main research question: **with a real chip's temperature sensitivity, joint control's energy advantage over well-run independent control is real but small, under 0.6% in every scenario.** The advantage in Phase 1 came mostly from cutting leakage by running chips cooler, which pays off far less when leakage barely changes with temperature. What survives is thermal safety. Under degraded cooling, independent control still exceeds 80 °C and throttles, while joint control does not. These conclusions still rest on one consumer card's slope over a 4 K window and on the placeholder voltage–frequency form.

**E010: thermal safety under cooling degradation and heat (pre-registered, 270 runs, 0 failed).** Measured leakage slope and clock sensitivity throughout; 3 cold-plate states × 3 ambient temperatures × 2 plants, high load.

| Hypothesis | Verdict | Result |
|---|---|---|
| H1: instant plant, joint never throttles and exceeds 80 °C in ≤ 1 of 9 | **supported** | 0 of 9 above target, 0 throttled; peak ≤ 79.9 °C |
| H2: instant plant, independent throttles in ≥ 3 of 9, all fouled | **supported** | above target in 6 of 9 (including clean plates at 40 °C), throttled in 3 (worst 246 chip·s) |
| H3: slow loop, joint exceeds 80 °C with severe fouling | **supported** | moderate/40 °C: 1,473 chip·s; severe/40 °C: 5,493 chip·s and 212 throttled, *worse* than independent (1,785 and 170) |
| H4: safety costs no energy | **supported** | joint vs independent −0.04% to −2.41%; the larger savings (1.5–2.4%) are where independent overheats |
| H5: joint ≥ 10% below fixed | **supported** | −35% to −41%; fixed never exceeded 64 °C |

What this means: **joint control's case on real silicon is thermal safety under stress, and it holds only if the controller can anticipate a slow coolant loop.** With an instant plant it kept every chip below 80 °C where independent control overheated in 6 of 9 conditions, and saved energy while doing it. With a 40 kg loop and a 1 K/min ramp, in the two hottest fouled conditions it planned for a steady state the loop could not reach in time and overheated, in the worst case more than independent control. This repeats E006's finding under harsher conditions and makes lag-aware planning the next step.

**E011: lag-aware joint control (pre-registered, 405 runs, 0 failed).** `joint_lag` tracks the plant's ramp-limited setpoint and checks that clocks and flow are safe at the supply temperature the chips will see before the next decision. The design is E010's grid plus a 150 kg loop with a 0.25 K/min ramp.

| Hypothesis | Verdict | Result |
|---|---|---|
| H1: joint_lag never throttles (27 conditions) | **supported** | 0 of 27 |
| H2: joint_lag never exceeds 80 °C with a slow loop (18) | **supported** | 0 chip·s; steady-state joint 17,218 and independent 10,008, summed over the 18 |
| H3: identical to joint with an instant plant (9) | **supported** | runs bitwise identical, seed by seed. The first version of the test compared seed means and failed on a 3.6e-15 kJ summation-order difference; corrected and disclosed |
| H4: no more energy than joint; less than independent where independent overheated | **supported**, but see E011B | −8.8% to 0.0% vs joint |
| H5: at most 2 more late tasks per run than the worse of joint and independent | **not supported** | severe fouling at 40 °C on both slow loops: 7.6 vs 2.0 per run (of about 3,700–3,800 tasks). Seeds give 0, 0, 32, 4 and 2, so one seed carries most of it |

**The energy result was confounded.** joint_lag was about 4.6% cheaper than joint even where lag-awareness should change nothing. A diagnostic of one cell (clean plates, 20 °C, 40 kg loop, seed 0) traced the gap to the 24 of 240 intervals where demand exceeded planned capacity. There joint runs every clock at maximum, while joint_lag's fallback kept memory-bound work at the lowest clock. In the simulator that costs no throughput, because beta_memory = 0, transferred from M001's streaming kernel (measured −0.056 ± 0.079). That kernel is a bound for LLM decode, not a measurement of it, so the size of this saving inherits that caveat.

**E011B: ablation (registered after E011's results, 405 runs, 0 failed).** `joint_fb` is steady-state joint control with joint_lag's fallback.

| Hypothesis | Verdict | Result |
|---|---|---|
| H1: the fallback saves > 2% in all 27 conditions | **supported** | joint_fb vs joint −4.50% to −4.74%, every CI upper bound below −3.3% |
| H2: lag-awareness costs nothing where it is not needed (14 benign slow-loop conditions, ±0.5%) | **supported** | exactly 0.00%: identical decisions |
| H3: lag-awareness, not the fallback, gives the safety | **supported** as worded | where joint overheated, joint_fb still did (1,188–6,155 chip·s); joint_lag 0. This shows the new fallback is not enough. joint_lag's fallback is itself defined by safety at the predicted supply, and the design has no lag-aware arm with the old fallback, so it does not show which part of joint_lag is sufficient |
| H4: the late tasks are the price of lag-awareness | **supported** by the seed-mean rule | severe/40 °C: joint 2.0, joint_fb 2.2–2.6, joint_lag 7.6 per run. The paired difference joint_lag − joint_fb is +5.4 [−6.2, +17.0] and +5.0 [−5.5, +15.5]: both CIs include zero, and one seed (32 vs 10–12) carries most of it |
| H5: joint and joint_lag reproduce E011 run by run | **supported** | 270 of 270 identical |

What E011 and E011B mean together:
* **The lag-aware safety check removed all overheating under slow loops.** That covers both its normal decisions and its overload fallback, which keeps the same check. The fallback's memory-clock choice alone (joint_fb) did not.
  * On slow loops where the delay did not bind, joint_lag's decisions were identical to joint_fb's.
  * With an instant plant, joint_lag hands over to steady-state joint control by design, including joint's original fallback. There it carries joint's 4.7–5.0% fallback penalty relative to joint_fb.
  * With moderate fouling at 40 °C it cost 1.7% energy to avoid 1,200–1,400 chip·s above 80 °C.
  * With severe fouling at 40 °C it used 3.5–4.3% *less* energy than the overheating alternative, and had about 5 more late tasks per run on seed means. That service cost is uncertain: the paired CIs include zero and one seed dominates. Slower clocks while the loop catches up are the likely mechanism, but this was not measured.
* **The overload fallback** is a separate 4.5–4.7% saving, given clock-insensitive memory-bound work (beta_memory = 0 from a streaming kernel). It is not new: it is the phase-aware DVFS insight (L09–L11) applied when capacity runs short.
  * Earlier experiments gave independent and joint control the same all-clocks-to-maximum fallback, so their comparisons stay like-for-like.
  * Absolute clock-control savings were probably understated wherever overload occurred. This is inferred; the earlier experiments were not re-run.

All of this is simulation, and the controller knows the loop's mass and ramp exactly. E013 and E014 test the obvious objections.

**E013: a fixed thermal margin instead of lag-awareness (pre-registered, 300 runs, 0 failed).** The design covered the 12 slow-loop conditions at 30 and 40 °C. `joint_fb` planned against 80 − m °C for m = 0, 3, 6 and 9 K; joint_lag planned against 80 °C. Time above target was always measured against 80 °C.

| Hypothesis | Verdict | Result |
|---|---|---|
| H1: no margin overheats somewhere | **supported** | 4 of 12 conditions, 12,868 chip·s summed |
| H2: a 3 K margin is not enough | **supported** | summed chip·s above 80 °C by margin: 0 K 12,868, 3 K 8,394, 6 K 10,348, 9 K 7,232. No margin was safe everywhere, and the 9 K margin created small excursions (3 and 36 chip·s) at 30 °C with severe fouling |
| H3: joint_lag is cheaper than the safest margin (9 K) in ≥ 9 of 12 | **supported** | cheaper in 10 of 12 (−0.8% to −7.3%); equal in the 2 clean, 30 °C conditions |
| H4: joint_lag's late tasks within 1 of the margin's | **not supported** | severe fouling at 40 °C: 7.6 vs 2.0 |
| H5: joint_lag never exceeds 80 °C | **supported** | 0 in 12 |

**E014: a wrong loop model, and no loop model (pre-registered, 180 runs, 0 failed).** The design covered the 6 slow-loop conditions at 40 °C. joint_lag ran with its loop mass, or its ramp limit, wrong by 4× either way. `joint_meas` has no loop model: it checks safety at the warmer of the measured supply and the setpoint.

| Hypothesis | Verdict | Result |
|---|---|---|
| H1: exact-model joint_lag never exceeds 80 °C | **supported** | 0 in 6 |
| H2: robust to each wrong model | **supported** | 0 chip·s above 80 °C for all four |
| H3: joint_meas at most 10 chip·s above 80 °C, never throttles | **supported** | 0 and 0 |
| H4: joint_meas energy within ±1% and late tasks within 1 | **supported** | identical: 0.00% |
| H5: wrong models cost within ±1% | **supported** | identical: 0.00% (the controllers' configurations were confirmed different) |

What E013 and E014 mean together:
* **A margin cannot buy time from a rate-limited plant.** The plant moves its setpoint at its ramp rate whatever the target. A lower target makes the controller command colder water, but the chips see the same water during the ramp. This is the explanation the plant model implies; it was not separately instrumented. Only the fast actuator, the clocks, can close the gap, and that is what the lag-aware check uses.
* **The loop model was never what made joint_lag safe.** In every condition tested, its decisions were identical to those of a one-line rule: never judge thermal safety at a colder setpoint that has not arrived; use the warmer of measured supply and setpoint. Getting the loop's mass or ramp wrong by 4× changed nothing.
* **The candidate contribution therefore shrinks to a design rule** for steady-state joint optimisers on slow liquid loops. It is simple and cheap, and in simulation it removed every overheating event at no cost where the delay did not bind. Feedback on a measured state is ordinary control practice, so this is a corrected design, not a discovery. Its practical value depends on how often deployed optimisers judge safety at the commanded setpoint, which this review did not establish. E010 showed what goes wrong when they do.
* **Still untested:** loop-model structure error (stratification, transport delay) and a real loop.

**E012: warm water on real-silicon parameters (pre-registered, 360 runs, 0 failed).** The idea under test was that a nearly flat energy-per-work curve and a small leakage slope would let energy-optimal control run the coolant warm enough to make the waste heat reusable. Two parameter worlds were compared:
* the registry placeholders;
* RTX 5070-derived values: M001 clock sensitivity, leakage matched to the slope from M001's warm-up (0.135%/K at 2.0 GHz), and the voltage-floor V–f form fitted to M001's power curve (rms shape error 0.016 vs 0.049 for the registry's form).

Both worlds are simulations of the same 600 W-class accelerator. "Measured world" below means simulated with RTX 5070-derived parameters (class E transfer), not measured. Each world ran with no supply floor and with a 40 °C floor, on an instant plant and a 150 kg loop, in 20, 35 and 8 °C ambient.

| Hypothesis | Verdict | Result |
|---|---|---|
| H1: measured world runs ≥ 10 K warmer without a floor | **not supported** | 0.0 K difference everywhere. Both worlds sit at the coldest supply free cooling allows: 25 °C at 20 °C ambient, 13 °C at 8 °C, 40 °C at 35 °C |
| H2: measured world makes ≥ 50% of heat reusable at 20 and 8 °C ambient | **not supported** | 0% in both worlds: return water never reaches 45 °C without a floor |
| H3: the 40 °C floor costs < 0.5%, and less than in the registry world | **not supported** (second half holds at 20 and 8 °C ambient; at 35 °C both costs are exactly 0) | measured world +2.7% (20 °C ambient) and +4.4–4.5% (8 °C); registry world +7.7% and +12.9%; no cost at 35 °C, where free cooling already forces 40 °C |
| H4: joint_lag never exceeds 80 °C | **supported** | 0 in all 24 cells |
| H5: steady-state joint overheats somewhere with the 150 kg loop | **not supported** | these scenarios run at lower load than S6. Joint never exceeded 80 °C. Independent did, but only in the registry world whenever supply sat at 40 °C (368–400 chip·s), never in the measured world |

What it means:
* **H1 and H2 could not have passed in this plant model, and I should have seen that before registering them** (found by the independent audit).
  * The dry cooler's fan power is a fixed fraction of the heat it rejects, whatever the approach temperature (`physics.plant`), and the cooler reaches any supply down to ambient + 5 K.
  * So above the free-cooling limit, warmer water has no facility-side benefit, and any positive leakage slope puts the optimum at the coldest free-cooled supply.
  * The failure is a property of the model, not evidence about silicon.
* **A rough estimate with an approach-dependent fan law points the same way, but is untested.** It assumes fan power ∝ (5 K / approach)³ at design duty, fans at ~2% of facility energy, and a marginal leakage cost of ~0.15–0.18%/K (class F; computed here, not simulated).
  * The energy-optimal approach would then be ~8 K in the RTX 5070-derived world vs ~6 K in the registry world: about 2 K warmer supply, not 10–20 K.
  * Testing this needs an approach-dependent dry-cooler model, now the top plant-model item.
* **Heat reuse has a chip-side price.** With RTX 5070-derived parameters it is about a third of the placeholder estimate: holding supply at 40 °C costs about 0.16–0.18% energy per successful task per kelvin above the free-cooling temperature, against 0.48–0.51%/K with placeholders.
  * The per-kelvin figures divide the floor cost by the supply rise.
  * The one-third ratio follows the leakage power parameter (27.4 vs 90 W, ratio 0.30), so it restates the measured slope in energy terms rather than adding independent evidence.
  * About 91% of the added energy is IT energy and about 6% conversion losses. Cooling energy rose by a similar *fraction* (+3–6%) but is small in absolute terms.
* **A PUE-style ratio does not register this cost.** The ratio of facility to IT energy stayed at 1.089 with and without the floor while energy per successful task rose 2.7–4.4% (instant plant).
  * In the registry world the ratio did move (1.092–1.093 → 1.096).
  * That PUE hides IT-side changes is a known criticism. It is consistent in direction with Schneider's facility-side analysis (L48, class D, via press: under 1% PUE gain from 45 °C water). L48 compared 32 → 45 °C with chillers, not free cooling, so the two are not directly comparable. The PUE value is this model's.
* **One difference between the worlds is fragile.** At 35 °C ambient the RTX 5070-derived world counts 39–41% of rejected heat as reusable against 25% for the registry world. But mean return temperatures differ by only 0.4–0.5 K (44.3–44.4 vs 43.9 °C) around the 45 °C threshold, so this is threshold-sensitive. The suggested mechanism (less flow spent cooling chips) was not isolated.
* **In the model the only temperature dependence of chip power is leakage, so this cost is set by the leakage slope.** That is the weakest measured input: one card, a 4 K window. M003 (`09` §8) would narrow it.

**Failures and corrections during this measurement:**
* The first desktop fit reported two failed fits (`v_min_ratio` = 0.3 and `kappa_leak` = 0.2, both exactly at their bounds) as class-B measurements. Acceptance rules R1–R3 now stop that. They were set after seeing that fit summary and before examining the raw data, and this is disclosed.
* The tool reported "clock held down by a power cap" at 35% of the power limit. On this GPU the driver sets that flag whenever clocks are locked. A flag now counts as a limit only if the clock was not held or power was near the limit.
* A conflicted `git stash pop` on the PC left three time-series files in the repository without database records; they are in `results/orphaned/` with a forensic note.
* **Leakage attempt 2 (M002)** at 2347 MHz had steady load, but the fan ran on automatic control rather than fixed: 0% at idle, 27–35% under load. The card held 63–64 °C for 13 of 15 minutes, and the driver dropped one clock step (2340 → 2332 MHz) with a ~4 W power step. Under the old ±15 MHz clock rule that step made power appear to *fall* with temperature (−0.22 W/K). The leakage fit now keeps one clock step only. The coefficient is still not identified, but the slope agrees with attempt 1: board power rises 0.12–0.14% per K, about a third of the registry's 0.35–0.37%.

## Definition of done (charter §16), initial platform

| # | Criterion | Status |
|---|---|---|
| 1 | Research questions documented | Done (`01`) |
| 2 | Credible literature review | Done for 50 verified sources; not a systematic review (`02`); targeted prior-art check for the newer results (`11`) |
| 3 | Architecture documented | Done (`03`) |
| 4 | Functioning simulation | Done |
| 5 | Reproducible baseline | Done (bitwise-reproducible per seed; bundles) |
| 6 | ≥ 2 strategies compared | Done (5 policies, paired CIs) |
| 7 | Energy and thermal models validated | Done analytically. **Against hardware, partly:** clock sensitivity is measured and used; the power-vs-clock shape is compared with a real GPU and found off by up to 0.09 of top-clock values; leakage is not yet measured (`10`) |
| 8 | Output-quality requirements evaluated | Partly: SLO and placeholder correctness only |
| 9 | Persistent, exportable logs | Done |
| 10 | Dashboard shows real simulation outputs | Done (static, generated from the database) |
| 11 | Interactive 3-D models linked to configuration | Done (Phase 2 lab). The cooling model is bound to the physics module, facility playback to stored runs; chip and photonic models are conceptual and labelled so; the energy-flow view is 2-D by choice |
| 12 | Numerical assumptions visible | Done (`04`, dashboard) |
| 13 | Failed experiments preserved | Done |
| 14 | Simulated vs measured distinguished | Done (provenance on every metric) |
| 15 | Reproduction instructions | Done (README, bundles) |
| 16 | Most / least promising approaches identified | Done: most promising is phase-aware DVFS; least is joint control without an accurate twin |
| 17 | Hardware feasibility assessment | Done: custom chip not warranted (`08`) |

## What should happen next

1. **M003, leakage at fixed fan speeds (you run it; about 55 minutes).** Every remaining real-silicon effect scales with the leakage slope: joint control's energy advantage (E009) and the chip-side cost of heat reuse (E012). Today it rests on a 4 K window. `python -m ueic calib plan-leak --clock 2347 --fans 100,80,60,45,30` prints the procedure; use 30% only if your fan tool allows it (`09` §8).
2. **Approach-dependent dry-cooler model.** The plant's fan power is proportional to heat rejected, which guaranteed E012's warm-water result. Model fan power against approach temperature (fan affinity laws, class F placeholders swept in E002 style), then re-ask E012's question.
3. **Adopt the design rule in the default joint controller.** Judge safety at the warmer of measured supply and setpoint, and use the throughput-first, power-second overload fallback. Then re-run E001C, E009 and E010 with it and the voltage-floor V–f form, so the headline numbers use the best available physics.
4. **Loop-model structure error and unnoticed degradation:** a stratified or delayed loop the controller models as one tank, and fouling the twin does not know about (E005/E008).
5. **Remaining Phase 3 items:** routing decided jointly with clocks and cooling; a facility power-cap scenario; synchronised training load steps (L46); multi-node placement with migration cost.
6. **Operation-level energy model** (FLOPs and bytes per prefill and decode phase) for gate 1 of the hardware feasibility assessment.
