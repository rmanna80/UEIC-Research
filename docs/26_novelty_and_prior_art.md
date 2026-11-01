# 26 · Novelty and prior art (next generation)

This document positions the next-generation work against prior work found in **targeted** searches (2026-11-01). It is not a systematic review. The earlier verified literature (50 sources) is in `02_literature_review.md`; the Phase 3 prior-art check is in `11_novelty_assessment.md`. **No claim of scientific novelty, patentability or publication readiness is made here.**

## 1. Closest prior work found

| Work | What it does | Evidence type | Relation to UEIC |
|---|---|---|---|
| [ETCInfer](https://arxiv.org/pdf/2609.15230) (Lu, Ge, Liang, Zhou, Wang; arXiv, Sept 2026) | Jointly chooses the CRAC setpoint, per-GPU frequency and micro-batch size for LLM inference, with a learning-based controller, under thermal and latency constraints | CFD simulation from real traces, plus an 8-consumer-GPU workstation | Very close to UEIC's core question (joint compute and cooling for AI inference). It is air-cooled (room setpoint), whereas UEIC models liquid loops, plant inertia and dry-cooler physics. Its reported savings (up to 33% total job energy) are from its own setup and are not comparable to UEIC's simulated numbers |
| [TAPAS](https://arxiv.org/html/2501.02600v1) (Stojkovic et al., Microsoft/UIUC, 2025) | Thermal- and power-aware VM placement, request routing and reconfiguration for LLM inference clusters, to oversubscribe cooling and power safely | Production traces on a large GPU cluster | Prior art for thermal/power-aware placement and routing (UEIC's E018 and model router). TAPAS works at cloud scale with real telemetry; UEIC's E018 is a small simulated cluster with an explicit thermal-budget formula |
| [Emerald AI field demonstration](https://arxiv.org/html/2507.00909v1) (Colangelo, Coskun et al., 2025) | GPU-cluster demand response through frequency scaling, job pausing and reallocation under performance-flexibility tiers; 25% power cut for 3 h, no SLA violations | 256-GPU A100 cluster, real grid events | Prior art and a physical benchmark for E022's question. UEIC adds cooling inertia and storage in simulation only |
| [Optimized thermal-aware job scheduling and control of data centers](https://ar5iv.labs.arxiv.org/html/1611.00522) (arXiv 1611.00522) | Joint thermal-aware scheduling and cooling control | Model and simulation | Long-standing prior art for joint scheduling and cooling: the idea is not new |
| [MPC for energy-efficient data centers with cold-aisle containment](https://ar5iv.labs.arxiv.org/html/1806.03375) (arXiv 1806.03375) | MPC of cooling in data centres | Model and simulation | Prior art for MPC in data-centre cooling: UEIC's MPC is not novel as a method |
| [Thermal-aware workload distribution with demand variations](https://arxiv.org/pdf/2308.12559) (arXiv 2308.12559) | Workload distribution aware of thermal state under varying demand | Model and simulation | Prior art for thermal-aware placement |

Older classics (thermal-aware scheduling, temperature-aware placement, DVFS for energy, CUSUM change detection, RLS identification, NTU heat-exchanger theory) are textbook or long-established. UEIC uses them, and does not claim them.

## 2. What is *specific* to UEIC (an implementation and framing claim, not a discovery claim)

1. **Thermal power budget over a horizon** for placement. The closed form ΔP_max(H) from the exact lumped solution, evaluated on every GPU whose inlet a placement warms in a series chain. Similar ideas may exist under other names; the search did not find this exact formulation, but the search was narrow.
2. **A safety filter independent of the optimiser**, sharing a supply upper bound built only from installation ratings, combined with MPC on a liquid loop with command delay and ramp limits (E015).
3. **Pre-registered, append-only simulation experiments with stated failure criteria.** These include negative results (E014, E015 H2–H4, E016 H3–H5, H7) that are kept and reported.
4. **Boundaries kept separate everywhere:** GPU board vs facility (estimated); energy vs cost vs carbon; measured vs simulated vs assumed.

## 3. What would be needed before any novelty claim

* A systematic search (Google Scholar, IEEE Xplore, ACM DL, arXiv) on each of the items in §2, with recorded queries and inclusion criteria.
* Physical evidence: at least M003, E017 and a thermal-test-vehicle loop experiment (docs/23).
* Comparison against the strongest published baselines on a shared benchmark where possible (for example, the Emerald AI flexibility tiers for E022-type experiments).

## 4. Honest summary

* The questions UEIC studies are active research areas with strong 2025–2026 prior art, some of it physically validated at scale.
* UEIC's contribution so far is a transparent, reproducible simulation platform, plus a small amount of real-GPU measurement. It has pre-registered results that show *where* joint control helps and where it does not under stated physics.
* That is useful engineering and teaching material. It is not yet a scientific discovery.
