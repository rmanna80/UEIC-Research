# 05 · Dependencies and risk assessment

## Dependencies

| Dependency | Needed for | Status |
|---|---|---|
| Python ≥ 3.10, NumPy, SciPy, matplotlib, pytest | Phases 0–1 | Available; no GPU or network needed |
| A machine with an NVIDIA GPU + NVML (`nvidia-smi`, `pynvml`) | Phase 4 telemetry | **Not available in this environment**; needs the owner's hardware |
| External power meter (wall plug or PDU) | Phase 4 node-level energy | Not available; GPU-reported power excludes PSU, CPU, fans |
| Instrumented liquid loop (flow meter, inlet/outlet RTDs) | Phase 4 thermal calibration | Not available; without it the cooling model stays unvalidated |
| Verilator, Yosys, OpenROAD (or YoWASP builds) | Phase 5 RTL | Not installed; installable when Phase 5 is justified (see `eda_tools_status.md`) |
| Node.js + Three.js (or React stack) | Phase 2 3-D models | Node available; not used yet |
| Real model-quality evaluations (benchmark datasets, verifiers) | Replacing the placeholder routing quality model | Not started |

## Risks

| Risk | Likelihood | Impact | Mitigation in place / planned |
|---|---|---|---|
| **Conclusions driven by invented parameters.** Most hardware/plant values are class E/F. | High | High | Every value is in the registry with a range; E002 sweeps them all; results are labelled conditional; Phase 4 targets the most sensitive ones. |
| **Model too optimistic for the joint controller** (perfect twin, instant setpoints, no loop thermal mass) | High | Medium–High | E005 tests twin mismatch; loop dynamics are the first model upgrade; never report joint savings without E005 context. |
| **Leakage model wrong in form, not just value** (exponential in T, linear in V) | Medium | High (it is the main joint-vs-independent coupling) | Kept as class E; Phase 4 measures power vs temperature at fixed clock on real hardware. |
| **Quality model is a placeholder** (Bernoulli success) | Certain | High for RQ4 | Routing results are reported only as break-even conditions and work-vs-energy gaps, not as quality claims. |
| **Overclaiming from small differences** | Medium | High | Pre-registered threshold, paired CIs, verdict labels, failures and null results reported. |
| **Rebound effects** (cheaper inference → more inference) | Plausible | High for societal claims | Out of scope; stated explicitly; no carbon or total-demand claims made. |
| **Physical-control safety** if controllers ever touch hardware | Low now | Severe | No actuation code exists. Future: read-only first, shadow mode, independent hardware interlocks, explicit authorisation. |
| **Data corruption / silent edits** | Low | High | Triggers, hash chain, `verify` command, corrections table. |
| **Scope explosion** (charter spans 14 disciplines) | High | Medium | Phase gates in `07_phase_plan.md`; each phase must produce validated evidence before the next starts. |
| **Custom-chip work started without justification** | Medium | High cost | `08_hardware_feasibility.md` sets explicit evidence gates. |
