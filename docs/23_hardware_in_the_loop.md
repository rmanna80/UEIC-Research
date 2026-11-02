# 23 · Hardware-in-the-loop: adapters, permissions and an instrumentation plan (Stage 9)

**Status:**
* Software: implemented and tested with mock devices and a replayed RTX 5070 NVML recording (`ueic/hardware/`, `tests/test_stage9_hardware.py`).
* No instrument beyond the GPU's own sensors has been bought or connected.
* No actuator driver for real hardware has been written, on purpose (§4).
* Nothing has been purchased, and nothing will be purchased by this software.

## 1. Modes

| Mode | What runs | Writes |
|---|---|---|
| `simulation` | Mock devices driven by the registry physics (`mock_gpu`, `mock_power_meter`, `mock_coolant_sensor`, `mock_flow_sensor`, `mock_pump`, `mock_cooling_controller`) | Mock actuators only |
| `replay` | Recorded data played back with its own time stamps (`replay_gpu` reads `ueic.telemetry` CSVs; the CSV ingest sensors read logged files) | None |
| `read_only` | Live sensors: `nvml_gpu`, plus CSV ingest for instruments whose own software logs to a file | None: read-only adapters have no write path |
| `operator` | Declared actuators, under an unexpired operator grant | Range- and step-limited, with restore on exit |

Every adapter declares its capabilities:
* what it reads (with units);
* what it may write (range, maximum step, safe value);
* its safety limits;
* its **measurement boundary**;
* the provenance of its readings;
* its calibration status.

`create(kind, mode)` refuses a mode the adapter does not support before any device is opened.

## 2. Grants and guarded writes

* An operator creates a grant naming:
  * themselves;
  * one device and one actuation;
  * a value range;
  * a duration of at most 4 h.

  They must type `I AUTHORIZE`, and grants are saved as JSON.
* A write through `GuardedSession` is allowed only if all of these hold:
  * mode is `operator`;
  * the device declares the actuation;
  * the value is inside the device's safety range;
  * an unexpired grant covers it;
  * the step from the current setpoint is within the declared maximum step.
* Every write registers a restore action. Restores run on exit, including after an exception, and return each actuator to its declared safe value (tested).

GPU clocks, power limits and fans are **not** writable in any mode. This is a charter rule: the operator applies GPU operating points with vendor tools, and UEIC only checks them (calibration guard, inference clock guard). A test fails if any file in `ueic/hardware/` contains an NVML setter, an `nvidia-smi` clock or limit command, or a subprocess call.

## 3. What each instrument would add (and which experiment needs it)

| Quantity | Why | Experiments | Today |
|---|---|---|---|
| Host wall power | Turns the GPU-only boundary into a host boundary (CPU, RAM, PSU losses) | E017, E023 | Not measured |
| Coolant supply/return temperature | Measures heat removed (with flow) and the loop's dynamics | E015/E016 validation, M-series loop tests | No liquid loop |
| Coolant flow | Heat removed = ṁ c_p ΔT; separates fouling from low flow (E019 limitation) | E016, E019 | – |
| Differential pressure | Pump curve and branch resistance (`cooling_network`) | E020 validation | – |
| Controllable pump/CDU | Closed-loop tests of supply control and the safety filter | E015 on hardware | – |

## 4. Equipment categories and requirements (no purchases; no prices are given because they change)

**Power meters:**
* *Low budget:* a plug-in energy monitor that logs to a computer (CSV export), with the stated accuracy class recorded.
* *Better:* a power analyser or metered PDU with documented accuracy, sampling of at least 1 Hz and a time-stamped log.
* *Requirements:* true-RMS measurement; time synchronisation with the host (log both clocks); a calibration certificate or a check against a resistive load of known power.

**Temperature sensors:**
* *Low budget:* 10k NTC thermistors or DS18B20-class digital probes (±0.5 K class), with an ice-point check.
* *Better:* Pt100/Pt1000 RTDs (IEC 60751 class A) in immersion wells, read by a 4-wire or ratiometric RTD front end.
* *Requirements:* matched supply/return probes (the ΔT error dominates the heat measurement). Calibrate both probes together in a stirred bath and record the offset.

**Flow meters:**
* *Low budget:* a turbine/Hall-effect flow sensor, calibrated by timing a weighed volume (bucket, scale, stopwatch).
* *Better:* an inline magnetic flow meter (water is conductive enough) or an ultrasonic clamp-on meter specified for the pipe size.
* *Requirements:* a range that covers the loop's flow at good resolution; straight pipe runs as the maker specifies.

**Differential pressure:**
* A transmitter across the cold-plate branch, with range matched to the expected drop (tens of kPa for small loops).

**Data acquisition:**
* *Low budget:* a microcontroller with a 16-bit ADC (ADS1115 class) or digital probes, streaming CSV over USB.
* *Better:* a USB DAQ with RTD/thermocouple inputs and its own logging software.
* UEIC ingests either through the CSV adapters. Instrument-specific drivers are written only after an instrument is chosen; no vendor protocol is assumed now.

**Controlled cooling loop:**
* Recommended first step: a **thermal test vehicle** instead of liquid-cooling the GPU. Use resistive cartridge heaters in a cold-plate block with a known, adjustable heat load, a small pump, a reservoir, a radiator or plate heat exchanger, and the sensors above. It exercises E015/E016 dynamics without risking the GPU.
* Liquid-cooling a GPU (an aftermarket water block) is invasive. It voids warranties and adds leak risk over expensive electronics. It is not recommended for this project's stage.

## 5. Calibration

* Temperature: ice point (0 °C) plus a warm stirred bath against a reference thermometer, recording offsets and uncertainty.
* Flow: gravimetric (mass collected over time) at 3 or more flows.
* Power: a known resistive load, or comparison with a reference meter.
* GPU (NVML): no independent calibration is possible without a wall meter. The board sensor's evidence class stays B on that card only.
* Every calibration is recorded with date, method, reference and uncertainty, and attached to sessions as metadata. The adapters' `calibration` field carries it.

## 6. Electrical and thermal safety

* Mains wiring, PDUs and any instrument in the mains path are installed by a qualified person. Use RCD/GFCI protection.
* Water and electronics:
  * drip trays;
  * leak detection that cuts pump and heater power;
  * no fluid lines above powered electronics;
  * fluid compatible with the wetted materials;
  * pressure relief or an open reservoir.
* The heaters in a thermal test vehicle need an independent over-temperature cutout (a thermal fuse or bimetal switch) that does not depend on software.
* The pump needs an independent low-flow interlock that cuts the heat load.
* GPU thermal and power protection must never be disabled or raised. UEIC has no code path that could do it.
* Experiments with actuators run only with an operator present, inside a grant, with restore-on-exit. They never run autonomously.

## 7. How to use it now

```python
import ueic.hardware
from ueic.hardware.hardware_registry import create
from ueic.hardware.permissions import Mode
from ueic.hardware.telemetry import TelemetryBus
gpu = create("replay_gpu", Mode.REPLAY, csv_path="data/calibration/<session>/telemetry.csv")
TelemetryBus([gpu], "data/hardware/replay_test.csv").collect(100)
```
