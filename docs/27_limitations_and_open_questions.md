# 27 · Limitations and open questions

## 1. Evidence base

* **Almost everything is simulated.** The only physical measurements are NVML board telemetry on one RTX 5070 (M001, M002) and one laptop GPU. No facility, coolant loop, wall power or serving engine has been measured.
* **Parameters:**
  * plant, cold-plate and leakage-curvature parameters are class F/G placeholders;
  * the measured shape parameters (β, voltage floor) are class B on one card and class E when transferred;
  * the leakage slope rests on a 4 K window.
* **Synthetic workloads.** The fluid demand model (single node) and the job generator (facility) are not traces. E017 is designed to replace them for inference.

## 2. Model structure

* **One lumped node per junction.** Real dies have hot spots and several thermal paths. The measured fast response (0.12 K/W in < 2 s) fits the lumped view only roughly.
* **Instant plant in the facility simulator.** Plant lag is studied only on one node (E015). Combining multi-node placement with a lagging shared plant is untested.
* **Plant modules scale linearly.** There is no staging of chillers or dry coolers, and the chiller part-load map is neutral by default.
* **Coolant network:** quadratic branch law; no valve or pump dynamics, check valves or pressure limits.
* **Storage (E022)** is a heat reservoir, not a stratified tank in the loop. `physics/thermal_storage.py` exists but is not wired into the facility simulator. In E022 the store received only 1.9 kWh_th, too little to test its effect (H3, H4).
* **Network model (class G).** Each rack uplink carries 4 cross-node jobs without slowdown. At 16 nodes and load 0.75 this saturated under least-loaded placement and dominated E020's 16-node cells (exploratory diagnostic: on-time 0.49 → 1.00 without the limit). E024 uses the same topology parameters. Facility results at that scale describe congestion as much as cooling.

## 3. Control and scheduling

* The MPC knows the loop model exactly (E015). Model error is studied separately (E014, E016, E019), not jointly with forecasting error.
* Thermal-credit parameters (2 K margin, 600 s horizon cap, clock set, 60 s hold) were set by hand and are untuned. A different setting may change E018's verdicts.
* The fault-aware supervisor's thresholds are stated, not tuned. Its false-alarm rate was measured only on synthetic Gaussian residuals. Faults present from t = 0 are learned as its baseline (E019: a degraded pump was detected in 1 of 10 runs).
* Placement rules (least-loaded, thermal-credit) ignore the network. E020 and E024 show this matters more than cooling at 16 nodes in this model.
* The warmest-safe supply rule uses measured state only. Under a grid cap it warms the supply while clocks are held down, and the chips overshoot when the cap lifts (E024, 83.8 °C). With a lagging plant this would be worse.
* The independent safety filter shares the steady chip model with the optimiser. A shared-model error is caught only by the simulated hardware throttle.

## 4. Statistics

* Most experiments use 5 seeds. Effects of a few percent can be real and still fail an equivalence or threshold test.
* Many hypotheses are tested with no multiplicity correction.
* Energy per on-time job divides by a count that the policy itself changes. When a policy trades deadlines for energy (E018, E020), the metric's confidence intervals become wide, and the verdict mixes the two effects. Grid energy, time above target and on-time fraction are reported alongside it for that reason.
* Seeds vary the workload realisation, not the uncertain physical parameters. Parameter uncertainty is explored by sensitivity variants (E021 fan ratio) and is not propagated through every experiment.

## 5. Open questions (ranked by what would most change conclusions)

1. **What is the real leakage slope over 45–75 °C on the RTX 5070** (M003)? Every warm-water and joint-control energy result scales with it.
2. **How do real serving engines spend energy per correct answer** across model size, clock and concurrency (E017)? Is the J/token ranking misleading in practice?
3. **Do the predictive controller and safety filter keep their margins on a physical loop with real lag and sensor noise?** This needs the thermal test vehicle (docs/23).
4. **Where does the MPC's energy advantage on an instant plant come from** (E015 H3)? The decision rule (backlog price, per-step clocks) needs an ablation.
5. **When does thermal-aware placement stop mattering** in shared-cooling facilities? E018 and E020 answer this only in simulation. E018 shows the gain comes from clock reduction and holds, not placement. E020 shows that at scale, network congestion dominates in this model. A network-aware placement rule is the next test.
6. **How should forecasters be judged?** E015 showed a burst-blind forecast was worse than none. Is there a forecast-quality test that predicts controller harm?
7. **Are abrupt cold-plate faults detectable fast enough to matter at high ambient** (E016 H3/H7)? E019 answered part of this in simulation: a fouling step was detected 420–660 s after onset, and the fault-aware stack cut time above target by about 80%. A fault present from the start remains undetected (H6).
8. **Does storage separate energy from cost** when it is sized to the chiller duty during an event (E022 H4 untested in effect)?

## 6. Things the platform deliberately does not do

* It does not change GPU clocks, power limits or fans. It does not command real pumps or chillers. It does not purchase equipment.
* It does not report facility energy from GPU sensors. Facility numbers are estimates or simulations, and are labelled as such.
* It does not treat a lower bill or a lower PUE-like ratio as lower energy.
