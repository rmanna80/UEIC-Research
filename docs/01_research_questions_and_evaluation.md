# 01 · Research questions, evaluation criteria and baseline methodology

## Research questions → where they are addressed

| # | Question (charter §2) | Phase 1 status | Experiment |
|---|---|---|---|
| RQ1 | How much energy can software optimisation alone save? | Simulated (DVFS, routing) | E001 `compute_only`, E003 |
| RQ2 | What additional savings come from coordinating computation and cooling? | Simulated | E001 `independent` vs `joint` |
| RQ3 | Can thermal-aware scheduling increase useful throughput? | Partly (thermal limits + throttling counted); throughput-maximisation not yet a policy objective | E001 S6 |
| RQ4 | Can model routing reduce energy without degrading quality? | Simulated with a placeholder quality model; break-even derived analytically | E003 |
| RQ5 | Can improved memory architecture reduce data-movement energy? | Not modelled (needs an operation-level energy model) | Phase 5 |
| RQ6 | Could photonic/neuromorphic/in-memory hardware help selected workloads? | Literature only | `literature_matrix.csv` |
| RQ7 | Could waste-heat recovery reduce overall energy requirements? | Reusable heat and its exergy reported, but no heat user is modelled, so no net claim | E001 metrics |
| RQ8 | When would a custom chip outperform existing hardware? | Assessed qualitatively from Phase 1 evidence | `08_hardware_feasibility.md` |
| RQ9 | What physical constraints fundamentally limit the architecture? | Landauer bound, Carnot COP bound, energy conservation encoded and tested | `tests/test_physics.py` |
| RQ10 | Which combinations help and which add excessive overhead? | Simulated factorial (5 policies × 6 scenarios) + sensitivity | E001, E002 |

## Evaluation criteria (fixed before running E001–E005)

1. **Primary metric:** facility energy per successful task, `E_per_success_kJ`.
2. **Comparison method:** paired by seed (every policy sees the identical task stream and identical outcome random numbers). Per-seed relative difference `d = (A − B)/B`; mean and two-sided 95 % Student-t CI.
3. **Practical significance:** a difference is called *meaningful* only if the whole 95 % CI lies beyond ±1 %. CIs that exclude zero but straddle 1 % are reported as *detectable but not confirmed ≥ threshold*. *Disclosure:* this threshold was chosen after one smoke run (see the research log).
4. **Guards (a saving does not count if it breaks these):**
   * success rate and SLO violations no worse than the comparator;
   * zero chip-seconds throttled by hardware protection in nominal scenarios;
   * chip-seconds above the 80 °C target reported, not hidden.
5. **Robustness:** a conclusion is labelled *robust* only if its sign survives every one-at-a-time variation in E002 and the model-mismatch cases in E005.
6. **Numerical validity:** results stand only if E004 shows < 0.5 % change between dt = 0.5 s and 1 s.

## Baseline methodology

* **Conventional baseline (`fixed`).** The accelerator runs at full clock when busy and drops to its minimum clock when idle (as current hardware does by default). Coolant supply is fixed at 18 °C at design flow. 18 °C stands in for a conventional chilled-water setpoint and is itself a swept assumption (12–27 °C in E002).
* **Single-layer baselines.** `compute_only` (energy-aware DVFS, fixed cooling) and `cooling_only` (full clock, optimised cooling) isolate each layer's contribution.
* **Uncoordinated combination (`independent`).** Both single-layer controllers run at once with no shared model. The compute side assumes a fixed junction temperature. The cooling side treats the measured chip power as fixed, so it does not anticipate the leakage response to its own setpoint. This is the comparator for the joint-optimisation claim.
* **Joint (`joint`).** One model-predictive controller grid-searches clocks per job class, supply temperature and flow against a steady-state digital twin. Its objective is grid power at the planned demand, subject to utilisation ≤ 0.85 and steady junction temperature ≤ 80 °C.
* **Same constraints for all.** Same thermal target, same hardware protection, same control interval, same demand estimator.

## Experiment register

| Key | Purpose | Cells |
|---|---|---|
| E001 | Policy benchmark | 6 scenarios × 5 policies × 10 seeds |
| E002 | One-at-a-time sensitivity on 25 uncertain parameters | 51 variants × 3 policies × 3 seeds |
| E003 | Routing cascade vs analytic break-even | 7 variants × 2 policies × 10 seeds |
| E004 | Time-step convergence | 4 dt × 2 policies × 2 seeds |
| E005 | Digital-twin mismatch robustness | 6 variants × 2 policies × 2 scenarios × 5 seeds |
| E006 | Dynamic coolant loop (v2 after a confound in v1) | 3 plant models × 4 policies × 3 scenarios × 10 seeds |
| E007 | Move suppression and time-step sensitivity | 7 threshold/dt variants × 2 scenarios × 10 seeds (joint only) |
| E008 | Self-correcting joint control under twin mismatch | 7 cases × 3 policies × 2 scenarios × 5 seeds |
| M001 | GPU calibration measurement: RTX 5070, 2026-10-26 | 12 sessions on one GPU; results in `10` |
| E001C | E001 with M001's measured clock sensitivity | 6 scenarios × 5 policies × 10 seeds, seed-paired against E001 |

Full pre-registered specs, including hypotheses, variables, controls and limitations, are in `experiments/*.json`. They are frozen in the database at registration.
