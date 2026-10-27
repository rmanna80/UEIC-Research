# 11 · What in UEIC might be new: a targeted prior-art check (2026-10-27)

**Scope.** These are targeted searches, run while E011, E011B and E012 were designed. They covered:
* recent data-centre MPC with liquid cooling;
* LLM-serving schedulers that use coolant thermal mass;
* warm-water facility analyses;
* GPU leakage–temperature measurements;
* patents on workload-informed proactive cooling.

Sources read are L44–L48 in `literature_matrix.csv`, each with how it was verified. This is not a systematic review, so not finding something here is **not** evidence that it is new. Every claim below names its evidence class. Simulation results stay simulation results.

## Candidate 1 · A measured leakage–temperature slope for a current GPU

**What UEIC has.** On an RTX 5070 at a locked clock and constant compute load, board power rose 0.135 % per K at constant fan speed (2.0 GHz). At 2.33 GHz the rise was ≤ 0.124 %/K (M002, class B on that card). The window is only 4 K, at 1 °C sensor resolution. The voltage-regulator share is not separated, so the figure is an upper bound on leakage sensitivity.

**Prior work found.**
* **L28 (Price et al., Kepler K20, water-cooled).** Reports efficiency falling from 13.5 to 12.4 GFLOPS/W between 30 and 90 °C at a fixed clock. That is an average power rise of about 0.15 %/K, computed here from the two reported figures and assuming constant throughput; the paper fits a non-linear law.
* **L29 (Latif et al. 2025, H100 liquid vs air).** Reports lower power with liquid cooling but does not isolate a temperature coefficient.
* **L26 (Breen et al.).** Gives leakage shares of chip power, not slopes.

**Assessment.** Two GPU generations twelve years apart, measured independently, give about 0.14 %/K. UEIC's registry assumed 0.35–0.37 %/K, about 2.5 times that. The agreement makes M002 more credible than its 4 K window alone would. It also explains why E009 found leakage-aware coordination worth under 0.6 %. As a contribution this is a **data point, not a discovery**. It becomes a usable one with a wider window (M003, `docs/09` section 8) and a second card.

## Candidate 2 · Joint DVFS and cooling control that plans with the coolant loop's lag

**What UEIC has.** `joint_lag` (E011) tracks the cooling plant's ramp-limited setpoint, predicts the supply temperature the chips will see before the next decision, and keeps clocks and flow safe at that temperature. Clocks are the fast actuator and the coolant setpoint the slow one. This is **class C** (UEIC simulation), with a controller that knows the loop's mass and ramp limit exactly.

**Prior work found.**
* **HeatCache (L44, 2026).** The closest. It treats a chassis-level liquid loop's thermal mass as a heat budget, checks admission with a one-step RC model, and chooses micro-batch size and DVFS level for LLM serving on four water-cooled RTX 4090s. It explicitly excludes facility direct-to-chip/CDU loops. Its controller does not set the coolant, and it optimises GPU energy only.
* **EPFL two-layer MPC (L45, 2026).** Dispatches a liquid-cooled data centre with heat recovery, but states that coolant and thermal transients are outside its MPC.
* **IBM patent US 8,909,383 (L47, 2014).** Forecasts chip power from upcoming workload and informs cooling ahead of the temperature change (feedforward). It claims no DVFS coordination and no loop-dynamics model.
* **Lazic et al. (L23, 2018).** MPC on a real cooling plant, with server power as an exogenous disturbance.

**Assessment.** No source found combines a facility coolant loop with a ramp-limited plant, coolant setpoint and flow as decision variables, DVFS as the fast safety actuator, and an IT-plus-cooling energy objective. That combination **may** be new, but the bar for claiming it is high:
1. A simpler baseline has not been tested: steady-state joint control with a fixed safety margin on the thermal target. If a margin achieves the same safety at similar cost, the loop model adds little.
2. The controller knows the loop exactly. Robustness to a wrong loop mass or ramp is untested.
3. Everything is simulated, with a single well-mixed tank.

E011's safety result (0 chip-seconds above 80 °C against 17,218 for steady-state joint control across the slow-loop conditions) is strong *inside the model*. Its energy result mixed two changes, and E011B separates them (below).

## Candidate 3 · The overload fallback

E011's diagnostic found that, when demand exceeded planned capacity, steady-state joint control ran every clock at maximum, including the clock for memory-bound work. M001 measured that clock as having no effect on throughput. **This is not new.** Phase-aware DVFS for memory-bound LLM decode (L09–L11) rests on the same fact. In UEIC it is a correction to its own controllers. Earlier joint-vs-independent comparisons remain like-for-like, since both used the same fallback. Absolute DVFS savings in earlier experiments are understated wherever overload occurred.

## Candidate 4 · Warm water on real-silicon parameters

The facility-side case for warm water is established practice:
* Aquasar (L30) and SuperMUC (L31);
* Schneider's 2026 analysis (L48): 45 °C supply cuts water use by 66–82 % for under 1 % PUE gain.

L48 does not report the chip-side cost: leakage, throttling, service. E012 estimates that cost with measured-slope leakage. Results below.

## Results that bear on these candidates

*Filled in from E011B and E012 once they finish; see `PHASE_REPORT.md`.*
