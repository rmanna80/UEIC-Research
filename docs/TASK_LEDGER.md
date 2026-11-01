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
| 3 | E015 thermal futures | done | pre-registered (fd7ef1a); 1,320 runs; H1, H5, H6 supported; H2–H4 not (PHASE_REPORT) |
| 2 | Identification (ARX, step response, RLS), identifiability, active experiment design, drift detection, adaptive twins | done | docs/15; EKF/UKF considered and not built (RLS sufficient for the linear problem); applied to RTX 5070 warm-ups |
| 2 | E016 adaptive identification | done | pre-registered (353edb1); 160 runs; H1, H2, H6 supported; H3–H5, H7 not |
| 2 | M003 leakage sweep (user) | pending hardware | rerun with the guarded procedure (`calib plan-leak`) |
| 4 | Inference adapters (vLLM, Ollama, SGLang), tracing, energy accounting, quality evaluation, sessions, CLI | done (software) | docs/18; tested against mock HTTP servers and a synthetic engine; no live engine measured yet; SGLang adapter not exercised on a live server |
| 4 | E017 real LLM energy per useful result | pending hardware | pre-registered as a hardware protocol; operator procedure `infer plan`; needs the user's GPU, Ollama and GSM8K |
| 5 | Thermal capacity budgets, thermal-credit placement and admission, phase clocks, measured-quality router, batching | done (software) | docs/17; tested |
| 5 | E018 thermal scheduling | in progress | pre-registered (5e0b172); queued |
| 6 | Multi-node facility simulator (types, racks, manifold, series plates, caps, network) | done (software) | docs/19; validated against analytic cases, conservation, 1→4 scaling, dt |
| 6 | E020 multi-node joint control | in progress | pre-registered (5e0b172); queued |
| 7 | Grid modules: caps, compliance, deferral, cold storage, tariffs, carbon | done (software) | docs/21 |
| 7 | E021 heat reuse | in progress | pre-registered (2aaa6b6); first attempt interrupted by a session time limit at ~120/480 runs, aborted with reason, re-run superseding it |
| 7 | E022 grid coordination | in progress | pre-registered (4c14a91); queued |
| 8 | Fault injection, sensor validation, CUSUM, degradation, recovery modes, fault-aware supervisor | done (software) | docs/22 |
| 8 | E019 fault robustness | in progress | pre-registered (692b375); queued |
| 9 | Hardware adapters with mocks, modes, grants, guarded writes, replay; instrumentation document | done (software) | docs/23; no real actuator driver by design; no instrument connected |
| 10 | E024 integrated ablation | in progress | pre-registered; queued |
| 10 | Docs 12–29 | in progress | 25 (findings), 20 (heat reuse) and 29 (interview guide) written after the runs |
| 13 | ATLAS / KernelSmith adapters | blocked | no repository visible to this account (checked 2026-11-01); interface-only adapters raise PendingIntegration |
| 13 | Equivalent-kernel energy harness; E023 | pending hardware | harness tested with synthetic samples; protocol pre-registered |
