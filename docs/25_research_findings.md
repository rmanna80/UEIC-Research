# 25 · Research findings (next generation)

**Status:** E015, E016, E018–E022 are complete and summarised below. E024 is running in simulation; its section is filled in only after it finishes and its pre-registered analysis has been run. E017, E023 and M003 are pending hardware. Every finding here is **simulated** unless it says otherwise. Hypotheses were committed before each experiment's first run and have not been changed; "not supported" verdicts are reported as such.

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

### E021 · Heat reuse with an approach-dependent dry cooler (480 runs)

* **Supported:**
  * H2 (no-floor supply stays below 35 °C at 8 and 20 °C);
  * H5 (supply orders by fan cost);
  * H6 (in the RTX 5070-derived world, a 44 °C floor costs 0.037–0.055 kWh_el per kWh_th of reusable heat);
  * H7 (about 4× less than a heat pump would need).
* **Not supported:**
  * H1: the better dry-cooler model moved the optimum 0.8–1.9 K *colder*, not warmer;
  * H3 and H4: no larger shift in the RTX world, and no cheaper floor with the NTU plant.
* **Reading:**
  * The legacy plant's optimum was its fixed 5 K approach.
  * A dry cooler that can reach a 3–4 K approach cheaply lets the optimiser cool the chips further.
  * The chiller never ran, so the cost of warm water is chip leakage, and warm water is justified only by the value of the heat.
  * In the RTX-derived world it pays if heat is worth more than ~2–6% of the electricity price per kWh. In the registry world the threshold is ~5–15%.
  * This scales with the leakage slope (M003 pending).

### E019 · Fault-aware supervision under 13 faults (260 runs)

* **Supported:**
  * H1: no false alarm and no cost without a fault;
  * H2: 85% of window faults detected within 180 s;
  * H3: never worse than the nominal stack;
  * H4: stuck clock −85% and −89% time above target;
  * H5: 94% back to NORMAL within 300 s of the window ending.
* **Not supported:** H6. Degradation was detected in 70% of runs: fouling and a wrong model every time, a pump degraded from t = 0 once in 10.
* **Reading:**
  * Residual and actuation checks catch faults that the twin in E016 missed, and the SAFE fallback never made temperatures worse.
  * It costs up to 22% energy per success while a fault lasts.
  * Faults present from the start are learned as normal. Catching them needs a reference not learned from the running plant.

### E022 · Demand-response cap (50 runs)

* **Supported:**
  * H1: the cap was held to within watts;
  * H2: deferral kept, and raised, the on-time fraction;
  * H5: the cap binds when not enforced.
* **Not supported:**
  * H3: storage added +0.7% event work at 30 °C (CI includes 0);
  * H4: storage used less energy *and* cost less on the seed means. In 3 of 5 seeds it used more energy, as expected; in the other two it avoided a backlog that plain capping created.
* **Reading:**
  * Deferral beat plain capping on energy, cost and on-time fraction.
  * The storage test was underpowered: a small charge (1.9 kWh_th) against a small chiller share.
  * "Energy is not cost" remains untested.

### E018 · Thermal-credit placement (150 runs)

* **Supported:**
  * H2: 3–6× less time above target than temperature-aware placement;
  * H4: no difference under uniform cooling;
  * H5: rack-capped bursts.
* **Not supported:**
  * H1: lower energy per on-time job than all baselines held only with heterogeneous nodes (C5);
  * H3: on-time fraction fell 4–16 points below the best baseline under tight thermal stress.
* **Reading:**
  * The placement rule alone did nothing (ablation). The benefit comes from reduced start clocks and holds.
  * That gave the lowest grid energy and far less throttling, at the price of deadlines.
  * Parameters were hand-set.

### E020 · Joint vs independent facility control, 1–16 nodes (120 runs)

* **Not supported:** H1–H4.
  * Joint control won at 1 node (−7% and −16% energy per on-time job).
  * It lost at 4 and 16 nodes (+8% to +22%, wide CIs), because thermal-credit holds cost on-time jobs and heat-proportional valves added pump work.
* **Descriptive:**
  * The warm-supply component alone saved 3.9–4.9% at 30 °C and cost 0.5–3.3% at 20 °C, in line with E021.
  * The 16-node cells were congested by the illustrative rack-uplink model. An exploratory re-run without the limit raised on-time from 0.49 to 1.00.
* **Reading:** joint cooling control at scale has to be tested with network-aware placement or an uncongested topology. That is a new experiment.

## 2. Running (simulation)

| ID | Question | Section filled after |
|---|---|---|
| E024 | Integrated 2⁴ ablation | its 80 runs finish |

## 3. Pending hardware

* **E017**: real LLM energy per correct, on-time answer (Ollama + GSM8K on the user's GPU).
* **E023**: equivalent kernels (ATLAS/KernelSmith sources pending access).
* **M003**: leakage at fixed fan speeds on the RTX 5070.

None of these has synthetic data standing in for it.
