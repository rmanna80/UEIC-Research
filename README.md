# UEIC: Unified Energy-Intelligent Computing

A research platform for one question: **can an AI computing system lower the facility energy per successful task by coordinating what it computes (clock frequency, model routing) with how it is cooled (coolant temperature, flow, free cooling versus chilling), and how much of that needs joint rather than independent control?**

This repository covers **Phase 0** (problem definition, evaluation criteria, architecture, assumptions, risks, literature matrix), **Phase 1** (a validated simulator, a pre-registered benchmark, sensitivity and robustness studies, a tamper-evident experiment store, report and dashboard), **Phase 2** (a local API and interactive 3-D lab), **Phase 3** (dynamic coolant loop, move suppression, a self-correcting joint controller; experiments E006–E008), and **Phase 4 tooling** (read-only GPU telemetry and calibration, ready to run on your hardware). Every result so far is simulation; no number is a hardware measurement yet.

## Start here

| If you want… | Open |
|---|---|
| The findings and what they rest on | `docs/PHASE_REPORT.md` |
| Every number, generated from the database | `docs/RESULTS.md` |
| The interactive dashboard | `results/dashboard.html` (open in a browser) |
| Every assumption, with its evidence class | `docs/04_assumptions_register.md` |
| Whether a custom chip is justified | `docs/08_hardware_feasibility.md` |
| What happened, in order, including bugs | `docs/research_log.md` |
| The interactive 3-D lab (API + Three.js) | run `python -m ueic serve`, open http://127.0.0.1:8765/lab/ |
| How to measure your own GPU | `docs/09_calibration_protocol.md` |

## Run it (Windows PowerShell)

```powershell
git clone https://github.com/rmanna80/UEIC-Research.git
cd UEIC-Research
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python -m pytest                                   # 82 tests, ~30 s
python -m ueic verify                              # check the results database has not been altered
python -m ueic params                              # print the assumptions register
```

Reproduce or extend the experiments. Each run registers a **new** experiment; old ones are never overwritten:

```powershell
python -m ueic run experiments\E001_policy_benchmark.json --workers 4   # ~4 min on 4 cores
python -m ueic run experiments\E002_sensitivity.json --workers 4
python -m ueic report                              # regenerates docs\RESULTS.md and figures
python -m ueic dashboard                           # regenerates results\dashboard.html
start results\dashboard.html
python -m ueic export E001                         # CSV, JSON and a reproducible bundle (.zip)
```

Phase 2 lab and API (local only, binds to 127.0.0.1):

```powershell
python -m ueic serve                               # then open http://127.0.0.1:8765/lab/
```

The lab has six views: a cooling system bound to the physics model, facility playback of stored runs with before/after comparison, an exploded accelerator package, a conceptual photonic accelerator, an energy-flow diagram per run, and an experiment manager that registers and runs new experiments through the same append-only store. Three.js r185.1 is vendored in `web/vendor/three/` (MIT licence), so the lab works offline; fonts fall back to system fonts without a connection.

To test your own idea, copy a spec in `experiments\`, change the `design` block (scenarios, policies, seeds, `param_overrides`, `variants`), give it a new `key`, and run it. The hypothesis and evaluation criteria are frozen in the database when the run starts. On macOS/Linux, use `/` paths and `source .venv/bin/activate`.

## How the code is organised (suggested reading order)

1. `ueic/params.py`: every number, with unit, evidence class (A–G), source and sensitivity range.
2. `ueic/physics.py`: power, thermal, pump, plant, exergy. Short pure functions with the equations in the docstring.
3. `ueic/sim.py`: the time-stepped simulator and its energy accounting.
4. `ueic/policies.py` and `ueic/twin.py`: the five controllers and the digital twin they plan with.
5. `ueic/store.py` and `ueic/experiment.py`: append-only experiment database, hash chain, runner.
6. `tests/`: what "validated" means here, one test per physical claim.

## Integrity rules the code enforces

* Experiments must be registered with a hypothesis and evaluation criteria before any result is recorded.
* Finished runs, metrics, specs and the research log cannot be edited or deleted (database triggers). Corrections are new records.
* Every finished run is sealed into a SHA-256 hash chain, so `python -m ueic verify` detects tampering even if the triggers are removed.
* Every metric is labelled `simulator_output`, `physical_measurement`, `analytical_calculation`, and so on.
* Superseded and failed experiments stay in the database and in the report.

## Repository notes

* `results/ueic.sqlite` is the experiment record itself. It is committed at milestones (after new experiments), not on every code change, to keep the repository small.
* `results/timeseries/*.csv.gz` hold per-run time series referenced (and hashed) by the database; do not edit or rename them, or `python -m ueic verify` will fail.
