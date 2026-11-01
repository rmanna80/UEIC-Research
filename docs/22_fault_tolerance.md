# 22 · Failure-aware operation: fault injection, detection and recovery (Stage 8)

**Status:**
* Implemented and tested (`ueic/reliability/`, `tests/test_stage8_reliability.py`).
* E019 is pre-registered and run in simulation (§8).
* Faults are injected **in simulation only**.

## 1. Problem

Controllers act on telemetry and assume their commands take effect. Real systems break both assumptions in several ways:
* sensors drop out, drift or freeze;
* commands are lost or ignored;
* controllers crash;
* plates foul and pumps wear.

A controller that is optimal on clean data can be dangerous on bad data. The question is whether an explicit fault-aware layer makes things safer, how quickly it notices, and what its caution costs.

## 2. Architecture

```
plant ─(true state)─► FaultInjector ─(possibly corrupted obs)─► Supervisor ─► controller (joint_meas or mpc)
  ▲                       │                                       │
  └──(applied action)─────┴──(possibly altered action)◄───────────┘
hardware throttle acts on TRUE junction temperature underneath everything
```

* `NominalSupervisor`: catches controller exceptions and holds the last action. Nothing else.
* `FaultAwareSupervisor`: validation → residual and degradation monitoring → mode (NORMAL / DEGRADED / SAFE) → controller or fallback → independent safety filter with a degradation-adjusted plate resistance.

## 3. Detectors (every threshold stated, none tuned on fault data)

| Check | Rule | Catches |
|---|---|---|
| Dropout / range | Non-finite or outside [−5, 125] °C | Lost sensors |
| Rate | \|ΔT\|/Δt > 5 K/s (the lumped chip cannot do that) | Spikes, wrong channel |
| Stuck values | Junction readings bit-identical for 3 intervals while chip heat changed > 2% | Frozen sensors |
| Age | Telemetry time stamp older than 90 s | Communication loss |
| Actuation | Reported applied clock differs from the last command by > 0.05 for 2 intervals | Clock commands not applied |
| Residual CUSUM | r = mean(T_j) − T_sup − R_model q/N. Baseline learned over 20 intervals; σ is the upper 90% χ² bound; k = 0.5, h = 8; two-sided | Readings biased low (S⁻), resistance or reading high (S⁺) |
| Degradation | RLS excess resistance ΔR (Stage 2) > 0.01 K/W for 3 updates | Fouling, low flow, wrong model (not told apart) |
| Exceptions | Any exception from the controller | Crashes, infeasibility |

**CUSUM, from first principles.** For standardised residuals z, the CUSUM statistic S⁺ = max(0, S⁺ + z − k) accumulates evidence that the mean has shifted up by more than k. It resets toward 0 while the mean is in control, and an alarm is raised when it exceeds h. Larger h means fewer false alarms but slower detection.

Measured on i.i.d. Gaussian residuals: 14 of 200 sequences of 180 in-control samples raised a false alarm (7%), and a 6σ low bias was caught within 4 samples (tests). An earlier version that used the sample σ from 10 points raised far more false alarms. It was made conservative before E019 was registered (disclosed).

## 4. Modes and recovery

| Mode | Behaviour |
|---|---|
| NORMAL | The controller acts, and its action passes the safety filter |
| DEGRADED | Junction readings are replaced by T_sup + (R_model + ΔR)·q/N + 3 K (analytical redundancy). The controller is still in charge |
| SAFE | `control.fallback.fallback_action`: maximum flow, minimum supply, the highest-throughput safe clocks |

* A mode is left only after 3 consecutive healthy intervals.
* A detected ΔR raises the safety filter's plate resistance, so the filter becomes more conservative. It never relaxes below the configured model.

## 5. Fault set (`fault_injection.py`)

* **Window faults (2400–4200 s):**
  * sensor dropout (junction and supply);
  * junction bias −10 K;
  * stuck sensors;
  * clock stuck;
  * communication failure (telemetry frozen and commands lost);
  * controller crash;
  * solver infeasibility;
  * supply-sensor bias −8 K.
* **Physical faults (true plant only):** 600 s setpoint delay, a +0.02 K/W fouling step, a degraded pump, and a wrong model (r_cond 0.024 vs 0.04).

## 6. Run and test

```bash
python -m pytest tests/test_stage8_reliability.py
python -m ueic run experiments/E019_fault_robustness.json --workers 2
```

## 7. Assumptions and failure modes

* The CUSUM baseline is learned in the first 20 minutes. A fault present from t = 0 becomes part of the baseline, and only the resistance estimator can see it.
* `joint_meas` does not read junction temperatures, so junction-sensor faults cannot hurt it. That is a property of the controller, not a gap in the test.
* SAFE mode is expensive (maximum flow, coldest supply). Fault-awareness costs energy during faults.
* The power telemetry is assumed healthy. A fault in it would blind the residual and the actuation checks.

## 8. Results (E019)

Filled in after the run; see `PHASE_REPORT.md`.
