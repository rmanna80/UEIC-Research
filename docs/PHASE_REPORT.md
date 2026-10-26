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

**Failures and corrections during this measurement:**
* The first desktop fit reported two failed fits (`v_min_ratio` = 0.3 and `kappa_leak` = 0.2, both exactly at their bounds) as class-B measurements. Acceptance rules R1–R3 now stop that. They were set after seeing that fit summary and before examining the raw data, and this is disclosed.
* The tool reported "clock held down by a power cap" at 35% of the power limit. On this GPU the driver sets that flag whenever clocks are locked. A flag now counts as a limit only if the clock was not held or power was near the limit.
* A conflicted `git stash pop` on the PC left three time-series files in the repository without database records; they are in `results/orphaned/` with a forensic note.

## Definition of done (charter §16), initial platform

| # | Criterion | Status |
|---|---|---|
| 1 | Research questions documented | Done (`01`) |
| 2 | Credible literature review | Done for 43 verified sources; not a systematic review (`02`) |
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

1. **Measure leakage properly** with the improved warm-up (`09`, section 3): the second-highest clock, a fixed fan speed, 15 minutes from a cold card. The indicative slope says the simulator may overstate leakage's temperature sensitivity 2.5–4×. That would shrink the benefit of colder coolant, one of the mechanisms behind joint control's advantage, so this is now the measurement with the highest information value.
2. **Give the simulator a measured voltage–frequency form.** The straight-line form cannot follow the measured curve. A form with a voltage floor and a steep top section, fitted once leakage and static power are separated, would make DVFS magnitudes trustworthy; re-run E001C with it.
3. **Make the joint controller lag-aware.** Plan over a short horizon with the tank and ramp model instead of a steady state. E006 shows that steady-state planning is what costs its thermal margin under loop lag, and that the temperature-feedback correction does not fix this.
4. **Remaining Phase 3 items:** routing decided jointly with clocks and cooling; a facility power-cap scenario; multi-node placement with migration cost.
5. **Operation-level energy model** (FLOPs and bytes per prefill and decode phase), to estimate the data-movement share that gate 1 of the hardware feasibility assessment needs.
