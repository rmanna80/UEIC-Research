# Task ledger: UEIC next generation

Branch `research/ueic-next-generation`. Status values: **done** (code, tests, docs committed; experiments run if any), **in progress**, **pending** (not started), **blocked** (with the blocker), **pending hardware** (software and protocol ready, physical run needed). A stage is never marked done while any of its acceptance criteria (docs/12 §4) is unmet.

| Stage | Item | Status | Notes |
|---|---|---|---|
| 0 | Branch, baseline tests (123 passed), store verified, docs/12, this ledger | done | base commit 6096bb4 |
| 0 | Record M003 attempt 1 | done | data not pushed by the user; outcome recorded from the console output (PHASE_REPORT) |
| 1 | `ueic.physics` package with unchanged legacy behaviour | done | legacy file moved verbatim; bitwise E001 reproduction passes |
| 1 | NTU dry cooler with fan affinity; chiller part-load map; pump curve; transport delay; storage; heat reuse and heat pump; power delivery | done (components) | dry cooler and chiller wired in behind `plant_model = 1`; pump curve, delay, stratified tank, heat pump, reuse and power delivery tested as components, wired in when an experiment needs them |
| 1 | Parameter registry with uncertainty, validity ranges, extrapolation warnings; identifiability; validation utilities | done | `ueic/models/`; docs/13 |
| 3 | Forecasters, multi-step MPC, robust MPC, safety filter, fallback | done | `ueic/control/`, docs/16; chance-constrained MPC not implemented (no calibrated probability model) |
| 3 | E015 thermal futures | in progress | pre-registered (fd7ef1a), running |
| 2 | Identification (ARX, step response, RLS), identifiability, active experiment design, drift detection, adaptive twins | done | docs/15; EKF/UKF considered and not built (RLS sufficient for the linear problem); applied to RTX 5070 warm-ups |
| 2 | E016 adaptive identification | in progress | pre-registered (353edb1), queued after E015 |
| 2 | M003 leakage sweep (user) | pending hardware | rerun with the guarded procedure (`calib plan-leak`) |
| 4 | Inference adapters (vLLM, Ollama, SGLang), tracing, energy accounting, quality evaluation | pending | E017 needs the user's GPU |
| 5 | Thermal capacity budgets, thermal-credit scheduling, router, placement; E018 | pending | |
| 6 | Multi-node facility simulator; E020 | pending | |
| 7 | Heat-reuse economics (E021), grid coordination (E022) | pending | |
| 8 | Fault injection, detection, recovery; E019 | pending | |
| 9 | Hardware adapters with mocks, permissions, replay; instrumentation document | pending | |
| 10 | Integrated evaluation (E024), docs 13–29 | pending | |
| 13 | ATLAS / KernelSmith adapters; E023 | pending | repository access to be checked |
