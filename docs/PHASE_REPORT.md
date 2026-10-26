# UEIC · Phase 0–1 report

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

## Definition of done (charter §16), initial platform

| # | Criterion | Status |
|---|---|---|
| 1 | Research questions documented | Done (`01`) |
| 2 | Credible literature review | Done for 43 verified sources; not a systematic review (`02`) |
| 3 | Architecture documented | Done (`03`) |
| 4 | Functioning simulation | Done |
| 5 | Reproducible baseline | Done (bitwise-reproducible per seed; bundles) |
| 6 | ≥ 2 strategies compared | Done (5 policies, paired CIs) |
| 7 | Energy and thermal models validated | Done analytically; **not** against hardware |
| 8 | Output-quality requirements evaluated | Partly: SLO and placeholder correctness only |
| 9 | Persistent, exportable logs | Done |
| 10 | Dashboard shows real simulation outputs | Done (static, generated from the database) |
| 11 | Interactive 3-D models linked to configuration | **Not done.** Phase 2. The 2-D cold-plate explorer bound to the physics module is a stopgap |
| 12 | Numerical assumptions visible | Done (`04`, dashboard) |
| 13 | Failed experiments preserved | Done |
| 14 | Simulated vs measured distinguished | Done (provenance on every metric) |
| 15 | Reproduction instructions | Done (README, bundles) |
| 16 | Most / least promising approaches identified | Done: most promising is phase-aware DVFS; least is joint control without an accurate twin |
| 17 | Hardware feasibility assessment | Done: custom chip not warranted (`08`) |

## What should happen next

1. **Measure the parameters that drive the conclusions** on one real GPU with NVML, read-only: clock vs throughput vs power for a compute-bound and a memory-bound kernel, and power vs die temperature at fixed clock and load. This replaces the highest-impact class F/E values with class B values from your own hardware.
2. **Add loop thermal mass and setpoint ramp limits**, then re-run E001 and E005.
3. **Add move suppression to the joint controller** and re-run E004; quantify the thermal-safety benefit that remains.
4. **Phase 2:** FastAPI over the store, then the 3-D cold-plate model bound to the same physics functions the explorer uses.
