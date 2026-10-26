"""Phase 4 tooling: read-only telemetry and calibration fitting, validated on synthetic
data generated from known parameters (a fit that cannot recover known values from
clean synthetic data should not be trusted on real data)."""
import json
import re
import sys
import time
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


# ------------------------------------------------------------- environment diagnosis
def _fake_torch(cuda_build, available):
    m = types.ModuleType("torch")
    m.__version__ = "2.13.0" + ("" if cuda_build else "+cpu")
    m.version = types.SimpleNamespace(cuda=cuda_build)
    m.cuda = types.SimpleNamespace(is_available=lambda: available, device_count=lambda: 1 if available else 0,
                                   get_device_name=lambda i: "Fake CUDA GPU")
    return m


@pytest.mark.parametrize("torch_mod, phrase", [(None, "not installed"), ("cpu", "CPU-only"),
                                                ("nodev", "sees no CUDA GPU")])
def test_missing_gpu_support_is_diagnosed_and_leaves_no_folder(tmp_path, monkeypatch, torch_mod, phrase):
    """Field failure, RTX 4060 Laptop, 2026-10-26: 'PyTorch cannot see a CUDA GPU', with an empty
    session folder left behind. The message must say which case it is and nothing may be written."""
    fake = {None: None, "cpu": _fake_torch(None, False), "nodev": _fake_torch("13.0", False)}[torch_mod]
    monkeypatch.setitem(sys.modules, "torch", fake)          # None makes `import torch` raise ImportError
    with pytest.raises(RuntimeError, match=phrase) as e:
        cal.run_session("warmup", 1.0, tmp_path / "cal", nvml=fake_nvml({"P": 20.0, "T": 40, "clk": 1500}))
    assert sys.executable in str(e.value)
    assert not (tmp_path / "cal").exists() or not any((tmp_path / "cal").iterdir())


def test_check_reports_each_component(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(None, False))
    res = dict((m.split()[0], s) for s, m in cal.check(0, nvml=fake_nvml({"P": 20.0, "T": 40, "clk": 1500})))
    assert res["PyTorch"] == "fail" and res["NVML:"] == "ok"
    monkeypatch.setitem(sys.modules, "torch", _fake_torch("13.0", True))
    res = cal.check(0, nvml=fake_nvml({"P": 20.0, "T": 40, "clk": 1500}))
    assert not any(s == "fail" for s, _ in res)


# ------------------------------------------------------------- synthetic sessions
def _power(s, T, floor=False):
    v = cal.v_of_s(s, TRUE["vmin"])
    if floor:                       # real GPUs hold a minimum voltage below some clock
        v = np.maximum(v, TRUE["vmin"])
    return TRUE["A"] + TRUE["Pd"] * s * v ** 2 + TRUE["L"] * np.exp(TRUE["kappa"] * (T - 60.0))


def _write_session(root, kind, clk, rng, seconds=60.0, warm=False, f_top=MAXCLK, nvml_max=MAXCLK,
                   label_clk=None, floor=False):
    """`clk` is the clock the GPU actually ran at; `label_clk` the clock the user locked (default: same);
    `f_top` the highest clock the GPU sustains (s = 1 in the truth model); `nvml_max` what NVML reports."""
    d = Path(root) / f"{kind}_{clk}"
    d.mkdir()
    s = clk / f_top
    t = np.arange(0, seconds, 0.1)
    T = 35.0 + 35.0 * (1 - np.exp(-t / 150.0)) if warm else np.full_like(t, 62.0)
    P = _power(s, T, floor) + rng.normal(0, 0.8, t.size)
    with open(d / "telemetry.csv", "w") as f:
        f.write(",".join(telemetry.FIELDS) + "\n")
        for ti, Ti, Pi in zip(t, T, P):
            f.write(f"{1000 + ti},0,{Pi},,{Ti},{clk},9000,99,50,0,0,,{kind}\n")
    beta = TRUE["beta_memory"] if kind == "memory" else TRUE["beta_compute"]
    tw = np.arange(0, seconds, 0.5)
    thr = 100.0 * s ** beta * (1 + rng.normal(0, 0.003, tw.size))
    np.savetxt(d / "workload.csv", np.column_stack([1000 + tw, thr]), delimiter=",", header="t_unix,throughput", comments="")
    (d / "session.json").write_text(json.dumps({"kind": kind, "label": f"clk={label_clk or clk}", "device": {
        "index": 0, "name": "Synthetic", "max_sm_clock_MHz": nvml_max}}))
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
    assert "calib check" in txt and "Activate.ps1" in txt


