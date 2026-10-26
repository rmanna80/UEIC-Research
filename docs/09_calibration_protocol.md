# 09 · Phase 4 calibration protocol (real GPU, read-only)

**Purpose.** E002 showed that a handful of assumed parameters decide most of the Phase 1 conclusions: the voltage–frequency curve (`v_min_ratio`), clock sensitivity by workload type (`beta_compute`, `beta_memory`), and the leakage–temperature relation (`kappa_leak`, `p_leak_ref`). This protocol measures them on a real NVIDIA GPU and feeds them back into the simulator, with their provenance recorded.

**Safety.** UEIC only *reads* from the GPU through NVML; a test enforces that its code contains no NVML setter calls. The only hardware change in this protocol is clock locking with `nvidia-smi`. You run those commands yourself, after reviewing them. Do not run the protocol on a laptop on battery, in a closed bag, or with blocked vents. Stop if the GPU reports thermal throttling.

**Boundary.** NVML reports GPU board power only. Results calibrate the *accelerator* model, never facility energy.

**Status (2026-10-26).**
* **Laptop (RTX 4060 Laptop GPU).** Clock locking worked. The first run stopped before measuring (PyTorch could not see the GPU). A probe then showed the GPU held to about 51 W of a reported 125 W limit by a power cap, most likely a laptop power budget.
* **Desktop PC (250 W GPU), now the calibration device.** The probe sustained 2685 MHz at exactly its 250 W limit and 70 °C, and the suggested sweep is 1342–2685 MHz. The clock sweep and warm-up have not run yet.

Sessions from the two machines are never fitted together (section 4). Details are in the research log.

## 1. Set up one Administrator window (Windows PowerShell)

Clock locking needs Administrator rights. The calibration commands must run in a Python that has PyTorch **with CUDA**. Do both in the same window. An Administrator window does not inherit the virtual environment from your normal window, so activate it again there.

```powershell
# Start menu > right-click Windows PowerShell > Run as administrator
cd C:\dev\UEIC-Research
.\.venv\Scripts\Activate.ps1                 # the prompt must now start with (.venv)
pip install -r requirements-hw.txt           # NVML bindings
pip uninstall -y torch                       # the default Windows PyTorch from pip is CPU-only
pip install torch --index-url https://download.pytorch.org/whl/cu130
python -m ueic calib check                   # every line must be OK, INFO or WARN; none FAIL
```

`cu130` works with drivers that report CUDA 13.0 or newer in the `nvidia-smi` header. For older drivers, pick the matching build at https://pytorch.org/get-started/locally/.

`calib check` reports four things:
* which Python is running;
* whether a virtual environment is active;
* whether PyTorch is a CUDA build that can see the GPU;
* what NVML reads: power limit, current clock, temperature.

It changes nothing.

**Laptop preparation.**
* Plug in the charger.
* Set Windows power mode to *Best performance*, and use the vendor's performance mode if it has one.
* Close games, browsers with video, and anything else using the GPU.
* Keep the vents clear.

## 2. Find the clock your GPU actually sustains

```powershell
nvidia-smi -i 0 -rgc                         # make sure no clock lock is left from earlier
python -m ueic calib probe                   # 60 s of the compute kernel at default clocks
```

The probe prints:
* the median SM clock the GPU held under load, and how much it varied;
* power, with the limit the GPU reports;
* temperature;
* **which** limit held the clock down, if any, and the likely cause.

It ends with a `calib plan` command containing five suggested lock clocks, spread from half the sustained clock to the sustained clock and snapped to the clocks your driver supports. `python -m ueic calib show` prints the same summary for any recorded session, by default the most recent.

**If the probe reports power at the GPU's own limit** (for example 250 W of 250 W), that is the normal state of a desktop card under full load: the power limit sets the top clock. The suggested sweep is fine. Locks near the top may run a few MHz low, and the fit uses the measured clock. Some drivers do not raise the power-cap flag in this state, so the tool also checks power against the limit.

**If the probe reports a power cap well below the GPU's limit,** a budget set outside the GPU limited it. On a laptop that usually means battery power, a quiet or balanced mode, or a CPU–GPU shared power budget. Fix what you can and probe again, because the sweep should reach the clock the GPU holds without that budget. If the cap cannot be lifted, the suggested clocks still work. The calibration then describes the GPU only up to the capped clock, and the fit records that.

**Why this step exists.** In the simulator, s = 1 is the accelerator's top clock. NVML's "max SM clock" is the top of the driver's clock table, which many GPUs never reach under load. An RTX 4060 Laptop reports 3105 MHz. The fit therefore uses s = clock / f_ref, where f_ref is the highest steady clock among your compute sessions. The power fit uses only clocks between 0.5 × f_ref and f_ref, because that is the range the simulator models. Lock clocks below that range still count towards `beta_compute` and `beta_memory`.

## 3. Print the procedure and run it in the same window

```powershell
python -m ueic calib plan --clocks <the five clocks the probe suggested>
```

The printed plan is the whole procedure:

1. **Leakage warm-up** (about 15 min). Lock the middle clock and let the GPU idle for 5 minutes to cool. Then run a steady compute load for 10 minutes. At constant clock and load, the rise in power as the die warms is attributed to leakage. The fit needs at least 8 K of temperature rise.
2. **Clock sweep** (2 minutes per clock). At each locked clock, run a compute-bound kernel (FP16 matrix multiply) and a memory-bound kernel (FP32 vector update), 60 s each.
3. **Reset.** Finish with `nvidia-smi -i 0 -rgc`. Clock locks persist until you reset them or reboot.

