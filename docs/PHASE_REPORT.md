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
  * With severe fouling at 40 °C it used 3.5–4.3% *less* energy than the overheating alternative, and had about 5 more late tasks per run on seed means. That service cost is uncertain: the paired CIs include zero and one seed dominates.
* **The overload fallback** is a separate 4.5–4.7% saving, given clock-insensitive memory-bound work (beta_memory = 0 from a streaming kernel). It is not new: it is the phase-aware DVFS insight (L09–L11) applied when capacity runs short.
  * Earlier experiments gave independent and joint control the same all-clocks-to-maximum fallback, so their comparisons stay like-for-like.
  * Absolute clock-control savings were probably understated wherever overload occurred. This is inferred; the earlier experiments were not re-run.

All of this is simulation, and the controller knows the loop's mass and ramp exactly. E013 and E014 test the obvious objections.

**E013: a fixed thermal margin instead of lag-awareness (pre-registered, 300 runs, 0 failed).** The design covered the 12 slow-loop conditions at 30 and 40 °C. `joint_fb` planned against 80 − m °C for m = 0, 3, 6 and 9 K; joint_lag planned against 80 °C. Time above target was always measured against 80 °C.

| Hypothesis | Verdict | Result |
|---|---|---|
| H1: no margin overheats somewhere | **supported** | 4 of 12 conditions, 12,868 chip·s summed |
| H2: a 3 K margin is not enough | **supported** | summed chip·s above 80 °C by margin: 0 K 12,868, 3 K 8,394, 6 K 10,348, 9 K 7,232. No margin was safe everywhere, and the 9 K margin created small excursions (3 and 36 chip·s) at 30 °C with severe fouling |
| H3: joint_lag is cheaper than the smallest margin that makes joint_fb safe (9 K if none does) in ≥ 9 of 12 | **supported** by the protocol | no margin made joint_fb safe, so the comparison is against the 9 K margin, which still overheated in 6 of 12. joint_lag was cheaper in 10 of 12 (−0.8% to −7.3%) and equal in the 2 clean, 30 °C conditions. Against no margin it cost +1.7% with moderate fouling at 40 °C |
| H4: joint_lag's late tasks within 1 of the margin's | **not supported** | severe fouling at 40 °C: 7.6 vs 2.0 |
| H5: joint_lag never exceeds 80 °C | **supported** | 0 in 12 |

**E014: a wrong loop model, and no loop model (pre-registered, 180 runs, 0 failed).** The design covered the 6 slow-loop conditions at 40 °C. joint_lag ran with its loop mass, or its ramp limit, wrong by 4× either way. `joint_meas` has no loop model: it checks safety at the warmer of the measured supply and the setpoint.

