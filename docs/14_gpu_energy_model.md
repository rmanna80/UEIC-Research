# 14 · GPU power and performance model

**Status:**
* The power model is the registry's, unchanged since Phase 4: `ueic/physics/__init__.py` and `ueic/physics/gpu.py`.
* Its clock-sensitivity and voltage-floor shape are calibrated on one RTX 5070 (M001; evidence class B on that card).
* The leakage slope is measured only over a 4 K window (M001/M002). The wide-window measurement (M003) is pending on the user's GPU.
* No full power *surface* over clock × temperature × workload has been fitted. That needs M003 and the E017 sessions.

## 1. Problem

A controller that trades clock speed against cooling needs two predictions:
* how much power a GPU draws at a given clock, temperature and workload;
* how fast the work goes.

If either is wrong, "energy-optimal" decisions are wrong. The project's early results showed the registry's straight-line voltage form predicted the wrong *shape* of energy vs clock (Phase 4, docs/10).

## 2. Model

For one accelerator at clock ratio s = f/f_max, junction temperature T and activity a:

| Term | Equation | Meaning |
|---|---|---|
| Voltage ratio | v(s) = v_min + (1 − v_min)·max(0, (s − k)/(1 − k)) with knee k (`vf_knee` > 0); the legacy linear form when k = 0 | Supply voltage relative to its maximum. A floor up to the knee, then linear (measured shape) |
| Dynamic power | P_dyn = p_dyn_max · a · s · v(s)² | CMOS switching ∝ C V² f |
| Other static | p_static_other | Memory, I/O, fans on the board, assumed constant |
| Leakage | P_leak = p_leak_ref · v · e^(κ (T − T_ref)) | Subthreshold leakage grows roughly exponentially with temperature |
| Total | P = P_dyn + p_static_other + P_leak | `chip_power(s, T, a, cfg)` |
| Throughput | r ∝ s^β (β_compute, β_memory) | Work rate vs clock. Memory-bound work barely speeds up with core clock (β ≈ 0) |
| Energy per unit of work | e(s, T) = P(s, T)/s^β | `gpu.energy_per_work`. Its minimum over s is `gpu.most_efficient_clock` |

**Why a minimum exists:**
* At a high clock, P_dyn grows like s·v² while throughput grows like s^β, so e rises.
* At a low clock, the static and leakage power are paid for longer per unit of work, so e rises again.

The voltage floor (v cannot fall below v_min) makes deep clock cuts save less than the linear form predicts. That was the measured behaviour (M001: the compute kernel's energy minimum is at 1657 MHz, 32% below the top clock).

## 3. What is measured, and on what

| Parameter | Value | Source | Class |
|---|---|---|---|
| β_compute | 0.983 ± 0.009 | M001, five locked clocks, FP16 GEMM | B (RTX 5070) |
| β_memory | measured −0.056 ± 0.079, used as 0 | M001, memory kernel | B |
| v_min, knee | 0.78, 0.805 | M001 power-vs-clock fit (voltage-floor form) | B |
| Leakage slope dP/dT | ≈ 0.12–0.14% of board power per K | M001/M002, 4 K windows | B (narrow window) |
| κ (curvature) | not identified | Fisher information (docs/15) | – |
| Fast thermal resistance | 0.118–0.123 K/W | M001/M002 power steps (docs/15) | B |

When transferred to the simulated accelerator, everything becomes class E (an extrapolation to a different device). Registry defaults without a measurement remain class F/G.

## 4. Files and data flow

* `physics/__init__.py`: `voltage_ratio`, `leakage_power`, `chip_power`, `idle_power`, thermal functions.
* `physics/gpu.py`: `energy_per_work`, `most_efficient_clock` (views on the same functions).
* `calibrate.py`: sessions, guards and fits (β, power-vs-clock, leakage).
* `models/parameter_registry.py`: uncertainty and validity domains, with an `ExtrapolationWarning` outside the measured clock range.
* `scheduling/phase_scheduler.py`: per-phase clocks (compute-bound prefill vs memory-bound decode) from `energy_per_work` under a throughput floor.
* `scheduling/model_router.py`: rescales measured request energy by the model's leakage ratio at the current temperature (a labelled prediction).

## 5. How to run and test

```bash
python -m pytest tests/test_physics.py tests/test_calibration.py tests/test_stage1_physics.py
python -c "from ueic.params import make_config; from ueic.physics.gpu import most_efficient_clock; \
cfg = make_config({'beta_compute': 0.983, 'vf_knee': 0.805, 'v_min_ratio': 0.78}); print(most_efficient_clock(60.0, 0, cfg))"
python -m ueic calib plan-leak --clock 2347 --fans 100,80,60,45,30   # M003 procedure (you run it)
```

## 6. Assumptions and failure modes

* One activity level per workload class. Real kernels vary within a run (E017 measures real serving).
* Leakage is exponential in T with one κ. Over the 4 K measured window, any smooth form fits. Outside it, the model is extrapolating (M003 widens the window).
* Board power (NVML) is not chip power: it includes memory and VRM losses. Comparisons are within that boundary.
* The throughput law s^β holds for the measured kernels. LLM decode at small batch is memory-bound (β ≈ 0), and large-batch prefill compute-bound. The phase scheduler assumes these two extremes until E017 measures them on a serving engine.

## 7. Interpreting results

* A predicted energy-optimal clock is a property of this model with these parameters.
* On the measured card it agrees with measurement in where the minimum is, to within a few percent of top-clock power.
* On any other accelerator it is a hypothesis to measure.
