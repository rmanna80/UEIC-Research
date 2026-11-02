"""EXPLORATORY diagnostic, not a confirmatory experiment; nothing is written to the results store.

Question: is thermal-credit's large gain in E024 at a fixed 25 C supply (S0V0T1D0 vs S0V0T0D0) a thermal effect
or relief of rack-uplink congestion (``uplink_jobs`` = 4, ueic/facility/networking.py, class G)? Re-runs seed 1
of both arms as registered and with the uplink limit effectively removed.

Run after the E024 write-up (PHASE_REPORT, E024 section). Output on the reference machine:
  S0V0T0D0 uplink=4:       on_time=0.470 ... E/on-time=1061.4
  S0V0T0D0 uplink=1000000: on_time=1.000 ... E/on-time=369.9
  S0V0T1D0 uplink=4:       on_time=0.918 ... E/on-time=472.5
  S0V0T1D0 uplink=1000000: on_time=1.000 ... E/on-time=362.9

Usage: python experiments/diagnostics/e024_uplink_check.py
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ueic.facility.experiment import expand, run_cell  # noqa: E402

spec = json.loads((ROOT / "experiments" / "E024_integrated_ablation.json").read_text(encoding="utf-8"))
cells = expand(spec)
for lab in ("S0V0T0D0", "S0V0T1D0"):
    cell = [c for c in cells if c["scenario"] == lab and c["seed"] == 1][0]
    cell["record_timeseries"] = False
    for up in (4, 10 ** 6):
        c = copy.deepcopy(cell)
        for r in c["topology"]["racks"]:
            r["uplink_jobs"] = up
        m = {k: v[0] for k, v in run_cell(c)["metrics"].items()}
        print(f"{lab} uplink={up}: on_time={m['on_time_frac']:.3f} util={m['utilisation']:.3f} "
              f"E/on-time={m['E_per_on_time_job_kJ']:.1f} E_grid={m['E_grid_kWh']:.2f} "
              f"chip_s={m['chip_s_over_target']:.0f}", flush=True)
