# 28 · Publication roadmap

**Current readiness: not ready for a research publication.** The simulated findings are internally consistent and pre-registered, but they lack physical validation. Strong, physically validated prior work exists on the same questions (docs/26). What follows is a plan, not a claim.

## 1. Candidate contributions and their evidence gaps

| Candidate paper | Core claim it could make | Missing evidence | Venue type (examples of the *kind* of venue) |
|---|---|---|---|
| A. Measured energy per useful LLM result on consumer GPUs | How J/token, J/request and J per correct, on-time answer rank model × clock × concurrency choices differently | E017 sessions on ≥ 2 GPUs and ≥ 2 task families; a wall-meter boundary | Workshop on sustainable or efficient ML systems |
| B. Safety-filtered predictive control of liquid cooling with lagged plants | A filter independent of the optimiser keeps junction limits under lag, delay and forecast error, at no energy cost | A physical loop (thermal test vehicle); comparison with published MPC baselines; an ablation of the decision rule (E015 H3) | Building or data-centre energy conference |
| C. Thermal power budgets for placement under shared coolant | Closed-form horizon budget with downstream inlet coupling; when it helps and when it doesn't (E018) | Real multi-GPU telemetry or validated traces; sensitivity over the hand-set parameters; comparison with TAPAS-style policies | Systems or HPC workshop |
| D. Reproducible negative results in joint compute–cooling control | Pre-registered null and negative results (E012 design error, E014, E015 H2–H4, E016) and what they teach | Mostly ready; needs a careful related-work section and a clear-scope statement | Negative-results or reproducibility track |

## 2. Order of work

1. M003 (leakage), then E017 (inference energy). Both run on the user's GPU and are the cheapest physical evidence.
2. Thermal test vehicle (docs/23 §4) with flow and temperature instruments. Re-run E015's safety claims physically.
3. Systematic literature search for each candidate (docs/26 §3).
4. Write paper D or A first, because their evidence is closest to complete.

## 3. Standards before submission

* Every number traceable to a run ID, a commit and a data file.
* Physical and simulated results in separate figures and tables.
* Limitations (docs/27) stated in the paper, not only in the repository.
* No claim of novelty beyond what a systematic search supports. No patent language.