# ------------------------------------------------------------- clock reference and sweep design
def test_clock_reference_is_highest_measured_clock_not_nvml_table_max(tmp_path):
    """Laptop case: NVML reports 3105 MHz, the GPU sustains 2000 MHz. Normalising by 3105 would put
    the whole sweep below s_min and corrupt v_min_ratio; normalising by the measured top recovers it."""
    rng = np.random.default_rng(3)
    ds = [_write_session(tmp_path, kind, clk, rng, f_top=2000.0, nvml_max=3105.0)
          for clk in (1000, 1250, 1500, 1750, 2000) for kind in ("compute", "memory")]
    out = cal.calibrate(ds)
    assert out["clock_reference"]["f_ref_MHz"] == 2000.0
    assert out["clock_reference"]["nvml_max_sm_clock_MHz"] == 3105.0
    assert out["fits"]["power_vs_clock"]["v_min_ratio"] == pytest.approx(TRUE["vmin"], abs=0.03)
    assert out["fits"]["beta_compute"]["value"] == pytest.approx(TRUE["beta_compute"], abs=0.01)


def test_power_fit_leaves_out_clocks_below_s_min(tmp_path):
    """Below s_min real GPUs sit at a voltage floor the registry form cannot represent; those
    sessions must not enter the v_min_ratio fit, and the report must say they were left out."""
    rng = np.random.default_rng(4)
    ds = [_write_session(tmp_path, "compute", clk, rng, floor=True) for clk in (500, 700, 900, 1200, 1500, 1800, 2000)]
    out = cal.calibrate(ds)
    fp = out["fits"]["power_vs_clock"]
    assert fp["excluded_s"] == [0.25, 0.35, 0.45] and fp["n"] == 4
    assert fp["v_min_ratio"] == pytest.approx(TRUE["vmin"], abs=0.03)
    assert any("left out" in n for n in out["notes"])
    # the same data fitted over the whole range is biased: the exclusion is doing real work
    allpts = cal.fit_power_clock(out["sessions"], s_floor=0.0)
    assert abs(allpts["v_min_ratio"] - TRUE["vmin"]) > abs(fp["v_min_ratio"] - TRUE["vmin"])


def test_unheld_clock_lock_is_flagged(tmp_path):
    rng = np.random.default_rng(5)
    ds = [_write_session(tmp_path, "compute", clk, rng) for clk in (1000, 1500)]
    ds.append(_write_session(tmp_path, "compute", 1850, rng, label_clk=2000))   # power-limited at 1850
    out = cal.calibrate(ds)
    assert any("not held" in n and "2000" in n and "1850" in n for n in out["notes"])
    assert out["clock_reference"]["f_ref_MHz"] == 1850.0          # measured, not requested


def test_suggest_clocks_spans_half_to_sustained_on_the_driver_grid():
    c = cal.suggest_clocks(2535.0)
    assert len(c) == 5 and c == sorted(c) and all(x % 15 == 0 for x in c)
    assert c[-1] <= 2535 and abs(c[0] - 2535 / 2) <= 7.5
    assert cal.suggest_clocks(2535.0, supported=list(range(210, 3106, 15))) == c
    coarse = cal.suggest_clocks(2600.0, supported=[1000, 1300, 1600, 1900, 2200, 2500, 2800])
    assert coarse[-1] == 2500 and coarse[0] == 1300


def test_probe_measures_sustained_clock_and_suggests_a_sweep(tmp_path):
    def work(budget):
        time.sleep(min(budget, 0.05))
        return 10.0
    r = cal.probe(1.0, out_root=tmp_path, nvml=fake_nvml({"P": 95.0, "T": 70, "clk": 2400}), workload=work,
                  skip_s=0.0, interval_s=0.02)
    assert r["ok"] and r["clock_MHz"] == 2400.0 and r["kind"] == "probe"
    assert r["suggested_clocks"][-1] == 2400 and r["suggested_clocks"][0] == 1200
    # probe sessions are evidence only: they never enter a fit
    out = cal.calibrate([r["path"]])
    assert out["clock_reference"]["f_ref_MHz"] is None and not out["overrides"]
