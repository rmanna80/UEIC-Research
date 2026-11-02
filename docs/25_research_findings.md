# 25 · Research findings (next generation)

**Status:** E015 and E016 are complete and summarised below. E018–E022 and E024 are running in simulation; their sections are filled in only after each experiment finishes and its pre-registered analysis has been run. E017, E023 and M003 are pending hardware. Every finding here is **simulated** unless it says otherwise. Hypotheses were committed before each experiment's first run and have not been changed; "not supported" verdicts are reported as such.

Per-experiment detail, with every number, is in `PHASE_REPORT.md` and `RESULTS.md`; limits are in `27_limitations_and_open_questions.md`.

## 1. Completed

### E015 · Multi-step MPC vs the measured-state rule (1,320 runs)

* **Supported:** H1 (the MPC and robust MPC stayed at or below 80 °C in all 24 conditions, under every forecast tested), H5 (anticipation does not add capacity under overload), H6 (robustness costs +0.7% energy).
* **Not supported:**
  * H2: late tasks fell by 33%, short of the pre-registered "at least 1 fewer" (a low-power test);
  * H3: the MPC saved energy even on an instant plant, so part of its advantage is not anticipation;
  * H4: a burst-blind forecast caused 12× the late tasks of persistence.
* **Reading:** in this simulator, a predictive controller behind an independent safety filter was the only arm that was safe everywhere. It was also cheaper than the safe measured-state rule where loop inertia or fouling mattered. Forecasts that hide demand are the main risk.

### E016 · Adaptive identification under cold-plate drift (160 runs)

* **Supported:** H1 (no harm without drift), H2 (drift makes a fixed model unsafe), H6 (no energy penalty).
* **Not supported:**
  * H3: adaptation removed 77% and 33% of the over-temperature time in the two worst conditions, short of the 80% criterion;
  * H4 and H5: only partly true;
  * H7: drift detection was late or missing after an abrupt step.
* **Reading:** online resistance estimation handles gradual fouling. It does not handle an abrupt fault at high ambient. That motivates E019's residual-based supervisor.

## 2. Running (simulation)

| ID | Question | Section filled after |
|---|---|---|
| E021 | Heat-reuse economics with an approach-dependent dry cooler | its 480 runs finish |
| E019 | Fault-aware vs nominal supervision under 13 faults | its 260 runs finish |
| E022 | Demand-response cap: capping, deferral, cold storage | its 50 runs finish |
| E018 | Thermal-credit placement vs four baselines | its 150 runs finish |
| E020 | Joint vs independent control, 1–16 nodes | its 120 runs finish |
| E024 | Integrated 2⁴ ablation | its 80 runs finish |

## 3. Pending hardware

* **E017**: real LLM energy per correct, on-time answer (Ollama + GSM8K on the user's GPU).
* **E023**: equivalent kernels (ATLAS/KernelSmith sources pending access).
* **M003**: leakage at fixed fan speeds on the RTX 5070.

None of these has synthetic data standing in for it.
