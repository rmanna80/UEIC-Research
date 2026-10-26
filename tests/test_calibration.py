"""Phase 4 tooling: read-only telemetry and calibration fitting, validated on synthetic
data generated from known parameters (a fit that cannot recover known values from
clean synthetic data should not be trusted on real data)."""
import json
import re
import types
from pathlib import Path

import numpy as np
import pytest

from ueic import calibrate as cal
from ueic import telemetry
from ueic.params import make_config
from ueic.store import Store

TRUE = {"beta_compute": 0.93, "beta_memory": 0.12, "vmin": 0.72, "A": 60.0, "Pd": 230.0, "L": 30.0, "kappa": 0.025}
MAXCLK = 2000.0


def fake_nvml(state):
    """Minimal stand-in for pynvml. Unsupported queries raise, as on many laptop GPUs."""
    class NVMLError(Exception):
        pass

    def unsupported(*a):
        raise NVMLError("Not Supported")
    U = types.SimpleNamespace
    return U(
        NVML_CLOCK_SM=1, NVML_CLOCK_MEM=2, NVML_TEMPERATURE_GPU=0,
        nvmlInit=lambda: None, nvmlShutdown=lambda: None, nvmlSystemGetDriverVersion=lambda: b"999.99",
        nvmlDeviceGetCount=lambda: 1, nvmlDeviceGetHandleByIndex=lambda i: "h0",
        nvmlDeviceGetName=lambda h: b"Fake GPU", nvmlDeviceGetUUID=lambda h: "GPU-fake",
        nvmlDeviceGetMaxClockInfo=lambda h, k: int(MAXCLK) if k == 1 else 9000,
        nvmlDeviceGetEnforcedPowerLimit=lambda h: 300000,
        nvmlDeviceGetPowerUsage=lambda h: int(state["P"] * 1000),
        nvmlDeviceGetTotalEnergyConsumption=unsupported,
        nvmlDeviceGetTemperature=lambda h, k: state["T"],
        nvmlDeviceGetClockInfo=lambda h, k: state["clk"] if k == 1 else 9000,
        nvmlDeviceGetUtilizationRates=lambda h: U(gpu=99, memory=50),
        nvmlDeviceGetPerformanceState=lambda h: 0,
        nvmlDeviceGetCurrentClocksEventReasons=lambda h: 0,
        nvmlDeviceGetFanSpeed=unsupported,
    )


def test_telemetry_module_never_calls_an_nvml_setter():
    src = Path(telemetry.__file__).read_text() + Path(cal.__file__).read_text()
    # no call, and no getattr-by-name, of any NVML setter/reset/clear function
    assert not re.search(r"nvmlDevice(Set|Reset|Clear)\w*\s*\(", src)
    assert not re.search(r"['\"]nvmlDevice(Set|Reset|Clear)", src)


def test_logger_writes_csv_and_metadata_with_hash(tmp_path):
    state = {"P": 123.4, "T": 55, "clk": 1500}
    meta = telemetry.Logger(tmp_path / "t.csv", interval_s=0.02, nvml=fake_nvml(state), label="x").run(0.3)
    rows = telemetry.read_csv(tmp_path / "t.csv")
    assert len(rows) >= 5 and rows[0]["power_W"] == pytest.approx(123.4)
    assert rows[0]["energy_J"] is None and rows[0]["fan_pct"] is None      # unsupported -> None, not a crash
    side = json.loads((tmp_path / "t.meta.json").read_text())
    assert side["provenance"] == "physical_measurement" and "excludes" in side["measurement_boundary"]
    import hashlib
    assert side["csv_sha256"] == hashlib.sha256((tmp_path / "t.csv").read_bytes()).hexdigest()


def test_run_session_records_workload_and_telemetry(tmp_path):
    state = {"P": 200.0, "T": 60, "clk": 1200}
    d = cal.run_session("compute", 0.6, tmp_path, label="clk=1200", interval_s=0.02,
                        nvml=fake_nvml(state), workload=lambda budget: 42.0)
    s = cal.load_session(d)
    assert s.kind == "compute" and len(s.work) >= 1 and s.work[0, 1] == 42.0
    assert any(r["label"] == "compute" for r in s.tel)


