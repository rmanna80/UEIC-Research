# 15 · System identification, identifiability and experiment design (Stage 2)

**Status:**
* Implemented and tested: `ueic/models/`, `tests/test_stage2_sysid.py`.
* Applied to the RTX 5070 warm-ups, which gives one measured result (below).
* E016 (adaptive identification under simulated cold-plate drift) is pre-registered and run in simulation; results are in `RESULTS.md`.
* M003 (wide-window leakage) still needs the user's GPU.

## 1. What can be identified from what we measure

| Parameter | Signal needed | Status |
|---|---|---|
| Clock sensitivity β | Throughput at several locked clocks | Identified (M001) |
| Leakage slope dP/dT | Power vs temperature at a fixed clock and load | Measured over 4 K windows (M001/M002); M003 widens it |
| Leakage coefficient κ (curvature) | Power over a *wide* temperature window | **Not identifiable** from the warm-ups (Fisher information, below). Still marginal with M003's planned 50–70 °C window |
| Fast thermal response (die/heatsink) | A power step with high-rate temperature samples | Measured magnitude; time constant below the sensor's update interval |
| Cold-plate resistance R (simulated plant) | Mean junction rise over supply vs mean chip heat | Tracked online by RLS (E016) |
| Coolant loop mass, ramp, delay | Supply temperature after setpoint steps | Not measurable without a liquid loop (Stage 9) |

## 2. Methods (`system_identification.py`, `parameter_estimator.py`)

### First-order thermal ARX

A lumped node C dT/dt = P − (T − T_in)/R, sampled every h with P held constant, is exactly:

T[k+1] = a T[k] + b P[k] + d, with a = e^(−h/RC), b = R(1 − a), d = T_in(1 − a).

* **Fit:** ordinary least squares.
* **Derived quantities:** R = b/(1 − a), τ = −h/ln a, T_in = d/(1 − a). Their standard errors come from the delta method.
* **Warnings:**
  * constant power, where R and T_in are confounded;
  * whole-degree quantisation;
  * a record shorter than 3τ;
  * Durbin–Watson outside [1.5, 2.5], which means autocorrelated residuals and optimistic standard errors.
* The estimator front end adds a Fisher-information identifiability report.

### Step-response fit

T(t) = T0 + A(1 − e^(−t/τ)) + B t over the first seconds after a power step:
* A/ΔP is the fast thermal resistance;
* the B·t term absorbs the start of the slow rise.

### Recursive least squares with forgetting

K = P x/(λ + xᵀPx), θ ← θ + K(y − xᵀθ), P ← (P − K xᵀP)/λ.

* The effective memory is about 1/(1 − λ) samples.
* The covariance does not collapse, so the estimate can follow drift.
* The residual variance is tracked to give standard errors.
* An extended or unscented Kalman filter was considered and **not** built. With one temperature per chip, measured heat and one resistance to track, the problem is linear in the unknown, and RLS is sufficient and easier to audit.

### Excess-resistance estimator (simulator)

y = mean(T_j) − T_sup − R_model(f)·x, with x = q/N, and y = ΔR·x.

* The fit is flow-aware: the model's own R(f) is subtracted.
* While temperatures are still moving the estimate is biased. The bias is small when the chip time constant (~25 s) is short against the 60 s control interval.

### Drift detection (`model_drift.py`)

A Page–Hinkley test on prediction residuals:

U_k = Σ(e_i − ē_i − δ), alarm when U_k − min U > λ.

δ and λ are stated design choices.

## 3. Identifiability (`identifiability.py`)

* The Fisher information is F = JᵀJ/σ², and its inverse is the Cramér–Rao bound.
* Near-null eigen-directions of the scaled F are reported as unidentifiable parameter combinations.
* The verdict is a stated threshold, rel_tol = 0.5, not a theorem.
* It is local, and assumes Gaussian independent noise.

**The warm-up leakage fit.** P(T) = c + L·e^(κ(T−60)) over 48–57 °C has about 10 independent temperature levels:
* NVML reports whole degrees;
* samples at 10 Hz are strongly autocorrelated.

With that, κ's relative CRLB error is far above 1. The stored fit's own standard error (0.036 for κ = 0.0015) says the same thing. A 45–80 °C window would cut it more than fivefold (tested).

## 4. Choosing the next measurement (`active_experiment_design.py`)

The planner ranks safe candidate designs by expected information about the parameters of interest, using D-optimality on that subset of the Fisher information, per minute of operator time. Unsafe candidates are excluded, not penalised. It only recommends; nothing touches hardware.

For the leakage question (σ = 0.8 W, the M001 residual; κ = 0.02/K and 20% leakage at mid-window are E009's matched values; temperature levels assumed):

| Design | κ relative error (CRLB) | Safe (≤ 83 °C) |
|---|---|---|
| M001-like warm-up, 48–57 °C | 6.0 | yes |
| M003 plan, 5 fan speeds, ~50–70 °C | 1.27 | yes |
| M003 plan, repeated 3×, ~50–70 °C | 0.73 | yes |
| Narrow high window, 60–66 °C | 14 | yes |
| Fan to 20%, ~50–85 °C | (excluded) | no |

* M003 as planned will measure the leakage **slope** well, which is what the simulator's conclusions depend on (E009, E012).
* It will **not** identify κ on its own. Repeating the sweep helps. A safe window wider than ~20 K is the only way to pin down κ.

This was computed before M003 runs and is recorded so that its result is not over-read.

## 5. Measured result: fast thermal step of the RTX 5070

Source: `experiments/analyze_thermal_step.py` → `data/calibration/M001_M002_thermal_step.json`. Evidence class B on that card only; it would be class E if transferred.

| Warm-up | Power step | Fast rise A | R_fast = A/ΔP | Fitted τ | Sensor update interval |
|---|---|---|---|---|---|
| M001 (2002 MHz) | 103 W | 12.6 K | 0.123 K/W | 0.72 s | 1.75 s |
| M002 (2340 MHz) | 139 W | 16.4 K | 0.118 K/W | 0.50 s | 1.00 s |

* The fit uses the first 10–17 s of load, before the fans started.
* The fast rise per watt agrees between the two sessions: 0.118–0.123 K/W.
* The fitted τ is shorter than the interval at which NVML's temperature actually changes, so **τ is not resolved**. The die responds within one or two sensor updates.
* This supports, on real silicon, the premise of Stage 3: clocks act on chip temperature in seconds, while the cooling path acts over minutes. The slow rise after the fast step continued at ~0.24–0.36 K/s at zero fan speed.

## 6. How to run

```bash
python -m pytest tests/test_stage2_sysid.py
python experiments/analyze_thermal_step.py
python -m ueic run experiments/E016_adaptive_identification.json --workers 2
```

## 7. Limits

* All identification here uses lumped models. Uneven fouling, multiple heat paths and sensor dynamics are structural errors that these models cannot represent; E016's drift is uniform by construction.
* The adaptive twin may only become *more* conservative from data (ΔR ≥ 0). An estimate below the configured value is not acted on until validated.
