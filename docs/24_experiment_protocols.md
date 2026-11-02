# 24 · Experiment protocols and registry

## 1. Rules every experiment follows

1. **Pre-registration.** The spec (research question, hypotheses with numeric criteria, null, variables, baselines, sample size, randomisation, measurement boundary, statistics, practical threshold, known limitations and confounders, disclosure of what was seen before) is committed to git **before** the first confirmatory run. Hypotheses are never edited after results are seen. A changed design is a new experiment.
2. **Append-only storage.** Runs are written to `results/ueic.sqlite`:
   * every run is sealed into a SHA-256 hash chain (`python -m ueic verify`);
   * config and code hashes are stored per run;
   * failed and aborted runs are kept with their reason;
   * a re-run *supersedes* the old record and never deletes it (E021 was interrupted and re-run this way);
   * an experiment that was registered but not finished can instead be **resumed in its own record** (`python -m ueic resume EXP_ID`, or `ueic queue`). `ueic/resume.py` refuses unless all of these hold:
     1. the experiment is still `running`, never finalised or aborted;
     2. the simulation-core hash equals the one stored at registration;
     3. every stored run (cell, seed, config hash, model-config hash) is regenerated exactly from the stored spec;
     4. re-simulating some of the completed runs (`--check`, spread evenly) reproduces their stored metrics and time-series hash exactly. Host wall-clock timings are the exception, since they are physical measurements and differ on every run.

     The core hash covers the single-node simulator only. For facility experiments (E018, E020, E022, E024), check 4 is what detects a changed facility simulator. Extending the core hash to `ueic/facility`, `ueic/scheduling` and `ueic/grid` is open work. It has to be a new field, because changing the existing hash would invalidate every stored record.

     Each resumption is logged in the research log with both hashes, and the finished summary counts `resumed_sessions`. Only pending runs are executed. Nothing already stored is rewritten.
3. **Pairing.** Every arm sees the same workload realisation per seed. Effects are paired relative differences d = (A − B)/B with two-sided 95% Student-t intervals over seeds.
4. **Practical significance.** Each spec states a threshold (1–10%). "CI excludes 0" alone is never called success.
5. **Exploratory vs confirmatory.** Exploratory runs (smoke tests, dry-runs in scratch databases) are disclosed in the spec or the write-up, and are never stored as confirmatory results.
6. **Provenance labels** on every metric: simulation, physical measurement, replay or estimate.
7. **Hardware protocols** (`"kind": "hardware_protocol"`) are refused by `ueic run`. They are executed by the operator with the procedure printed by `ueic infer plan`. UEIC never sets clocks, fans or power limits.

## 2. Registry of next-generation experiments

| ID | Question | Kind | Runs | Status |
|---|---|---|---|---|
| E015 | Multi-step MPC vs the measured-state rule across inertia, delay and forecast quality | simulation (single node) | 1,320 | completed; H1, H5, H6 supported; H2–H4 not |
| E016 | Adaptive identification under cold-plate drift | simulation | 160 | completed; H1, H2, H6 supported; H3–H5, H7 not |
| E017 | Real LLM energy per correct, on-time result: model × GPU clock × concurrency | hardware protocol | – | **pending hardware** (user's GPU, Ollama, GSM8K) |
| E018 | Thermal-credit vs four placement baselines, 5 conditions | simulation (facility) | 150 | completed; H2, H4, H5 supported; H1, H3 not (H1 met only with heterogeneous nodes) |
| E019 | Nominal vs fault-aware supervision under 13 faults | simulation | 260 | completed; H1–H5 supported; H6 not (degraded pump from t = 0 undetected) |
| E020 | Joint supply, valves and placement vs independent control, 1–16 nodes | simulation (facility) | 120 | completed; H1–H4 not supported; 16-node cells congested by the uplink model (exploratory diagnostic) |
| E021 | Heat-reuse economics with an approach-dependent dry cooler | simulation | 480 | completed; H2, H5, H6, H7 supported; H1, H3, H4 not. First attempt interrupted (infrastructure), aborted with its reason; second record superseded it and was resumed twice under checks (§1) |
| E022 | Demand-response cap: capping, deferral, cold storage; energy vs cost vs carbon | simulation (facility) | 50 | completed; H1, H2, H5 supported; H3, H4 not |
| E023 | Equivalent kernels: time vs GPU energy vs estimated facility energy | hardware protocol | – | **pending hardware**; ATLAS/KernelSmith sources pending access |
| E024 | 2⁴ factorial integrated ablation on 128 GPUs with a grid cap | simulation (facility) | 80 | completed; H1–H4 not supported (warm supply × thermal-credit conflict; overshoot at cap release). Resumed once under checks (§1) |
| M003 | Leakage over a wide temperature window at fixed clock | hardware (user) | – | **pending hardware** (guarded procedure ready) |

Earlier experiments (E001–E014, M001, M002) are unchanged and documented in `PHASE_REPORT.md` and `RESULTS.md`.

## 3. How to reproduce

```bash
git checkout main                                           # the next-generation branch is merged (PR #1)
pip install -r requirements.txt
python -m pytest -q                                         # full suite
python -m ueic run experiments/E015_thermal_futures.json --workers 2      # any simulated experiment
python -m ueic verify
python -m ueic report
python -m ueic dashboard
python experiments/make_spec_e0XX.py                        # regenerates a spec byte-identically from its script
```

Commands are listed one per line because Windows PowerShell 5.1 does not accept `&&`.

**Core hash change (2026-11-02).** All text I/O now names UTF-8 explicitly. Before this fix, Windows Python decoded specs as cp1252, so the same spec could be read as different text there than on Linux, and `ueic report` crashed writing `docs/RESULTS.md`. One core module (`experiment.py`, the spec loader) changed, so the simulation-core hash moved from `f0274eb299ad` to `d1582b117db4`. On Linux, where every stored run was produced, the change is a no-op: the bitwise E001 reproduction test passes, and no stored record is affected. Records made before the fix carry the old hash. Resuming one of them under the new code would be refused by check 2, which is the intended behaviour; none is unfinished.

Each run's config hash and the simulation-core hash identify what produced it (`python -m ueic hash`). Results reproduce bitwise per seed on the same platform, as the E001 reproduction test checks.

## 4. Statistical notes

* With 5 seeds a t-interval is wide. Where a hypothesis needs ±1% equivalence (E015 H3), a true difference of ~0.4% can still fail for lack of precision. This is reported as "not supported", not as "equivalent".
* Counts (late tasks, chip-seconds) are reported as seed means. Their distributions are skewed, so a mean driven by one seed is pointed out where it matters.
* No multiplicity correction is applied across hypotheses. Each is a separate pre-registered claim, and readers should weigh the number of tests.
