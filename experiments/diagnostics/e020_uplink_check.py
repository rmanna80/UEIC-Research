"""EXPLORATORY diagnostic, not a confirmatory experiment; nothing is written to the results store.

Question: does the rack-uplink limit (``uplink_jobs`` = 4 cross-node jobs per rack, ueic/facility/networking.py,
class G) explain the low on-time fraction of E020's 16-node cells? Re-runs the registered cell
``n16|amb20|independent``, seed 1, once as registered and once with the uplink limit effectively removed.

Run after the E020 write-up (PHASE_REPORT, E020 section). Output on the reference machine:
  uplink_jobs=4:       on_time=0.491 util=0.933 ... E/on-time=988.2
  uplink_jobs=1000000: on_time=1.000 util=0.613 ... E/on-time=341.7

Usage: python experiments/diagnostics/e020_uplink_check.py
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ueic.facility.experiment import expand, run_cell  # noqa: E402

spec = json.loads((ROOT / "experiments" / "E020_multinode_joint.json").read_text())
cell = [c for c in expand(spec) if c["scenario"] == "n16|amb20|independent" and c["seed"] == 1][0]
cell["record_timeseries"] = False
for up in (4, 10 ** 6):
    c = copy.deepcopy(cell)
    for r in c["topology"]["racks"]:
        r["uplink_jobs"] = up
    out = run_cell(c)
    m = {k: v[0] for k, v in out["metrics"].items()}
    print(f"uplink_jobs={up}: on_time={m['on_time_frac']:.3f} util={m['utilisation']:.3f} "
          f"unfinished={m['jobs_unfinished']:.0f} work={m['work_done_gpu_s']:.0f} "
          f"E/work={m['E_per_work_kJ']:.3f} E/on-time={m['E_per_on_time_job_kJ']:.1f}", flush=True)
