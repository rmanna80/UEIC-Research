# 11 · What in UEIC might be new: a targeted prior-art check (2026-10-27)

**Scope.** These are targeted searches, run while E011–E014 were designed and analysed. They covered:
* recent data-centre MPC with liquid cooling;
* LLM-serving schedulers that use coolant thermal mass;
* joint DVFS-and-cooling control;
* warm-water facility analyses;
* GPU leakage–temperature measurements;
* patents on workload-informed proactive cooling.

Sources read are L44–L50 in `literature_matrix.csv`, each with how it was verified. This is not a systematic review, so not finding something here is **not** evidence that it is new. Simulation results stay simulation results.

An independent audit recomputed every E011, E011B and E012 hypothesis from the raw store. It flagged several overstatements in the first draft of this file and of `PHASE_REPORT.md`, and those are corrected here. The most important: E012's warm-water hypotheses could not have passed in UEIC's plant model.

**Bottom line.** Nothing here is a discovery. The most useful outputs are:
1. a measured leakage slope for a current GPU (a data point);
2. a simulated failure mode of steady-state joint DVFS/cooling optimisers on slow liquid loops, and a safe but myopic rule that removes it;
3. a quantified, model-dependent estimate of the chip-side cost of warm-water heat reuse.

## Candidate 1 · A measured leakage–temperature slope for a current GPU

**What UEIC has.** These are measurements on an RTX 5070 at a locked clock and constant compute load (class B on that card):
* **M001 warm-up (2.0 GHz):** board power rose 0.135% per K at constant fan speed.
* **M002 (2.33 GHz):** the rise was ≤ 0.124%/K.

Each window is about 4 K, at 1 °C sensor resolution. Voltage-regulator losses are not separated, so these are upper bounds on leakage sensitivity.

**Prior work found.**
* **L28 (Price et al., Kepler K20, water-cooled).** Reports efficiency falling from 13.5 to 12.4 GFLOPS/W between 30 and 90 °C at a fixed clock. That is an *average* power rise of about 0.15%/K over 60 K, computed here from the two reported figures and assuming constant throughput. The paper fits a non-linear law.
* **L29 (Latif et al. 2025, H100 liquid vs air).** Reports lower power with liquid cooling but does not isolate a temperature coefficient.
* **L26 (Breen et al.).** Gives leakage shares of chip power, not slopes.

**Assessment.** The two GPU generations agree only to order of magnitude. L28 gives a 60 K average and UEIC a local 4 K slope, so this is not a like-for-like comparison. Both sit well below UEIC's registry value of 0.35–0.37%/K, which explains why E009 found leakage-aware coordination worth under 0.6%. This is a **data point, not a discovery**. It becomes a usable one with a wider window (M003, `09` §8; tooling ready) and a second card.

## Candidate 2 · Joint DVFS and cooling control on a slow liquid loop

**What UEIC has (class C, simulation).**
* **E010:** steady-state joint control overheated under a ramp-limited coolant plant. It commanded chiller-cooled water and chose clocks for water that took minutes to arrive.
* **E011:** `joint_lag` checks safety at the supply the chips will actually see. It removed all overheating: 0 chip-seconds above 80 °C, against 17,218 for steady-state joint control summed over 18 slow-loop conditions.
* **E011B:** that safety does not come from its different overload fallback.
* **E013:** a fixed margin on the thermal target did not fix the steady-state controller, even at 9 K: 7,232 chip-seconds above 80 °C.
* **Second audit.** On slow loops joint_lag never changed its supply setpoint and never ran the chiller (420 of 420 runs). It stayed at the free-cooling temperature and handled heat with flow and clocks. Its check never credits cooling that has not arrived, so the slow actuator only ever adds cost.
* **E014's robustness test therefore had no power.** With a wrong loop model, or with no loop model (`joint_meas`), the outcome was identical *because the setpoint never moved*.
* **The audit's exploratory runs differ.** At heavier load and in constructed states (not pre-registered), the two policies diverge and wrong models do change joint_lag's behaviour.

**Prior work found.**
* **Abera & Chen (L49, 2026; workshop version NeurIPS 2025).** The closest on control structure. It co-optimises tensor parallelism, per-job DVFS and cooling for LLM serving. A 60 s cooling MPC acts on supply-air temperature and airflow over state-space rack thermal dynamics, with a temperature constraint. It is air-cooled. The text read mentions no actuator ramp limits, but its MPC section was truncated, so that is unconfirmed.
* **HeatCache (L44, 2026).** The closest liquid-cooled work. It treats a chassis-level loop's thermal mass as a heat budget, with a one-step RC admission check and DVFS plus micro-batching, on four water-cooled RTX 4090s. It excludes facility direct-to-chip/CDU loops. Like UEIC's joint_lag in practice, it manages heat through compute rather than by moving the coolant.
* **EPFL chip-scale MPC (L50; authors and year not verified; abstract only).** Sets DVFS and microchannel coolant flow together, minimising chip-plus-cooling energy under a temperature limit.
* **EPFL two-layer MPC (L45, 2026).** Dispatches a data centre with hybrid cold-plate and air cooling and heat recovery, but states that coolant transients are outside its MPC.
* **IBM patent US 8,909,383 (L47, 2014).** The claim summary read describes forecasting chip power from upcoming workload, compute-side measures (activating spare cores) and informing cooling ahead of the temperature change. DVFS coordination and loop dynamics do not appear in that summary.
* **Lazic et al. (L23, 2018).** MPC on a real cooling plant, with server power as an exogenous disturbance.

