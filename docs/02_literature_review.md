# 02 · Literature review: plan, matrix and synthesis

## Plan and method

* **Scope:** the twelve areas in charter §11. Priority went to peer-reviewed work, official documentation and reputable institutions, with foundational papers kept.
* **Verification rule:** a source enters the matrix only if it was confirmed on a page fetched during the review. Every row records its URL and how it was verified. Fields that could not be confirmed say *not verified* and were not filled from memory.
* **Extraction:** the matrix (`literature_matrix.csv`, 50 sources) records citation, year, venue, URL, evidence class, research question, method, hardware/workload, baseline, reported results (paraphrased), limitations, reproducibility, relevance, potential implementation, and how each was verified.
* **Companion files:** `reference_values.md` (published numbers usable as sanity checks, each with URL and class) and `eda_tools_status.md` (Verilator, Yosys and OpenROAD as of 2026-10-26).
* **Known gaps:** L27 (the most relevant IBM study) has unverified authors and venue. The Horowitz per-operation table (L14) was illegible, so its 45 nm figures come from the reproduction in L15. No reputable range for chiller second-law efficiency was found. The review is 50 sources, not a systematic review, so absence of prior art here is **not** evidence of novelty.
* **Corrections to the starting list:** Perseus is the system in *Reducing Energy Bloat in Large Model Training* (SOSP '24). The ASPLOS '24 power paper is titled *Characterizing Power Management Opportunities for LLMs in the Cloud*. Switch Transformer appeared in JMLR in 2022 and FrugalGPT in TMLR in 2024.

## Synthesis (charter §11 matrix questions)

### 1. What is already known
* **Leakage couples cooling to compute power.** Raising coolant temperature makes the plant more efficient but increases chip leakage (L26, simulation; leakage typically ~10% of chip power, possibly much more in future). A water-cooled GPU sweep measured power rising non-linearly with die temperature and fitted a leakage law (L28). On H100 nodes, liquid cooling lowered GPU temperatures and GPU power for the same work compared with air (L29, measured, platform-confounded at node level).
* **Clock control is a strong lever for memory-bound AI work.** LLM decode is memory-bound and nearly clock-insensitive (L09, preprint). Frequency locking and power capping trade small slowdowns for large power reductions (L03, L10), and training energy can be cut by tuning power limits and batch size (L04) or by slowing non-critical work (L05).
* **Data movement dominates energy at the circuit level** (L14, L15), which is why memory-bound kernels respond weakly to clock (roofline, L16).
* **Chiller-free warm-water cooling is deployed practice:** Aquasar at 60 °C with heat reuse and exergy accounting (L30), LRZ SuperMUC (L31), and vendor claims of 45 °C inlet (L33, class D only).
* **Model-predictive control works on real cooling plants** but has treated server power as an exogenous disturbance (L23).

### 2. What has already been implemented on the *joint* question
* **Coordinated IT and cooling control** has been studied since at least 2011 (L24). Its benefit depends on how heterogeneous the site's compute and cooling resources are.
* **Chip-scale co-optimisation of computation and cooling power** found an interior temperature optimum and up to 8.2% savings (L25).
* **Liquid cooling with temperature-dependent leakage** found the optimal coolant temperature is a discontinuous function of workload and weather, and that chillers sometimes beat free cooling (L27; bibliographic details unverified).
* **Thermal- and power-aware LLM scheduling** (L13, simulation, air-cooled) and **energy-aware LLM cluster reconfiguration** (L12, cooling not modelled) cover the compute side.

**Consequence for UEIC: the core trade-off it studies is not new.** The project cannot claim novelty for "jointly optimise coolant temperature against leakage" or for "co-optimise computation and cooling".

### 3. What remains unresolved (as far as this review found)
* Joint control evaluated **at a facility energy boundary** (conversion, pump, fans, chiller) for **modern liquid-cooled AI accelerators running LLM-like phase-mixed workloads**, against single-layer and uncoordinated baselines with paired statistics, and **measured**, not simulated.
* How robust model-based joint control is when its plant model is wrong, especially its safety margin under thermal limits.
* How model routing and cascades (L22) interact with DVFS and cooling at the energy-per-successful-task level, under real quality evaluations.

### 4. Promising directions
* Phase-aware DVFS (prefill vs decode, L09/L10/L11). It dominates the UEIC simulation as well, but that result leans on assumed V–f and β parameters that the literature only partly constrains.
* Warm-water operation with dry coolers, with leakage-aware setpoint selection (L26, L27, L30).
* Exergy-based accounting of reusable heat (L30) instead of netting heat against electricity.

### 5. Claims that need independent verification before use
* L12 headline savings (unclear whether from a real cluster or simulation); L13 (simulation); L33 (vendor); L35 photonic efficiency (projection); L36 neuromorphic gains (workload-specific, partly pre-silicon); L27 (bibliographic metadata).

### 6. Where UEIC might contribute something new (unconfirmed; needs a fuller prior-art search)
1. An **open, reproducible, pre-registered** benchmark that puts LLM-style DVFS, a liquid loop with dry cooler and chiller, and model routing at one facility boundary, with paired statistics, tamper-evident results and published negative results.
2. A documented **failure mode of uncoordinated control**. A cooling controller that raises supply temperature while treating chip power as fixed triggers leakage growth and hardware throttling in hot or degraded conditions (E001). How common this is in deployed controllers is unknown.
3. A **robustness result** that cuts the other way. When its twin underestimates leakage in hot ambient, the model-based joint controller becomes worse than uncoordinated control on both energy and thermal safety (E005). Model accuracy may therefore matter more than coordination.

Each would need a targeted prior-art search (thermal-aware DVFS and MPC robustness literature, ASHRAE/vendor control documentation) before any novelty claim.

## How the simulation compares with the literature (sanity, not validation)

| Quantity | UEIC (simulated, class E/F inputs) | Literature | Agreement |
|---|---|---|---|
| Energy saving from clock control vs full clock | 14–35% facility energy per successful task (E001) | ~23% energy for a 250→175 W cap with ~7% slowdown (L03); ~42% GPU energy in decode-heavy inference (L09) | Same order of magnitude; different boundaries |
| Chip temperature under liquid cooling at full load | ~52 °C peak at 18 °C supply (fixed policy) | 41–50 °C on liquid-cooled H100 (L29; inlet unknown) | Plausible |
| Leakage share of chip power | ~15% at 60 °C (registry default) | ~10% typical, higher projected (L26) | Inside the swept range |
| Cold-plate convective resistance | 15 mK/W at design flow | 7.6–10.4 mK/W total plate resistance on a 1 kW heater rig (reference_values.md) | UEIC is conservative (about 1.5–2× higher) |
| Joint vs uncoordinated savings | 0.3–1.4% (E001), up to ~3.9% with high leakage (E005) | Up to 8.2% at chip scale vs a DTM baseline (L25); ~9% cooling-cost estimate for MPC alone (L23) | Not directly comparable (different baselines and boundaries) |
| Memory-bound clock sensitivity β | 0.35 (range 0.15–0.60) | Decode latency changes <1% across clocks (L09), implying β ≈ 0 | **UEIC range excludes the measured value.** The DVFS saving is likely understated for decode-dominated serving. |