| Hypothesis | Verdict | Result |
|---|---|---|
| H1: exact-model joint_lag never exceeds 80 °C | **supported** | 0 in 6 |
| H2: robust to each wrong model | **supported**, but the test had no power | 0 chip·s above 80 °C for all four. joint_lag never changed its supply setpoint in these runs (see below), so the loop model could not enter a decision |
| H3: joint_meas at most 10 chip·s above 80 °C, never throttles | **supported** | 0 and 0 |
| H4: joint_meas energy within ±1% and late tasks within 1 | **supported** | identical: 0.00% |
| H5: wrong models cost within ±1% | **supported** | identical: 0.00% (the controllers' configurations were confirmed different) |

What E011–E014 mean together (revised after a second independent audit):
* **joint_lag never moved the coolant on a slow loop.** In every joint_lag run on a dynamic plant in E011, E011B, E013 and E014 (and every joint_meas run), the supply setpoint changed 0 times. It stayed at the free-cooling temperature (25, 35 or 45 °C at 20, 30 or 40 °C ambient), and the chiller never ran. Heat was handled with flow (26–87 changes per run) and clocks.
  * The reason is in its check. Commanding colder water does not change the supply the chips see before the next decision, so the controller never credits the chiller, and the chiller only adds cost.
  * Steady-state joint control, where it overheated, did the opposite. With severe fouling at 40 °C it commanded 36–44 °C water through the chiller (running 42% of the time in seed 0) and chose clocks for water that took minutes to arrive.
  * So the safety in E011 came from **not counting on slow cooling**. A loop model that predicts *when* the cooling arrives was not what did it.
* **E014 could not test the loop model.** With the setpoint fixed, joint_lag's predicted supply equals the measured one for every candidate. A wrong loop mass or ramp, or no model at all (joint_meas), therefore gives identical decisions *in these conditions*.
  * The second audit ran exploratory checks (not pre-registered): a heavier load (S6 mean 0.8 instead of 0.65) and constructed states where the tank is below the preferred setpoint.
  * There, joint_lag and joint_meas made different decisions (69 of 240 constructed states), and wrong loop models changed joint_lag's setpoint behaviour.
  * In one severe-fouling seed, joint_lag had 595 late tasks against 4 for joint_meas. Both stayed below 80 °C.
* **A margin did not fix the steady-state controller (E013).** joint_fb with margins kept commanding chiller-cooled water (up to 93 setpoint changes per run) and still overheated. A lower target makes it command colder water, which a ramp-limited plant still delivers at its own rate. This is the explanation the plant model implies; it was not separately instrumented.
* **What survives is a safe but myopic rule.** Do not judge thermal safety at a colder setpoint that has not arrived; use the warmer of measured supply and setpoint. In the tested conditions this kept every chip below 80 °C (joint_lag in E011 and E013; joint_meas in E014's 6 conditions).
  * Its cost is that it never deliberately cools the loop to win back capacity. That plausibly explains the extra late tasks with severe fouling at 40 °C, and possibly the much larger service loss in the audit's heavier-load exploratory runs.
  * A controller that credits cooling *when it will arrive*, a multi-step MPC with the loop model and this rule as a safety constraint, is where a loop model could earn its keep. It is untested.
* Using the measured state in a safety constraint is ordinary control practice. This is a corrected design with a clear simulated failure mode behind it, not a discovery.

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

**M003 attempt 1 (2026-10-27, user's RTX 5070): no measurement.** This is from the console output the user reported; the session data was not pushed.
* The ten sessions (five load, five idle) ran without an active clock lock. The GPU boosted to 2670–2692 MHz at its 250 W power limit.
* The pasted procedure ran every step back to back, so the fan speed was never changed. The two load points `calib leak` kept both report 47% fan and 73 °C.
* `calib leak` refused to fit (2 usable points, at least 3 needed). Even with three, points at the power limit could not have measured leakage.
* Fixes, on `main` at 6096bb4:
  * each run checks itself after ~30 s against its `clk=` and `fan=` labels and the power limit, and stops early if they disagree;
  * `calib leak` drops power-limited and unapplied-fan points;
  * the procedure pauses before every fan change.

**Failures and corrections during this measurement:**
* The first desktop fit reported two failed fits (`v_min_ratio` = 0.3 and `kappa_leak` = 0.2, both exactly at their bounds) as class-B measurements. Acceptance rules R1–R3 now stop that. They were set after seeing that fit summary and before examining the raw data, and this is disclosed.
* The tool reported "clock held down by a power cap" at 35% of the power limit. On this GPU the driver sets that flag whenever clocks are locked. A flag now counts as a limit only if the clock was not held or power was near the limit.
* A conflicted `git stash pop` on the PC left three time-series files in the repository without database records; they are in `results/orphaned/` with a forensic note.
* **Leakage attempt 2 (M002)** at 2347 MHz had steady load, but the fan ran on automatic control rather than fixed: 0% at idle, 27–35% under load. The card held 63–64 °C for 13 of 15 minutes, and the driver dropped one clock step (2340 → 2332 MHz) with a ~4 W power step. Under the old ±15 MHz clock rule that step made power appear to *fall* with temperature (−0.22 W/K). The leakage fit now keeps one clock step only. The coefficient is still not identified, but the slope agrees with attempt 1: board power rises 0.12–0.14% per K, about a third of the registry's 0.35–0.37%.

## Next generation (branch `research/ueic-next-generation`, 2026-11-01)

Plan and stage status: `12_next_generation_architecture.md`, `TASK_LEDGER.md`. Every result in this section is **simulated**. Hypotheses were committed before each experiment ran and were not changed afterwards; a "not supported" verdict is reported as such.

### E015 · Thermal futures: multi-step MPC vs the measured-state rule (1,320 runs, 0 failed)

24 conditions: 4 scenarios × 3 plants (instant, 40 kg, 150 kg loop) × 2 command delays. 5 seeds. Details are in `16_predictive_control.md` and `RESULTS.md`.

| Hypothesis | Verdict | What happened |
|---|---|---|
| H1 safety | **supported** | The MPC and robust MPC never exceeded 80 °C in any condition, with any forecast (persistence, oracle, noisy, −30% biased, burst-blind), and never fell back. For comparison: steady-state `joint` exceeded 80 °C in 10 of 24 conditions; `independent` in 18 (139–1,068 chip-s); even `joint_meas` did in 2 (ambient ramp with 180 s delay, 37 chip-s; fouling with 180 s delay, 524 chip-s) |
| H2 anticipation reduces late tasks on slow loops | not supported | Burst scenario: 1.2 → 0.8 late tasks (seed means) in all four slow-loop conditions. That is 33% fewer, but the pre-registered "at least 1 fewer" was not met. The burst was too small to stress the baseline, so the test had little power (a design weakness) |
| H3 no value without inertia | not supported | On the instant plant without delay, the MPC (oracle) used 3.2% (fouling) and 1.5% (ambient ramp) less energy per success than `joint_meas`. In the burst scenario the difference was small (−0.4%) but its CI (−1.9 to +1.1%) is not inside ±1%. Part of the MPC's advantage therefore does not come from anticipating inertia. A likely cause, not yet tested, is the different decision rule: a backlog price and clocks chosen per step |
| H4 forecast quality | not supported | Late tasks summed over the slow-loop bursts: oracle 3.2 ≤ noisy 8.0, and oracle < persistence 4.8. But the **burst-blind** forecast caused 56 late tasks, 12× persistence. A confident forecast that misses bursts was much worse than no forecast |
| H5 no capacity from anticipation | supported | Overload: every arm had ~180 late tasks; MPC within ±15% of `joint_meas` |
| H6 cost of robustness | supported | `mpc_robust` cost +0.7% energy vs `mpc` (oracle), with peaks ~2 K lower |

**Descriptive:**
* The MPC's energy advantage over `joint_meas` grew with loop inertia and fault severity:
  * fouling: −3.1 to −4.9% (oracle) and −0.4 to −3.4% (persistence);
  * burst on the 150 kg loop: −3.1%;
  * overload: +0.5 to +1.1% (the cost of keeping more margin).
* A −30% biased forecast saved 9% energy in the burst scenario but caused 6× the late tasks. The biased forecast saving energy is a service failure, not an efficiency gain.

**Interpretation:**
* In this simulator, the predictive controller with an independent safety filter is the only arm that was safe everywhere.
* It is also cheaper than the safe measured-state rule where inertia or degradation matter.
* Its service benefit could not be shown, because the scenarios were too easy for late tasks.
* Forecast errors that hide demand are the main risk. A forecaster should be judged by how it fails, not only by its average error.
* All of this rests on the simulator's loop model, which the controller knows exactly. E016 and E019 relax that.

### E016 · Adaptive identification under simulated cold-plate drift (160 runs, 0 failed)

| Hypothesis | Verdict | What happened |
|---|---|---|
| H1 no harm without drift | supported | Recalibrating and adaptive twins within ±0.5% energy, no extra time above 80 °C |
| H2 drift makes a fixed model unsafe | supported | `joint_fixed` exceeded 80 °C in 4 of 6 drift conditions |
| H3 adaptation restores safety (≥ 80% less) | not supported | chip-s above 80 °C, fixed → adaptive: slow/35 °C 15 → 0; fast/25 °C 49 → 0; **fast/35 °C 778 → 182 (−77%)**; **step/35 °C 1,444 → 969 (−33%)** |
| H4 adaptive beats periodic after a step | not supported | 35 °C: adaptive 969 vs periodic 1,169 (better). 25 °C: both 0, so "fewer" cannot hold |
| H5 prediction error halved | not supported | Peak-temperature MAE, fixed → adaptive: fast and step drift 5.2 → 2.1 K and 4.5 → 2.0 K (better than half); slow drift 2.3 → 1.5 K (0.65) |
| H6 cost | supported | No energy penalty where the fixed model was safe |
| H7 drift detection | not supported | No false alarms without drift, but the Page–Hinkley test alarmed late or not at all after the step in some seeds of both step conditions |

**Interpretation:**
* Online resistance estimation removes most of the risk from gradual fouling.
* It does not remove the risk from an abrupt step at high ambient. Forgetting-factor RLS needs several intervals to move, and the controller keeps running hot in the meantime.
* A fault-aware layer that reacts to the residual directly, rather than through the twin, is the natural complement. That is what E019 tests.

### E021 · Heat-reuse economics with an approach-dependent dry cooler (480 runs, 0 failed)

**Run history.**
* **First attempt** (`E021-20261101T202413-b92693`): stopped by the session's background time limit after 132 completed runs. It was aborted with its reason, and its 348 unfinished runs are kept as failed.
* **Second record** (`…212421-8b3d80`): same spec, superseding the first. A second time limit stopped it at 302/480.
* **Checked resumption:** rather than abort again, checked resumption was built (`ueic/resume.py`, docs/24 §1) and the record was continued twice. Before each resumption:
  * the core hash matched registration (`f0274eb299ad`);
  * every stored run's configuration was regenerated exactly;
  * completed runs were re-simulated and matched bit for bit (3 distinct runs, 4 checks).
* **Code hash:** the package hash differs from registration (`3838e5ace73b` → `7f9f80817862`) only through the resumption code, the CLI and reporting. The simulation core is unchanged.
* **Conditions:** 2 worlds × 4 plants × 4 supply floors × 3 ambients, `joint_fb`, S1, 4 h, 5 seeds. Details are in `20_heat_reuse.md` §7.

| Hypothesis | Verdict | What happened |
|---|---|---|
| H1 NTU plant moves the no-floor optimum ≥ 1 K warmer | not supported (opposite sign) | NTU minus legacy: −0.8 to −1.9 K in all 6 world × ambient conditions |
| H2 but below 35 °C at 8 and 20 °C | supported | 12.2–23.7 °C; at 8 °C the supply sat on its 12 °C limit |
| H3 larger shift in the RTX world | not supported | −0.8 vs −0.8 K (8 °C), −1.3 vs −1.9 K (20 °C) |
| H4 40 °C floor cheaper with the NTU plant | not supported | within 0.11 percentage points of legacy in all four conditions, one in the wrong direction |
| H5 supply orders by fan cost | supported | e.g. 24.6 / 23.7 / 23.0 °C (RTX, 20 °C) |
| H6 44 °C floor < 0.10 kWh_el per kWh_th (RTX world) | supported | 0.037–0.055 |
| H7 cheaper than a heat pump | supported | 0.037–0.055 vs 0.147–0.226 |

**Descriptive.**
* The legacy plant's optimum was its fixed 5 K approach (supply = ambient + 5 K exactly), not a fan-cost balance.
* The NTU dry cooler reaches 3–4 K approaches cheaply, so the optimum moved *colder*. The chips ran cooler and leaked less.
* The NTU plant used 1.8–1.9% less energy per success than legacy without a floor, mostly fan energy.
* The chiller did no work in any run, and NTU fan energy was below 1% of grid energy. The cost of a warm floor is therefore almost all chip leakage: 44 °C floor +3.4–5.4% (RTX world) vs +10–16% (registry world) at 8–20 °C.
* A 35 °C floor gave no reusable heat (return ~39 °C).

**Interpretation.**
* With an approach-dependent dry cooler, warm water does not pay for itself through cooling savings in this model. Cooling was already almost free, and warmer chips leak more.
* Warm water is justified by the heat. In the RTX 5070-derived world, a 44 °C floor made all of the node's heat reusable at 0.02–0.055 kWh of extra electricity per kWh of heat, about a quarter of what a heat pump would need.
* Whether that pays depends on a heat price of at least 2–6% of the electricity price, and on a real heat customer.
* All of it scales with the leakage slope, so M003 decides how far this transfers to real silicon.
* The pre-registered expectation behind H1 and H3–H4 was wrong. It came from a back-of-envelope estimate disclosed in the spec.

### Run notes for E018, E019, E020, E022 and E024

* **Queue.** All five ran from one queue (`python -m ueic queue …`, 2 workers, 110-minute segments). E019, E022, E018 and E020 each ran start to finish inside one segment, with no interruption and no resumption. E024 was continued by checked resumption (see its section).
* **Simulator code after registration.** Two additions were made after some of these specs were committed and before any of their runs. Both are inert unless a spec turns them on:
  * The Stage 7 grid features (caps, tariffs, carbon, deferral, storage) were added to the facility simulator in the E022 commit (`4c14a91`), after E018 and E020 were registered (`5e0b172`). E018 and E020 do not turn them on.
  * The E019 supervisor stacks and fault parameters were registered in `0007bd9`, after the E019 spec (`692b375`). E019 cannot run without them, and their defaults leave every other policy unchanged (the bitwise E001 reproduction test passes). This changed the single-node core hash (`0c33547baa67` → `f0274eb299ad`). Every dry-run and every confirmatory run used `f0274eb299ad`.
  * The core hash covers the single-node simulator only. The facility simulator (`ueic/facility`, `ueic/scheduling`, `ueic/grid`) is covered by the package hash and by git history, which shows no change to it after `4c14a91`.
* **Dry-runs (exploratory, disclosed).** After registration and before the confirmatory runs, shortened dry-runs were run in a scratch database to check that each pipeline runs end to end:
  * E018: 10-minute runs, 2 seeds, 60 runs;
  * E019: 80-minute runs, 2 seeds, 104 runs;
  * E020: 10-minute runs, 2 seeds, 32 runs;
  * E022: 67-minute runs, 2 seeds, 20 runs.

  They are not results and are not in `results/ueic.sqlite`.
* **When the analysis code was written.** The analysis functions for E018, E019, E020 and E022 (`ueic/results_next.py`, commit `566cdb4`) were committed less than a minute after the last dry-run finished, so they were written with the dry-run outputs available. The hypotheses they implement were committed earlier, and each spec file has exactly one commit (`git log -- experiments/E0xx_*.json`). After the runs, the code was checked against the hypothesis text. One operational detail (E019 H5) is reported in that section.

### E019 · Fault-aware vs nominal supervision under 13 faults (260 runs, 0 failed)

Record `E019-20261102T013052-4c3e48`.
* **Setup:** S6 at 38 °C ambient, load 0.6, 2 h, 40 kg loop, RTX-world parameters, 5 seeds.
* **Arms:** `joint_meas` and `mpc`, each under a nominal supervisor (catches exceptions, holds the last action) and a fault-aware one.
* **Faults:** 8 window faults (2,400–4,200 s), 4 physical faults, and none.
* **Details:** `22_fault_tolerance.md` §8.

| Hypothesis | Verdict | What happened |
|---|---|---|
| H1 no alarm and no cost without a fault | supported | No alarm in any of the 10 no-fault fault-aware runs; energy per success +0.00% for both controllers |
| H2 window faults detected within 180 s | supported | 68 of 80 runs (85%; 80% needed). Every alarm came at or after onset. Late: clock stuck 7 of 10 (240–420 s), supply bias 3 of 10 (240–300 s), stale sensors 2 of 10 (240 s) |
| H3 never worse than nominal (+1 chip-s) | supported | chip-s above t_target, nominal → fault-aware: clock stuck 103 → 15 (`joint_meas`) and 245 → 27 (`mpc`); supply bias (`mpc`) 193 → 67; fouling 1,068 → 224 and 1,436 → 266; wrong model 398 → 0 and 709 → 0; degraded pump 605 → 605 and 389 → 353. Every other cell 0 → 0 |
| H4 clock stuck: at least 50% less time above target | supported | −85% (`joint_meas`), −89% (`mpc`) |
| H5 back to NORMAL within 300 s of the window ending | supported | 66 of 70 runs that left NORMAL (94%). The 4 misses were junction-bias runs that left DEGRADED 420–540 s after the window |
| H6 degradation detected | **not supported** | 21 of 30 runs (70%; 80% needed): fouling 10/10 (420–660 s after the step), wrong model 10/10 (180–240 s after the start), degraded pump 1/10 |

**H5, an operational detail.**
* The registered analysis uses the stored `diag_recovered_t`: the *first* return to NORMAL after the first alarm.
* For controller crash and solver infeasibility (20 runs), the mode bookkeeping recorded that first return at 2,580 s, inside the window. Those runs therefore count as recovered on a return that was not after the window.
* The seed-0 time series (it has no mode column, so SAFE is read from its action: flow 2.0, supply 12 °C) shows the SAFE action applied continuously from 2,460 to 4,200 s in all four crash and infeasibility stacks, and released at the next interval.
* Leaving these 20 runs out gives 46 of 50 (92%), so the verdict does not depend on them.

**Descriptive** (fault-aware vs nominal energy per success, seed means of paired ratios).
* **SAFE mode while a fault lasts:**
  * sensor dropout +21.9% (`joint_meas`) and +1.5% (`mpc`); the nominal MPC's own energy already rose 19% under dropout;
  * crash and solver infeasibility +20.5% and +18.9% (identical, since both are injected as exceptions);
  * clock stuck +12.2% and +11.6%;
  * communication failure +1.3% and +1.1%.
* **DEGRADED mode** (junction bias, stale sensors): 0.0%.
* **Physical faults:** fouling −1.1% and −1.3%, wrong model −0.7% and −1.4%, supply bias −0.8% and −0.9%.
* **No effect:** the 600 s valve delay had no effect on either stack.
* **Late tasks:** crash and infeasibility 0.4 → 0; otherwise unchanged (0–0.4).

**Interpretation.**
* In this simulator, the fault-aware layer adds what E016 lacked: it reacts to the residual and to the actuation checks directly. A clock that ignores its commands, or a supply sensor that reads 8 K low, was caught within minutes, and the stack fell back to the conservative action.
* It was never worse than the nominal stack on chip temperature, and it cost nothing without a fault.
* Its price is energy while a fault lasts: SAFE mode (full flow, coldest supply) cost 11.6–21.9% per success during crashes, stuck clocks and, for `joint_meas`, sensor dropout.
* Detection was slowest for faults whose evidence builds up over time (a stuck clock, a supply-sensor bias), not for faults that are visible at once (dropout, a crash).
* **Blind spot: faults present from the start.**
  * A pump degraded from t = 0 is learned as normal by the CUSUM baseline and does not change the identified resistance. It was detected in 1 of 10 runs, and fault-awareness did not reduce its time above target for `joint_meas`.
  * The spec stated this as a limitation; the result shows that it matters.
  * Catching it needs a reference that is not learned from the faulty plant, such as a commissioning baseline or a pump-curve check.

### E022 · Demand-response cap: capping, deferral, cold storage (50 runs, 0 failed)

Record `E022-20261102T013819-2b1ccf`.
* **Setup:** 32 GPUs, load 0.75, supply 25 °C, NTU plant, ambient 20 and 30 °C, 5 seeds.
* **Signals:** a 15 kW grid cap from 16:00 to 16:30; illustrative tariff and carbon shapes.
* **Arms:** 5 (none, cap, cap_defer, cap_storage, cap_defer_storage) at each ambient.
* **Details:** `21_grid_coordination.md` §7.

| Hypothesis | Verdict | What happened |
|---|---|---|
| H1 cap held to ≤ 2% of event energy | supported | 0.000 kWh above the cap at both ambients (event energy 7.34 and 7.44 kWh). Grid power rode the cap; with the EMS's one-step lag the largest overshoot was 2–12 W |
| H2 deferral keeps the on-time fraction | supported | `cap_defer` 0.983 vs `cap` 0.972 (20 °C) and 0.983 vs 0.969 (30 °C) |
| H3 storage adds ≥ 3% work during the event at 30 °C, < 1% at 20 °C | **not supported** | 30 °C: +0.7% [−0.8, +2.1]. 20 °C: −0.0%, so the expected null held |
| H4 at 30 °C storage uses more energy but costs less | **not supported** | Storage used *less* energy and cost less (seed means): 39.40 vs 40.07 kWh (−1.7%); 8.35 vs 8.64 (−3.3%) |
| H5 the cap binds without enforcement | supported | Exceeded in every seed: 1.05 kWh (20 °C) and 1.89 kWh (30 °C) above, peaks 5.8 and 7.9 kW over |

**Why H4 failed (descriptive).**
* Per seed, storage minus cap in grid energy was −2.13, +0.19, +0.93, +0.62 and −2.97 kWh. In 3 of 5 seeds storage used more energy, as §3 of doc 21 expects.
* The other two seeds dominate the mean. In those seeds, plain capping caused a backlog: on-time fraction 0.947 and 0.918, and energy per GPU-second of work 0.871 and 0.930 kJ (uncapped: 0.802 and 0.854). Storage left more of the cap to IT and avoided most of it.
* The cost difference has mixed signs too: storage cost more in seeds 2 and 3.
* So the seed-mean result reflects how much capping slows the work, which the hypothesis did not anticipate. It is not a property of storage thermodynamics.

**Why H3 failed (descriptive).**
* The store was small for this event. Charging at 4 kW_th for 30 minutes put 1.9 kWh_th into a 6 kWh_th store (5% loss).
* At 30 °C, the chiller used 3.33 kWh over the whole run with plain capping, so storage could displace only a small share of non-IT power during the event.
* At 20 °C the chiller never ran. The storage was charged (0.27 kWh_el) and never used.

**Descriptive.**
* **Holding the cap cost energy:** cap vs none, grid energy +1.7% (20 °C) and +0.6% (30 °C), cost +2.4% and +0.9%.
* **Deferral beat plain capping at both ambients:**
  * event energy fell (7.34 → 6.19 kWh at 20 °C, 7.44 → 6.63 at 30 °C);
  * total energy fell 0.9% and 2.1%;
  * cost fell 1.3% and 2.9%;
  * the on-time fraction rose.
* **Deferral counts:** `deferrals` counts per-step hold decisions (4,473 and 4,366), not jobs.

**Interpretation.**
* In this simulated EMS, converting a grid cap into an IT limit using the previous step's non-IT power held the cap to within a few watts.
* Deferring jobs whose deadlines allow it improved every metric relative to plain capping.
* The storage test was underpowered by design: the store was charged for half an hour at 4 kW_th, and the chiller was a small share of power. Its effect could not be separated from the backlog that plain capping created in two seeds.
* "Energy is not cost" (H4) was not demonstrated. A test of it needs a store sized to the chiller duty during the event, and enough seeds to average over backlog effects.

### E018 · Thermal-credit placement vs four baselines (150 runs, 0 failed)

Record `E018-20261102T014828-72b80b`.
* **Setup:** 32 GPUs (2 racks × 2 nodes × 8), 2 h of arrivals + 30 min drain, NTU plant, 5 seeds.
* **Arms:** `thermal_credit`, four baselines (`round_robin`, `least_loaded`, `power_aware`, `temperature_aware`), and the `thermal_placement` ablation (placement rule only, full clock, never holds).
* **Conditions:**
  * C1 uniform cooling;
  * C2 series pairs with unequal branches at 35 °C;
  * C3 the same at 40 °C;
  * C4 a 7 kW rack limit with bursts;
  * C5 heterogeneous nodes.
* **Details:** `17_thermal_credits.md` §8.

| Hypothesis | Verdict | What happened |
|---|---|---|
| H1 lower energy per on-time job than every baseline in C2, C3, C5 (CI < 0, mean ≤ −2%) | **not supported** | **C5:** met against all four: −26.5% (round-robin), −10.3% (least-loaded), −18.2% (power-aware), −8.3% (temperature-aware), all CIs below 0. **C3:** below 0 only against round-robin (−31.3%) and power-aware (−13.4%); the CIs against least-loaded (−14.4% [−53.5, +24.8]) and temperature-aware (−4.6% [−27.9, +18.6]) include 0. **C2:** worse than three baselines on the mean (+5.4% to +17.3%); no CI excludes 0 |
| H2 fewer chip-s above target (≤ temperature-aware everywhere; ≤ ½ least-loaded in C2, C3, C5) | supported | thermal-credit / temperature-aware / least-loaded: C2 8,757 / 28,864 / 31,721; C3 20,875 / 71,800 / 83,898; C4 199 / 926 / 2,581; C5 13,696 / 76,815 / 84,416; C1 all 0 |
| H3 on-time fraction within 2 points of the best baseline in C2, C3, C5 | **not supported** | C2 0.797 vs 0.954 (−15.7 points); C3 0.868 vs 0.951 (−8.3); C5 0.953 vs 0.996 (−4.3) |
| H4 no difference in C1 (expected null) | supported | −0.2% energy vs least-loaded; on-time 1.000 for both |
| H5 C4 on-time at least power-aware's | supported | 0.947 vs 0.938 |

**Descriptive.**
* **Placement alone did nothing for energy or heat.** `thermal_placement` was within its CI of `temperature_aware` in every condition (+0.0% to +3.1%; every CI includes 0), with similar time above target (C2 27,293 vs 28,864 chip-s). Thermal-credit's thermal benefit therefore comes from starting jobs at reduced clocks (202–303 jobs per run in C2, C3 and C5) and from holding them, not from where it puts them.
* **Thermal-credit used the least grid energy in C2–C5**, e.g. C2 39.8 vs 42.8 kWh (temperature-aware), C3 37.2 vs 43.5, C5 33.1 vs 37.8.
* **Throttling:** in C3 and C5 the four baselines spent 42,500–89,600 GPU-s in hardware throttling; thermal-credit spent 10,356 and 12,540.
* **The cost was waiting:** mean wait 234 s vs 60 s (C2), and fewer jobs on time.
* **Why the energy metric and the other results disagree:** energy per on-time job divides by on-time jobs. The same holds that saved energy and heat cost deadlines, and the metric charges for both.
* **Peak temperature:** the peak was not lower. The *time* above target was.

**Interpretation.**
* In this simulator, thermal credits do what they were designed to do thermally: 3–6× less time above target, much less hardware throttling, and the lowest grid energy.
* Under tight thermal stress (series pairs at 35–40 °C supply), they pay for it with deadlines.
* Under the registered metric, that trade was a net win only with heterogeneous nodes (C5).
* The credit parameters were set by hand, not tuned. A less conservative setting might move the trade, but testing that needs a new experiment.

### E020 · Joint supply, valves and placement vs independent control, 1–16 nodes (120 runs, 0 failed)

Record `E020-20261102T022118-3ee654`.
* **Setup:** 1, 4 and 16 nodes (8 GPUs each), series pairs, load 0.75, ambient 20 and 30 °C, NTU plant, 5 seeds.
* **Arms:**
  * `independent`: 25 °C supply, equal valves, least-loaded;
  * `warm`: warmest-safe supply;
  * `warm_valves`: + heat-proportional valves;
  * `joint`: + thermal-credit.
* **Details:** `19_multi_node_facility.md` §9.

| Hypothesis | Verdict | What happened |
|---|---|---|
| H1 joint ≥ 3% lower energy per on-time job at every scale and ambient | **not supported** | **1 node:** met (−7.3% [−14.2, −0.5] at 20 °C; −16.4% [−23.7, −9.1] at 30 °C). **4 nodes:** +22.0% and +11.1%. **16 nodes:** +16.4% and +8.4%. The 4- and 16-node CIs are wide and include 0 |
| H2 on-time within 1 point | **not supported** | joint vs independent: 0.919 vs 0.972 (1 node), 0.823 vs 0.995 (4), 0.475 vs 0.615 (16); identical at both ambients |
| H3 benefit at 16 nodes ≥ 1-node benefit − 1 point | **not supported** | The benefit reversed sign above 1 node (H1 values) |
| H4 heat-proportional valves beat equal valves at 16 nodes | **not supported** | +2.8% [−2.5, +8.1] (20 °C), +1.8% [−3.3, +6.8] (30 °C). The valves raised pump energy (1.39 → 2.30 kWh), lifted the warmest-safe supply by 1.0 K, and introduced time above target (0 → 18.8 chip-s) and throttling (0 → 9.6 GPU-s) |

**The cooling component on its own** (`warm` vs `independent`; same scheduler, so the same jobs finish; ratios of seed means):

| | 1 node | 4 nodes | 16 nodes |
|---|---|---|---|
| 30 °C ambient | −4.9% | −3.9% | −4.0% |
| 20 °C ambient | +3.3% | +1.5% | +0.5% |

* At 30 °C, a 25 °C supply needs the chiller (15.9 kWh at 16 nodes), and warm supply cut that to 5.8 kWh.
* At 20 °C neither arm used the chiller, and warm supply only added leakage (IT energy +1.8% at 16 nodes).
* This agrees with E021: warm water saves energy only when it avoids chiller work.

**The 16-node cells were congested by the network model.**
* With `independent` at 16 nodes, only 61.5% of jobs finished on time and 18% were unfinished at the end, yet utilisation was 0.90. Energy per GPU-second of work was 1.25 kJ, against 0.73 kJ at 4 nodes.
* An exploratory diagnostic (not stored, script `experiments/diagnostics/e020_uplink_check.py`) re-ran seed 1 with and without the rack-uplink limit (4 cross-node jobs per rack, class G):
  * with the registered limit it reproduced the stored result (on-time 0.491);
  * without the limit: on-time 1.000, utilisation 0.61, energy per on-time job 342 instead of 988 kJ.
* Least-loaded placement spreads jobs across nodes as the cluster fills, and the uplink limit then slows them.
* So at 16 nodes, E020 measures network congestion as much as cooling, and the scale comparison (H3) is confounded by it.
* The 4-node cells (one rack) were not congested under `independent` (on-time 0.995).

**Interpretation.**
* "Joint" control as registered did not beat independent control, except on one node.
* Its losses came from two places:
  * thermal-credit's holds, which cost on-time jobs as in E018;
  * heat-proportional valves, which added pump work without enabling a materially warmer supply.
* The supply-temperature component alone behaved as E021 predicts: −4 to −5% at 30 °C, a small penalty at 20 °C.
* A fair test of joint control at scale needs a network-aware placement rule, or a topology where the uplink does not saturate. That is a new experiment, not a reinterpretation of this one.

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
3. **A controller that credits cooling when it arrives.** A multi-step MPC over the loop model, keeping "judge safety at the warmer of measured supply and setpoint" as a hard constraint. Pre-register it against joint_lag and joint_meas in conditions where the setpoint *has* to move: heavier load, rising ambient, cold start. That is where the loop model can matter and where the myopic rule loses capacity (the second audit's exploratory runs). Use the throughput-first overload fallback everywhere. Then re-run E001C, E009 and E010 with the best controller and the voltage-floor V–f form.
4. **Loop-model structure error and unnoticed degradation:** a stratified or delayed loop the controller models as one tank, and fouling the twin does not know about (E005/E008).
5. **Remaining Phase 3 items:** routing decided jointly with clocks and cooling; a facility power-cap scenario; synchronised training load steps (L46); multi-node placement with migration cost.
6. **Operation-level energy model** (FLOPs and bytes per prefill and decode phase) for gate 1 of the hardware feasibility assessment.