If a lock is not held, for example because the power limit caps the GPU below the requested clock, the fit uses the clock actually measured and prints a note.

## 4. Fit, record, and use the results

```powershell
python -m ueic calib fit data\calibration\* --out data\calibration\calibration.json
python -m ueic calib ingest data\calibration\calibration.json          # stored as measurement experiment M001
python -m ueic run experiments\E001_policy_benchmark.json --calibration data\calibration\calibration.json
```

* **`fit`** prints:
  * the clock reference f_ref, alongside NVML's table maximum;
  * each estimate with its standard error;
  * notes on values outside the ranges swept in E002, unheld locks, power- or thermal-limited sessions, and clocks left out of the power fit.

  Folders without a `session.json`, such as those left by a failed start, are skipped. A calibration describes one GPU. If the folder holds measurement sessions from more than one GPU (for example, after pulling data recorded on another machine), `fit` stops and lists them. Choose one with `--device` and part of its name or UUID; `calib show` prints both. Probe sessions from another GPU are left out with a note. Probe sessions are kept as evidence but never enter a fit. The fitting code is validated in `tests/test_calibration.py`, where it recovers known parameters from synthetic sessions. These include a GPU whose NVML maximum is far above the clock it sustains, and one with a voltage floor at low clocks.
* **`ingest`** writes the estimates into the append-only store as experiment `M001`. Directly measured shape parameters are labelled `physical_measurement`. The leakage power transferred to the simulated accelerator is labelled `engineering_assumption`, because it scales your GPU's leakage *fraction* to a 600 W-class device.
* **`run --calibration`** creates a new experiment `E001C` whose spec records the calibration file's SHA-256, so every calibrated result traces back to the raw telemetry.

Commit the `data/calibration/` folder with the results: it is the evidence behind any calibrated experiment.

## 5. Troubleshooting

| Message or symptom | Cause | Fix |
|---|---|---|
| `PyTorch ... is a CPU-only build` | `pip install torch` on Windows installs the CPU build | `pip uninstall -y torch`, then install from the CUDA index (section 1) |
| `PyTorch is not installed for this Python ... virtual environment NOT active` | The Administrator window is using a different Python from your venv | `.\.venv\Scripts\Activate.ps1` in that window, then `calib check` |
| `PyTorch cannot see a CUDA GPU` (versions before this fix) | Either of the two rows above | Run `python -m ueic calib check`; it names which |
| `running scripts is disabled on this system` when activating | PowerShell execution policy | `Set-ExecutionPolicy -Scope Process RemoteSigned` (this window only), then activate |
| `nvidia-smi -lgc`: insufficient permissions | Not an Administrator window | Reopen PowerShell with *Run as administrator* |
| Note: `locked at X MHz but ran at Y MHz` | Power or thermal limit below the requested clock | Plug in, use the performance power mode, or drop the top clock to what `calib probe` reported |
| Probe: power cap with power far below the reported limit (e.g. 51 W of 125 W) | A power budget set outside the GPU: battery, quiet or balanced mode, CPU–GPU sharing | Plug in, choose the performance mode in Windows and in the laptop maker's app, avoid heavy CPU work during the run, probe again |
| Probe: `user-set clocks (a clock lock is active)` | A lock from an earlier step is still in place | `nvidia-smi -i 0 -rgc`, probe again |
| Probe: `power is at the GPU's reported limit ... although the driver flagged no power cap` | The GPU is at its own power limit; the driver did not set the flag | Nothing to fix on a desktop card. Use the suggested clocks |
| `fit`: `sessions come from 2 different GPUs` | Data from two machines in one folder | `--device "<part of name or UUID>"` (see `calib show`) |
| `fit` note: `fan speed rose from X% to Y% during the warm-up` | Desktop fans draw from the board power NVML reports | Accept the note (kappa_leak is then an upper bound), or fix the fan speed in the card maker's tool for the warm-up and run it again |
| `temperature rose only N K` | The GPU was not cold when the warm-up started | Leave it idle longer: `--idle-before 600` |
| `need compute sessions at >= 4 different clocks between 0.5 x and 1 x` | Too few sweep clocks in the modelled range | Use the clocks `calib probe` suggests |
| Empty folders in `data\calibration` from earlier failed starts | Older versions created the folder before checking PyTorch | Delete them. `fit` skips them either way |
| GPU stays at a fixed clock after you stop | Clock locks persist | `nvidia-smi -i 0 -rgc` |

## 6. What the fits can and cannot tell you

| Fit | Model | Main caveat |
|---|---|---|
| `beta_compute`, `beta_memory` | log(throughput) vs log(clock / f_ref) | Kernel-specific. Real LLM prefill and decode are not these kernels; L09 reports decode is far less clock-sensitive than this memory kernel may be |
| `v_min_ratio` | P = A + P_d·s·v(s)² with v linear in s, using only clocks from 0.5 × f_ref to f_ref (at least 4) | Voltage is not observable through NVML. This fits the registry's functional form, not the true V–f table. f_ref is the highest clock you swept, so it describes the curve below that clock only. Sessions at different temperatures add leakage error |
| `kappa_leak`, leakage fraction | P(T) = c + L·exp(κ(T − 60 °C)) at constant clock and load | Attributes *all* temperature-dependent board power to leakage. Voltage-regulator losses are not separated, so this is an upper bound on leakage sensitivity. On a laptop the fans are powered by the system, so fan power is not in the reading. On a desktop card the fans are powered by the board, so a fan ramp during the warm-up adds to the rise; the fit reports the fan-speed range and notes it |