# ------------------------------------------------------------- synthetic sessions
def _power(s, T):
    v = cal.v_of_s(s, TRUE["vmin"])
    return TRUE["A"] + TRUE["Pd"] * s * v ** 2 + TRUE["L"] * np.exp(TRUE["kappa"] * (T - 60.0))


def _write_session(root, kind, clk, rng, seconds=60.0, warm=False):
    d = Path(root) / f"{kind}_{clk}"
    d.mkdir()
    s = clk / MAXCLK
    t = np.arange(0, seconds, 0.1)
    T = 35.0 + 35.0 * (1 - np.exp(-t / 150.0)) if warm else np.full_like(t, 62.0)
    P = _power(s, T) + rng.normal(0, 0.8, t.size)
    with open(d / "telemetry.csv", "w") as f:
        f.write(",".join(telemetry.FIELDS) + "\n")
        for ti, Ti, Pi in zip(t, T, P):
            f.write(f"{1000 + ti},0,{Pi},,{Ti},{clk},9000,99,50,0,0,,{kind}\n")
    beta = TRUE["beta_memory"] if kind == "memory" else TRUE["beta_compute"]
    tw = np.arange(0, seconds, 0.5)
    thr = 100.0 * s ** beta * (1 + rng.normal(0, 0.003, tw.size))
    np.savetxt(d / "workload.csv", np.column_stack([1000 + tw, thr]), delimiter=",", header="t_unix,throughput", comments="")
    (d / "session.json").write_text(json.dumps({"kind": kind, "label": f"clk={clk}", "device": {
        "index": 0, "name": "Synthetic", "max_sm_clock_MHz": MAXCLK}}))
    return d


@pytest.fixture
def sessions(tmp_path):
    rng = np.random.default_rng(0)
    ds = [_write_session(tmp_path, "warmup", 1400, rng, seconds=900, warm=True)]
    for clk in (900, 1200, 1500, 1800, 2000):
        ds.append(_write_session(tmp_path, "compute", clk, rng))
        ds.append(_write_session(tmp_path, "memory", clk, rng))
    return ds


def test_fits_recover_known_parameters(sessions):
    out = cal.calibrate(sessions)
    f = out["fits"]
    assert f["beta_compute"]["value"] == pytest.approx(TRUE["beta_compute"], abs=0.01)
    assert f["beta_memory"]["value"] == pytest.approx(TRUE["beta_memory"], abs=0.01)
    assert f["leakage"]["kappa"] == pytest.approx(TRUE["kappa"], abs=0.002)
    assert f["leakage"]["L_ref_W"] == pytest.approx(TRUE["L"], rel=0.1)
    # compute sessions run at 62 C, so leakage is a constant offset folded into A
    assert f["power_vs_clock"]["v_min_ratio"] == pytest.approx(TRUE["vmin"], abs=0.03)
    # beta_memory = 0.12 is below the registry range swept in E002: the report must say so
    assert any("beta_memory" in n for n in out["notes"])
    make_config({k: v["value"] for k, v in out["overrides"].items()})


def test_fit_refuses_when_temperature_barely_moves(tmp_path):
    rng = np.random.default_rng(1)
    d = _write_session(tmp_path, "warmup", 1400, rng, seconds=120, warm=False)
    r = cal.fit_leakage(cal.load_session(d))
    assert not r["ok"] and "temperature" in r["reason"]


def test_apply_and_ingest_calibration(sessions, tmp_path):
    calib = cal.calibrate(sessions)
    spec = json.loads((Path(__file__).resolve().parents[1] / "experiments" / "E001_policy_benchmark.json").read_text())
    s2 = cal.apply_calibration(spec, calib, "abc")
    assert s2["key"] == "E001C" and s2["design"]["param_overrides"]["kappa_leak"] == calib["overrides"]["kappa_leak"]["value"]
    st = Store(tmp_path / "m.sqlite")
    exp_id = cal.ingest(st, calib, "abc")
    run = st.runs(exp_id)[0]
    assert run["metrics"]["beta_memory"] == calib["overrides"]["beta_memory"]["value"]
    meta = st.metric_meta(exp_id)
    assert meta["beta_memory"][1] == "physical_measurement"
    assert meta["p_leak_ref"][1] == "engineering_assumption"
    assert st.verify_chain()[0]
    st.close()


def test_plan_never_contains_commands_ueic_would_execute():
    txt = cal.plan_commands([900, 1500])
    assert "-rgc" in txt and "Administrator" in txt
