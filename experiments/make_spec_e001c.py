"""Pre-registered spec for E001C: the Phase 1 benchmark with the M001 calibration applied.

Written and committed before E001C ran. The calibration values were known; E001C results were not.
Usage:  python experiments/make_spec_e001c.py
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ueic.calibrate import apply_calibration  # noqa: E402

HERE = Path(__file__).resolve().parent
CALIB = ROOT / "data" / "calibration" / "M001_calibration.json"

base = json.loads((HERE / "E001_policy_benchmark.json").read_text())
raw = CALIB.read_bytes()
spec = apply_calibration(base, json.loads(raw), hashlib.sha256(raw).hexdigest())
over = {k: v["value"] for k, v in spec["calibration_source"]["overrides"].items()}

spec["title"] = "Policy benchmark with measured clock sensitivity (M001: RTX 5070)"
spec["research_question"] = ("Do the Phase 1 conclusions survive when the two parameters measured on real hardware "
                             "(clock sensitivity of compute-bound and memory-bound work) replace the placeholders?")
spec["inherits"] = "E001 (same design, seeds and workloads; only the calibrated parameters differ)"
spec["hypothesis"] = (
    "Inherited from E001 and re-tested: H1: joint uses less energy per successful task than independent in at least "
    "4 of 6 scenarios (paired 95% CI entirely below 0), without more SLO violations or thermal-limit exceedances. "
    "H2: every optimising policy uses less energy per successful task than fixed in every scenario. "
    "New: HC1: compute_only saves more energy per successful task relative to fixed in E001C than in E001, in all 6 "
    "scenarios (seed-paired change in relative saving, 95% CI entirely below 0), because with beta_memory = 0 "
    "memory-bound phases lose no throughput when the clock drops. HC2: that change is largest in S5_memory_heavy. "
    "HC3: joint's advantage over independent changes by less than 0.5 percentage points (95% CI of the seed-paired "
    "change within +/-0.5 pp) in at least 5 of 6 scenarios, because both policies use the same DVFS model.")
spec["null_hypothesis"] = "Calibrating clock sensitivity changes neither the savings from DVFS nor the policy ranking."
spec["dependent_variables"] = base.get("dependent_variables", []) + [
    "seed-paired change vs E001 in compute_only/fixed and joint/independent relative energy per successful task"]
spec["baseline"] = "E001 (latest stored version) for HC1-HC3; fixed and independent within E001C for H1-H2"
spec["evaluation_criteria"] = (
    "As E001 for H1-H2 (paired 95% t-CI, practical threshold 1%). HC1-HC3: for each scenario and seed, "
    "d = (a/b - 1) in E001C minus (a/b - 1) in E001 on E_per_success_kJ, with a/b = compute_only/fixed (HC1, HC2) or "
    "joint/independent (HC3); 95% t-CI over the 10 seeds.")
spec["configuration"] = f"E001 design with calibrated overrides {over}; every other parameter at its registry value."
spec["known_limitations"] = (
    "Only clock sensitivity is calibrated. v_min_ratio, kappa_leak and p_leak_ref stay registry placeholders: their fits "
    "were rejected (docs/10). The measured power-vs-clock shape is not represented: with registry defaults the simulator "
    "misstates normalised power by up to 0.09 and energy per unit of work by up to 0.09 of the top-clock value. "
    "beta_memory = 0 comes from a pure streaming kernel and is a bound for LLM decode, not a measurement of it. "
    "One consumer GPU.")
spec["disclosure"] = (
    "The calibration values were known when these hypotheses were written; E001C results were not. Acceptance rules "
    "R1-R3 were set after seeing the first desktop fit summary and before examining raw telemetry. Before registration, "
    "a forensic check re-ran 24 seed-0 E001 cells with the first (rejected) fit's values to identify orphaned time-series "
    "files; only their time series were compared, not their outcomes. No runs with the accepted values preceded "
    "registration.")

if __name__ == "__main__":
    out = HERE / "E001C_calibrated.json"
    out.write_text(json.dumps(spec, indent=2))
    print("wrote", out.name, "with overrides", over)
