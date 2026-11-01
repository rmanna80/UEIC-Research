"""Real AI inference integration (Stage 4): serving-engine adapters, request tracing, workload drivers,
quality scoring, energy accounting with explicit boundaries, and measurement sessions.

Everything here *reads*: it sends inference requests and reads NVML telemetry. It never changes GPU
clocks, power limits or fans; operating points are set by the operator (see docs/17 and
``python -m ueic infer plan``). Results from the ``mock`` engine are synthetic and labelled as such.
"""