**Assessment.** Joint DVFS-and-cooling optimisation is established: at chip scale (L50, if its metadata checks out) and for air-cooled LLM serving with thermal dynamics (L49). What UEIC's slow-loop work actually showed, in simulation, is narrower:
1. A steady-state optimiser that counts on chiller cooling it has commanded but not yet received overheats chips under a ramp-limited plant. A margin on the target does not fix this.
2. The rule "judge safety at the warmer of measured supply and setpoint" removes the overheating. In the tested conditions it did so by never using the slow actuator, at a cost in capacity in the most severe case.

Using the measured state in a safety constraint is ordinary control practice. So this is a **corrected design with a clear simulated failure mode behind it, not a novel controller**. The interesting open question is a controller that credits cooling *when it will arrive*, a multi-step MPC with the loop model and this rule as a constraint, tested where the setpoint must move. Its value in practice would depend on whether deployed setpoint optimisers judge safety at the commanded setpoint, which this review did not establish. Untested: loop-model structure error and any real loop.

## Candidate 3 · The overload fallback

When demand exceeded planned capacity, UEIC's steady-state joint and independent controllers ran every clock at maximum, including the clock for memory-bound work. In the simulator that clock has no effect on throughput (beta_memory = 0, transferred from M001's streaming kernel; a bound for LLM decode, not a measurement of it). A throughput-first, power-second fallback saved 4.5–4.7% in all 27 E011B conditions. **This is not new.** Phase-aware DVFS for memory-bound decode (L09–L11) rests on the same fact. In UEIC it is a correction to its own controllers. Earlier joint-vs-independent comparisons remain like-for-like, since both used the same fallback. Absolute clock-control savings in earlier experiments were probably understated where overload occurred; they were not re-run.

## Candidate 4 · Warm water on real-silicon parameters

The facility-side case for warm water is established practice: Aquasar (L30), SuperMUC (L31). A Schneider analysis reported via trade press (L48, class D; underlying report not read) puts water-use cuts at 66–82% and PUE gain under 1% for 45 °C vs 32 °C supply. L48 reports no chip-side cost.

**E012 asked whether RTX 5070-derived parameters make warm water the energy optimum. The answer is no, but the model guaranteed that answer.** UEIC's dry cooler draws fan power in proportion to the heat it rejects, whatever the approach temperature, and reaches any supply down to ambient + 5 K. Above that limit warmer water has no facility-side benefit, so any positive leakage slope puts the optimum at the coldest free-cooled supply. That is a design error in E012's first two hypotheses, found by the audit.

A rough estimate (class F, computed here, not simulated) assumes fan power ∝ (5 K / approach)³ at design duty, with fans at ~2% of facility energy. It puts the energy-optimal approach at about 8 K with RTX 5070-derived leakage vs about 6 K with placeholders: about 2 K warmer supply, not the 15–20 K heat reuse needs. That suggests the conclusion would survive a better fan model, but it is untested. An approach-dependent dry-cooler model is now the top plant-model item.

**What E012 does quantify.** Holding supply at 40 °C costs 2.7–4.5% energy per successful task with RTX 5070-derived parameters, against 7.7–12.9% with placeholders. That is about 0.16–0.18% per kelvin above the free-cooling supply, ~91% of it IT energy, so a PUE-style ratio did not move (1.089). That PUE hides IT-side changes is a known criticism. The one-third ratio follows directly from the leakage parameters (27.4 vs 90 W), so it restates the measured slope in energy terms. It rests on one card's 4 K window, transferred to a simulated 600 W-class accelerator (class E).

## Status of each candidate

| Candidate | Evidence | Novelty | What would strengthen it |
|---|---|---|---|
| Leakage slope of a current GPU | B on one card, 4 K window | data point | M003 (20 K window), a second card |
| Slow-loop safety rule for joint control | C (simulation); E010–E014; in tested conditions it never moved the coolant | low (feedback on a measured state); value depends on deployed practice | a pre-registered test where the setpoint must move; a multi-step MPC that credits arriving cooling; loop-structure error; a real loop |
| Overload fallback | C, resting on a streaming-kernel bound | not new (L09–L11) | measured decode clock sensitivity |
| Chip-side cost of warm-water heat reuse | C/E, set by the leakage slope | low; quantification only | M003; approach-dependent dry-cooler model; a heat-value model |
