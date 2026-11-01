"""Hardware-in-the-loop layer (Stage 9). Four modes, in increasing privilege:

  simulation   mock devices driven by the physics model (tests, dry runs)
  replay       recorded measurements played back with their original time stamps
  read_only    live sensors; no write path exists in read-only adapters
  operator     experimental control of *declared* actuators, only with an unexpired operator grant
               covering the device, the actuation and its range; every write is limit-checked twice
               (grant and device safety limits) and registers a restore action

UEIC does not implement GPU clock, power-limit or fan setters in any mode (charter rule): GPU operating
points are applied by the operator with vendor tools. Independent hardware protection (GPU thermal and
power limits, pump/flow interlocks, PSU protection) stays outside UEIC and is never relaxed by it.
"""

# register adapters
from . import cooling_controller, coolant_sensor, flow_sensor, gpu_adapter, power_meter, pump_adapter  # noqa: E402,F401
