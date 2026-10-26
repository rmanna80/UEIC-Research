# UEIC reference values for sanity checks

Every value below was read on a page fetched during the literature review session of 2026-10-26. Evidence classes: A established physical principle or definition, B published experimental result, C published simulation result, D existing commercial capability or vendor/institutional claim, E engineering extrapolation. Source IDs (L##) refer to `docs/literature_matrix.csv`.

Use these values for sanity checks and scenario bounds. They are not calibration targets for any particular facility.

## Physical constants and fluid properties

| Quantity | Value | Notes | Class | Source (verified) |
|---|---|---|---|---|
| Boltzmann constant k | 1.380649 × 10⁻²³ J/K (exact) | Exact under the redefined SI (NIST dates approval to Nov 2018) | A | https://www.nist.gov/si-redefinition/kelvin-boltzmann-constant |
| Landauer bound kT ln 2 at 298.15 K | ≈ 2.853 × 10⁻²¹ J/bit (≈ 0.0178 eV) | Computed from k above. Bennett (L40) gives "about 3×10⁻²¹ J at room temperature". | A (derived) | k from NIST, above; Bennett: https://www.cs.princeton.edu/courses/archive/fall06/cos576/papers/bennett73.html |
| Specific heat of liquid water, cp, 298.15 K | ≈ 75.4 J/(mol·K) ≈ 4.184 J/(g·K) | Computed from the NIST WebBook Shomate coefficients for liquid water (298–500 K; Chase 1998, NIST-JANAF): A=-203.6060, B=1523.290, C=-3196.413, D=2474.455, E=3.855326, with t=T/1000 and M=18.0153 g/mol. The same equation gives ≈4.178 J/(g·K) at 40–45 °C. NIST does not list a single tabulated value; the number here is our evaluation of its equation. | A (reference data) | https://webbook.nist.gov/cgi/cbook.cgi?ID=C7732185&Mask=2#Thermo-Condensed |
| Specific heat of liquid water at 25 °C (cross-check) | 4.1787 J/(g·K) (75.28 J/(mol·K)) | Wikipedia data page; that row cites no source. It agrees with the NIST-derived value to about 0.1%. | A (secondary) | https://en.wikipedia.org/wiki/Water_(data_page) |
| 1 ton of refrigeration | 12,000 Btu_IT/h = 3.516853 kW (exact) | Needed to convert kW/ton benchmarks to COP: COP = 3.516853 / (kW/ton). The source page does not give this formula; it follows from the definition. | A (definition) | https://en.wikipedia.org/wiki/Ton_of_refrigeration |

## GPU / accelerator

| Quantity | Value | Notes | Class | Source (verified) |
|---|---|---|---|---|
| NVIDIA H100 SXM max TDP | Up to 700 W (configurable) | H100 NVL: 350–400 W (configurable) | D | https://www.nvidia.com/en-eu/data-center/h100 |
| H100 SXM memory / bandwidth | 80 GB / 3.35 TB/s | Same page | D | https://www.nvidia.com/en-eu/data-center/h100 |
| H100 SXM dense-vs-sparse note | FP16/BF16 Tensor 1,979 TFLOPS and FP8 3,958 TFLOPS **with sparsity** | Dense figures are not on the page. Do not use these as dense peaks. | D | https://www.nvidia.com/en-eu/data-center/h100 |
| Google TPU v1 | 65,536 8-bit MACs, 92 TOPS peak, 28 MiB on-chip memory | L38 | B | https://research.google/pubs/in-datacenter-performance-analysis-of-a-tensor-processing-unit/ |

## Energy per operation (45 nm, 0.9 V; Horowitz)

The per-operation figure in Horowitz's ISSCC 2014 paper was illegible in both fetched copies. The values below come from the verified reproduction in Han et al. 2015 (L15), which cites Horowitz. The body-text figures come directly from Horowitz (L14).

| Operation (45 nm) | Energy | Class | Source (verified) |
|---|---|---|---|
| 32-bit int ADD | 0.1 pJ | B | https://arxiv.org/pdf/1506.02626 (Fig. 1) |
| 32-bit float ADD | 0.9 pJ | B | same |
| 32-bit register file access | 1 pJ | B | same |
| 32-bit int MULT | 3.1 pJ | B | same |
| 32-bit float MULT | 3.7 pJ | B | same |
| 32-bit SRAM cache access | 5 pJ | B | same |
| 32-bit DRAM access | 640 pJ (≈6400× int add, ≈170× float mult) | B | same |
| DRAM access (Horowitz body text) | 1–2 nJ | B | https://pages.cs.wisc.edu/~markhill/restricted/isscc2014_horowitz_power_scaling.pdf |
| Cache fetch / instruction (Horowitz body text) | ~20 pJ per cache fetch; ~70 pJ per instruction | B | same |

Caveat: these are 45 nm numbers. Scaling them to HBM3 and 4–5 nm nodes is an engineering extrapolation (class E) and must be labeled that way.

## LLM inference power and energy (measured)

| Quantity | Value | Context | Class | Source (verified) |
|---|---|---|---|---|
| Energy per output token, LLaMA-65B | ~3–4 J/token | A100/V100 sharded inference. The source passage is ambiguous about generation length. | B | https://ar5iv.labs.arxiv.org/html/2310.03003 |
| Power cap 250 W → 175 W (A100) | ≈ −23% energy, ≈ +6.7% inference time (avg) | LLaMA-65B, GSM8K, batch 64 | B | same |
| Power cap 250 W → 150 W (A100) | ≈ −33 to −35% energy, ≈ +19.5% time (avg) | same | B | same |
| Inference frequency locking | up to ~20% peak-power reduction for up to ~7% performance loss | Model dependent. For BLOOM, ~100 MHz below max cost <2%. | B | https://homes.cs.washington.edu/%7Epatelp1/papers/llmpower-asplos24.pdf |
| Decode share and clock sensitivity | Decode takes 77–91% of time; decode latency changes <1% across 180–2842 MHz; ~42% average GPU energy saving at 180 MHz with ~1–3% end-to-end latency increase | Single RTX PRO 6000 (Blackwell), offline replay, preprint | B | https://arxiv.org/abs/2501.08219 |
| Median production text prompt (Gemini Apps) | 0.24 Wh; ~0.26 mL water | Full-stack boundary incl. idle capacity and facility overhead. Operator-reported. | B | https://arxiv.org/abs/2508.15734 |

## Temperature–power coupling

| Quantity | Value | Context | Class | Source (verified) |
|---|---|---|---|---|
| GPU leakage functional form | P_leak ≈ a·T²·exp(−b/T) + c, fitted b ≈ 3210 (T in K), a ≈ 1.0 | Tesla K20, water-cooled sweep. Refit before use on modern GPUs. | B | https://arxiv.org/abs/1407.8116 |
| GPU efficiency vs die temperature | 13.5 → 12.4 GFLOPS/W from 30 → 90 °C at 705 MHz | same | B | same |
| Dynamic power slope vs clock | ~0.14 W/MHz | same (K20) | B | same |
| Chip leakage share of power | typically ~10%, possibly up to ~50% in future (2011 projection) | Modeling paper | C | https://pure.ul.ie/en/publications/from-chip-to-cooling-tower-data-center-modeling-chip-leakage-powe-2/ |
| H100 GPU temperature under load, liquid vs air | 41–50 °C (direct-to-chip liquid) vs 54–72 °C (air) | 8× H100 HGX nodes, GPU Burn | B | https://arxiv.org/html/2507.16781v1 |
| H100 node power at full load, liquid vs air | 6.99 kW vs 8.16 kW | GPU Burn. Nodes also differ in platform, so this is confounded. | B | same |

## Liquid cooling temperatures and thermal resistance

| Quantity | Value | Context | Class | Source (verified) |
|---|---|---|---|---|
| ASHRAE liquid cooling classes (current) | W17, W27, W32, W40, W45, W+; the number is the upper facility-supply limit in °C; W+ means >45 °C | Higher classes may allow dry coolers | D/E (industry guideline) | https://www.energy.gov/sites/default/files/2024-07/best-practice-guide-data-center-design.pdf ; https://www.thegreengrid.org/resources/glossary/W |
| ASHRAE 2011 classes (legacy) | W1 2–17 °C, W2 2–27 °C, W3 2–32 °C, W4 2–45 °C (water-side economizer), W5 >45 °C (building heating) | Legacy scheme | D/E | https://datacenters.lbl.gov/sites/default/files/ASHRAE%20Thermal%20Guidelines_%20SVLG%202015.pdf |
| SuperMUC (LRZ) warm-water inlet / outlet | inlet up to 40 °C; outlet up to 70 °C | Production HPC. "Up to 40% energy reduction" is an institutional claim. | D | https://doku.lrz.de/decommissioned-supermuc-10746010.html |
| LRZ warm-water loop | up to 55 °C, 8 MW; chiller-free year-round with cooling surcharge ~10% | Institutional page | D | https://lrz.de/wir/green-it_en/ee-infrastruktur_en |
| Aquasar hot-water cooling | coolant 60 °C, no chillers; chip-to-coolant ΔT ~15 °C (water) vs ~35 °C (air); heat recovery 80%, exergetic efficiency 34% at 60 °C | Peer-reviewed prototype study | B | https://ideas.repec.org/a/eee/energy/v43y2012i1p237-245.html |
| NVIDIA Rubin platform coolant inlet | up to 45 °C inlet, ~55 °C outlet; dry coolers, chiller-less in favorable climates | Vendor claim | D | https://blogs.nvidia.com/blog/liquid-cooling-ai-factories/ |
| Cold-plate thermal resistance (direct-to-chip, single-phase water) | 7.6 K/kW (Cu diamond-pin) and 10.4 K/kW (CuW diamond-pin) at ~4.1 kPa pressure drop; tested at 1,000 W over 75 × 75 mm, flow 1.7–3.8 L/min | Measured on a test loop with cartridge heaters (not a GPU). Inlet temperature for the test not stated. | B | https://www.electronics-cooling.com/2026/04/high-performance-copper-tungsten-cold-plates-for-direct-to-chip-single-phase-liquid-cooling/ |
| Microchannel heat sink (Tuckerman & Pease) | 790 W/cm² with 71 °C rise above inlet water; ~0.09–0.11 °C/W for 1 cm² (source text partly garbled) | Lab silicon microchannels, 1981 | B | https://confluence.slac.stanford.edu/download/attachments/163485154/Pease1981.pdf?api=v2 |

## Facility plant efficiency

| Quantity | Value | Context | Class | Source (verified) |
|---|---|---|---|---|
| Cooling system efficiency benchmarks | 1.1 kW/ton (standard), 0.8 (good), 0.6 (better) → COP ≈ 3.2, 4.4, 5.9 | COP conversion uses 3.516853 kW/ton (our arithmetic) | D/E | https://www.energy.gov/sites/default/files/2024-07/best-practice-guide-data-center-design.pdf |
| PUE benchmarks | 1.6 (standard/average), 1.4 (good), 1.1 (better); Uptime 2022 survey average 1.55 | same | D/E | same |
| Chilled water temperature | ≥55 °F (≈12.8 °C) supply improves chiller efficiency (not quantified) | same | D/E | same |
| Water-side free cooling suitability | wet-bulb below 55 °F for ≥3,000 h/yr | same | D/E | same |
| Google datacenter PUE used in carbon study | 1.11 (Iowa), others 1.09–1.12; US average 1.58 (2018), 1.59 (2020) | L01 | B | https://www.alphaxiv.org/abs/2104.10350.md |
| Cooling energy sensitivity to chiller temperature | "~4% less cooling energy per +1 °C" | Second-hand industry estimate quoted in a vendor blog. **Do not use without the primary source.** | E (unverified primary) | https://blogs.nvidia.com/blog/liquid-cooling-ai-factories/ |

## Values requested but NOT verified (omitted from the tables)

- **Second-law (exergetic) efficiency of chillers:** no reputable page giving a range was fetched. The only exergy figure verified is Aquasar's heat-reuse exergetic efficiency of 34%.
- **Thermal resistance of GPU cold plates on real GPUs (H100/B200):** none found. The cold-plate value above comes from a heater test vehicle.
- **Horowitz Figure 1.1.9 values read directly from the ISSCC paper**, for example 8-bit and 16-bit operations and 8 KB/32 KB/1 MB SRAM reads: illegible in the fetched copies. Only the 32-bit reproduction in Han et al. is verified.
- **H100 dense (non-sparse) Tensor TFLOPS:** not shown on the fetched NVIDIA page.
