# 00 · Research problem statement

## The problem

Producing useful AI output costs electricity in several places at once. Accelerators convert it into computation and heat. Power-conversion stages lose a fraction on the way in. Pumps, fans and chillers spend more to move that heat outdoors. These costs are coupled. A colder coolant lowers chip temperature and therefore leakage power, but it costs chiller work. A lower clock reduces energy per operation for some kernels, but it keeps chips busy longer and changes how much heat the cooling plant must reject. Conventional practice optimises each layer separately (DVFS and schedulers on the compute side, setpoint controllers on the facility side), or not at all.

## Primary research question

> Can an integrated AI computing system dynamically choose its computation (model, clock, placement) and its cooling (supply temperature, flow, free cooling vs. chilling) to minimise **total facility energy per successful task** while meeting predefined quality, latency and thermal constraints, and how much of any saving requires *joint* rather than *independent* optimisation?

## What Phase 0–1 can and cannot answer

Phase 1 is a simulation study. It can establish:

* whether the coupling mechanisms (leakage–temperature feedback, the clock–energy curve, the supply-temperature–chiller-COP curve, pump scaling) are strong enough, *under stated assumptions*, to make joint optimisation worthwhile;
* which assumptions the conclusions hinge on (so that Phase 4 measurements can target them);
* break-even conditions that do not depend on specific parameter values (e.g. when a model cascade saves energy).

It cannot establish real-world savings. Every simulated number in this project is conditional on the parameter registry (`ueic/params.py`, rendered in `04_assumptions_register.md`). Most hardware and workload parameters there are evidence class E or F. A demonstrated saving (charter §16) requires Phase 4 measurements on real hardware with a valid baseline.

## Measurement boundary (applies to every energy number)

```
grid ─► power conversion (η_conv) ─► accelerators (IT) ─► heat ─► cold plates ─► coolant loop
                                                                         │
                         pump (electric → heat in coolant) ◄─────────────┤
                                                                         ▼
                                         dry cooler (fans) ──► trim chiller (compressor, fans) ──► ambient
```

Included: accelerator power, conversion losses, pump, heat-rejection fans, chiller compressor.
Excluded: host CPUs, networking, storage, room air handling for conversion losses, lighting, building loads, embodied energy. Recovered heat is reported separately (energy and exergy). It is never subtracted from consumption.

## Primary metric

`E_task = E_grid / N_successful`, where a task is *successful* if its output is correct (per the quality model) **and** it completed within its latency SLO. Secondary metrics: total grid energy, IT and cooling breakdown, success rate, SLO violations, p95 latency, peak junction temperature, chip-seconds above the thermal target, chip-seconds throttled by hardware protection, controller overhead.

## Out of scope for Phases 0–1

Training workloads, multi-node placement and network energy, carbon intensity of supply (energy savings do not imply emissions savings; rebound effects may increase total demand), two-phase and immersion cooling models, CFD, photonic/neuromorphic/in-memory hardware models, RTL. Each has a place in the phase plan (`07_phase_plan.md`).
