# 09 · Phase 4 calibration protocol (real GPU, read-only)

**Purpose.** E002 showed that a handful of assumed parameters decide most of the Phase 1 conclusions: the voltage–frequency curve (`v_min_ratio`), clock sensitivity by workload type (`beta_compute`, `beta_memory`), and the leakage–temperature relation (`kappa_leak`, `p_leak_ref`). This protocol measures them on a real NVIDIA GPU and feeds them back into the simulator, with their provenance recorded.

**Safety.** UEIC only *reads* from the GPU through NVML; a test enforces that its code contains no NVML setter calls. The only hardware change in this protocol is clock locking with `nvidia-smi`. You run those commands yourself, after reviewing them. Do not run the protocol on a laptop on battery, in a closed bag, or with blocked vents. Stop if the GPU reports thermal throttling.

**Boundary.** NVML reports GPU board power only. Results calibrate the *accelerator* model, never facility energy.

## 1. Install (Windows PowerShell)

```powershell
cd UEIC-Research
.\.venv\Scripts\Activate.ps1
pip install -r requirements-hw.txt
# PyTorch with CUDA: pick the command for your CUDA version at https://pytorch.org/get-started/locally/
python -m ueic telemetry devices          # should list your GPU, its max SM clock and power limit
```

## 2. Get the procedure for your GPU

```powershell
nvidia-smi -q -d SUPPORTED_CLOCKS | more  # choose 4-6 SM clocks spread over the supported range
python -m ueic calib plan --clocks 900,1200,1500,1800
```

The printed plan is the whole procedure. It has two parts:

1. **Leakage warm-up** (about 15 min): lock one mid-range clock, let the GPU idle for 5 minutes to cool, then run a steady compute load for 10 minutes. At constant clock and load, the rise in power as the die warms is attributed to leakage. The fit needs at least 8 K of temperature rise.
2. **Clock sweep** (2 minutes per clock): at each locked clock, run a compute-bound kernel (FP16 matrix multiply) and a memory-bound kernel (FP32 vector update), 60 s each.

Clock locking (`-lgc`) needs an Administrator PowerShell, and many laptop GPUs refuse it. If yours does:
* the sweep cannot be done, so `beta_*` and `v_min_ratio` stay unmeasured;
* the warm-up can still run at default clocks, but the fit keeps only samples within ±15 MHz of the median clock. If boost moves the clock too much, it reports "too few samples" instead of a number.

Always finish with `nvidia-smi -rgc` to restore default clocks.

## 3. Fit, record, and use the results

```powershell
python -m ueic calib fit data\calibration\* --out data\calibration\calibration.json
python -m ueic calib ingest data\calibration\calibration.json          # stored as measurement experiment M001
python -m ueic run experiments\E001_policy_benchmark.json --calibration data\calibration\calibration.json
```

* `fit` prints each estimate with its standard error and flags values outside the ranges swept in E002. The fitting code is validated in `tests/test_calibration.py`: it recovers known parameters from synthetic sessions.
* `ingest` writes the estimates into the append-only store as experiment `M001`. Directly measured shape parameters are labelled `physical_measurement`. The leakage power transferred to the simulated accelerator is labelled `engineering_assumption`, because it scales your GPU's leakage *fraction* to a 600 W-class device.
* `run --calibration` creates a new experiment `E001C` whose spec records the calibration file's SHA-256, so every calibrated result traces back to the raw telemetry.

## 4. What the fits can and cannot tell you

| Fit | Model | Main caveat |
|---|---|---|
| `beta_compute`, `beta_memory` | log(throughput) vs log(clock / max clock) | Kernel-specific. Real LLM prefill and decode are not these kernels; L09 reports decode is far less clock-sensitive than this memory kernel may be |
| `v_min_ratio` | P = A + P_d·s·v(s)² with v linear in s | Voltage is not observable through NVML. This fits the registry's functional form, not the true V–f table. Sessions at different temperatures add leakage error |
| `kappa_leak`, leakage fraction | P(T) = c + L·exp(κ(T − 60 °C)) at constant clock and load | Attributes *all* temperature-dependent board power to leakage. Fan and voltage-regulator losses are not separated, so this is an upper bound on leakage sensitivity |

Commit the `data/calibration/` folder with the results: it is the evidence behind any calibrated experiment.
