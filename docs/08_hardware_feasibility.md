# 08 · Hardware feasibility assessment: is a custom chip warranted?

**Verdict: not warranted on current evidence.** No Phase 1 result identifies a limitation that software, existing accelerators, or existing cooling hardware could not address. The charter (§5) requires that evidence before Phase 5 chip work starts. Below is the reasoning, followed by the gates that would change the verdict.

## What the evidence says, by limitation type (charter §5 list)

| Limitation source | Phase 1 / literature evidence | Addressable without new silicon? |
|---|---|---|
| **Computation** | The largest simulated lever is clock control (14–35% facility energy per successful task, E001). It is available on current GPUs through clock locking and power capping, with measured energy savings in the literature (L03, L04, L09, L10). | Yes: software on existing parts |
| **Memory access / data movement** | Circuit-level data shows a DRAM access costs ~170× a 32-bit float multiply at 45 nm (L15, reproducing L14). Decode is memory-bound (L09). UEIC does not model operation-level energy, so it cannot yet say how much of a real workload's energy is data movement. | Partly: quantisation, batching and attention kernels cut traffic (L18–L20). The remainder is the strongest candidate for a hardware argument, but is **unquantified** here |
| **Communication** | Not modelled (single node). | Unknown |
| **Power delivery** | Conversion efficiency swept 0.88–0.97 in E002 changed results modestly; no binding power-delivery constraint was modelled. | Not assessed |
| **Thermal resistance** | The conduction stack (die + TIM + lid, `r_cond`, class F) is the largest resistance in the default model. Raising it to its high bound caused hardware throttling under independent control (E002). Better packaging and TIMs exist commercially; measured cold plates are already ~8–10 mK/W (reference_values.md). | Yes: packaging/TIM and cold-plate choices, not a new compute architecture |
| **Cooling overhead** | Warm-water free cooling removed nearly all chiller energy in mild and cool ambient (E001). Chiller-free 40–60 °C operation is deployed practice (L30, L31). | Yes: existing plant hardware |
| **Control overhead** | Joint controller decision: ~1 ms of CPU per minute of operation (measured on the simulation host). | Negligible |
| **Software inefficiency** | The gap between fixed and optimised policies is large, and it is closed by software. | Yes |

## Gates for reopening the question (all required)

1. **Measured bottleneck.** Phase 4 measurements on real hardware show that, after software optimisation (clock control, batching, quantisation, efficient attention), a specific term dominates energy per successful task, most plausibly memory traffic in decode. "Dominates" means more than 40% of task energy, with a confidence interval, at the stated measurement boundary.
2. **Not fixable with existing parts.** No commercially available accelerator, memory configuration (e.g. larger on-chip SRAM or higher-bandwidth memory), or packaging option removes that term within cost and schedule constraints.
3. **Credible headroom.** A block-level model shows the proposed architecture would cut the dominant term by enough that facility energy per successful task falls more than 2× relative to the best software-optimised existing part, after accounting for conversion overheads (e.g. optical–electrical for photonics, ADC/DAC for analog in-memory) and precision limits.
4. **Workload stability.** The target workload family (e.g. memory-bound LLM decode) stays stable over the 3–5 year design and deployment window.

## If the gates open: candidate architectures to compare (charter Phase 2)

| | Candidate | Targets | Main risks (from the literature) |
|---|---|---|---|
| A | Digital accelerator with a large on-chip SRAM/near-memory tier for KV-cache and weights | Data-movement energy in decode | Area cost of SRAM; capacity limits; competes with fast-moving commercial parts |
| B | Heterogeneous: general control plus separate prefill (compute-dense) and decode (bandwidth-dense) engines | Phase mismatch (L10, L11) | Scheduling complexity; utilisation |
| C | Analog in-memory or photonic matrix engine | Arithmetic and data-movement energy | Precision and device non-idealities (L37); conversion overheads; demonstrated systems are small and efficiency claims partly projected (L35, class E) |

## What can be done with open-source tools (see `eda_tools_status.md`)

* **Feasible here or on a laptop:** RTL simulation and linting with Verilator 5.05x; synthesis and cell or area estimates with Yosys (`pip install yowasp-yosys` runs on Windows).
* **Feasible in Docker/WSL:** place-and-route, timing and power estimates with OpenROAD flow scripts on SKY130, GF180 or Nangate45. ASAP7 results are predictive only (class E). Open-PDK area, timing and power figures do not represent a 4–5 nm commercial process.
* **Requires commercial tools, foundry access or partners:** advanced-node PDKs (NDA), signoff DRC/LVS at advanced nodes, HBM and advanced-packaging integration, fabrication, and silicon test.

## Recommendation

Do not start chip work. Run Phase 4: measure clock–throughput–power curves and the leakage–temperature slope on a real GPU, and add an operation-level energy model (FLOPs and bytes moved per phase) so the data-movement share can be estimated. Then revisit gate 1.
