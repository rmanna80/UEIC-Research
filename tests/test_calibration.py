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
    assert rows[0]["power_limit_W"] == pytest.approx(300.0)                 # enforced limit, every sample
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
                   label_clk=None, floor=False, reasons=0, power=None, temp=62.0, power_limit=None,
                   name="Synthetic", uuid=None, folder=None, fan_ramp=False, dip=None, clk_step=None):
    """`clk` is the clock the GPU actually ran at; `label_clk` the clock the user locked (default: same);
    `f_top` the highest clock the GPU sustains (s = 1 in the truth model); `nvml_max` what NVML reports."""
    d = Path(root) / (folder or f"{kind}_{clk}")
    d.mkdir()
    s = clk / f_top
    t = np.arange(0, seconds, 0.1)
    T = 35.0 + 35.0 * (1 - np.exp(-t / 150.0)) if warm else np.full_like(t, temp)
    P = (_power(s, T, floor) if power is None else np.full_like(t, power)) + rng.normal(0, 0.8, t.size)
    if dip:                                    # (t_start, t_end, fraction): load drops, power falls with it
        P[(t >= dip[0]) & (t < dip[1])] -= 8.0
    clks = np.full(t.size, float(clk))
    if clk_step:                               # (t_at, new_clock, power_drop): driver drops one clock step
        clks[t >= clk_step[0]] = clk_step[1]
        P[t >= clk_step[0]] -= clk_step[2]
    with open(d / "telemetry.csv", "w") as f:
        f.write(",".join(telemetry.FIELDS) + "\n")
        for ti, Ti, Pi, ci in zip(t, T, P, clks):
            fan = f"{30 + 50 * (1 - np.exp(-ti / 150.0)):.0f}" if fan_ramp else ""
            f.write(f"{1000 + ti},0,{Pi},,{Ti},{ci:g},9000,99,50,0,{reasons},{fan},{kind}\n")   # pre-power_limit format
    beta = TRUE["beta_memory"] if kind == "memory" else TRUE["beta_compute"]
    tw = np.arange(0, seconds, 0.5)
    thr = 100.0 * s ** beta * (1 + rng.normal(0, 0.003, tw.size))
    if dip:
        thr[(tw >= dip[0]) & (tw < dip[1])] *= 1.0 - dip[2]
    np.savetxt(d / "workload.csv", np.column_stack([1000 + tw, thr]), delimiter=",", header="t_unix,throughput", comments="")
    label = "default-clocks" if kind == "probe" else f"clk={label_clk or clk}"   # probes run unlocked
    (d / "session.json").write_text(json.dumps({"kind": kind, "label": label, "device": {
        "index": 0, "name": name, "uuid": uuid, "max_sm_clock_MHz": nvml_max, "power_limit_W": power_limit}}))
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


# ------------------------------------------------------------- which limit held the clock down
def test_laptop_power_cap_is_named_and_explained(tmp_path, capsys):
    """Field reading, RTX 4060 Laptop probe 2026-10-26: 1860 MHz, 51.4 W, 58 C, 'power/thermal-limited
    100%' while NVML reported a 125 W limit. The tool must say which limit, and that the budget came
    from outside the GPU. This session uses the older telemetry format (no per-sample limit column)."""
    rng = np.random.default_rng(6)
    d = _write_session(tmp_path, "probe", 1860, rng, power=51.4, temp=58.0, reasons=0x4, power_limit=125.0)
    r = cal.show_session(d)
    assert r["limit_reasons"] == {"sw_power_cap": 1.0} and r["power_limit_W"] == 125.0
    text = " ".join(r["interpretation"])
    assert "power cap" in text and "battery" in text and "125 W" in text
    assert "temperature" not in text.split("likely cause")[1]          # not blamed on heat at 58 C
    from ueic.__main__ import main
    assert main(["calib", "show", str(d)]) == 0
    out = capsys.readouterr().out
    assert "1860 MHz" in out and "power cap" in out


def test_no_power_story_when_power_is_near_the_limit(tmp_path):
    rng = np.random.default_rng(7)
    d = _write_session(tmp_path, "probe", 2400, rng, power=118.0, temp=70.0, reasons=0x4, power_limit=125.0)
    text = " ".join(cal.show_session(d)["interpretation"])
    assert "power cap" in text and "battery" not in text                # the GPU's own limit, as designed


def test_leftover_clock_lock_is_detected(tmp_path):
    rng = np.random.default_rng(8)
    d = _write_session(tmp_path, "probe", 1500, rng, power=40.0, reasons=0x2, power_limit=125.0)
    r = cal.show_session(d)
    assert r["limited_frac"] == 0.0 and any("-rgc" in x for x in r["interpretation"])


def test_latest_session_picks_newest_folder(tmp_path):
    rng = np.random.default_rng(9)
    for name in ("20261026T190000_probe", "20261026T195900_probe"):
        d = _write_session(tmp_path, "probe", 1800, rng)
        d.rename(tmp_path / name)
    (tmp_path / "20261026T235959_empty").mkdir()                        # failed start: no session.json
    assert cal.latest_session(tmp_path).name == "20261026T195900_probe"


# ------------------------------------------------------------- one calibration = one GPU
def test_sessions_from_two_gpus_are_not_fitted_together(tmp_path):
    """Field case, 2026-10-26: a probe on a second machine (250 W limit, different clock table) landed
    next to sessions from the RTX 4060 Laptop. Mixing them would fit one curve to two chips."""
    rng = np.random.default_rng(10)
    ds = [_write_session(tmp_path, "compute", c, rng, name="GPU A", uuid="GPU-aaaa", folder=f"a_{c}")
          for c in (1000, 1250, 1500, 1750, 2000)]
    ds += [_write_session(tmp_path, "compute", c, rng, name="GPU B", uuid="GPU-bbbb", folder=f"b_{c}")
           for c in (1200, 1800)]
    with pytest.raises(ValueError, match="2 different GPUs") as e:
        cal.calibrate(ds)
    assert "GPU A" in str(e.value) and "GPU B" in str(e.value)
    out = cal.calibrate(ds, device="gpu a")
    assert len(out["sessions"]) == 5 and out["fits"]["power_vs_clock"]["ok"]
    assert cal.devices_in(tmp_path) == {"GPU A (GPU-aaaa)": 5, "GPU B (GPU-bbbb)": 2}
    from ueic.__main__ import main
    assert main(["calib", "fit", str(tmp_path / "*"), "--out", str(tmp_path / "c.json")]) == 2
    assert main(["calib", "fit", str(tmp_path / "*"), "--out", str(tmp_path / "c.json"), "--device", "GPU-aaaa"]) == 0


def test_power_at_limit_without_a_cap_flag_is_pointed_out(tmp_path, capsys):
    """Field reading, second probe 2026-10-26: 2685 MHz, 250.0 W median against a 250 W limit,
    no clock-event reason set. The clock is probably power-limited even though nothing is flagged."""
    rng = np.random.default_rng(11)
    d = _write_session(tmp_path, "probe", 2685, rng, power=250.0, temp=70.0, reasons=0, power_limit=250.0,
                       name="Second GPU", uuid="GPU-cccc")
    r = cal.show_session(d)
    text = " ".join(r["interpretation"])
    assert "reported limit" in text and "battery" not in text
    from ueic.__main__ import main
    assert main(["calib", "show", str(d)]) == 0
    out = capsys.readouterr().out
    assert "GPU: Second GPU (GPU-cccc)" in out


def test_probe_from_another_gpu_does_not_block_a_fit(tmp_path):
    rng = np.random.default_rng(12)
    ds = [_write_session(tmp_path, "compute", c, rng, name="GPU A", uuid="GPU-aaaa", folder=f"a_{c}")
          for c in (1000, 1250, 1500, 1750, 2000)]
    ds.append(_write_session(tmp_path, "probe", 1860, rng, name="GPU B", uuid="GPU-bbbb", folder="b_probe"))
    out = cal.calibrate(ds)
    assert len(out["sessions"]) == 5 and any("GPU B" in n and "probe" in n for n in out["notes"])


def test_power_limited_probe_is_marked(tmp_path):
    rng = np.random.default_rng(13)
    d = _write_session(tmp_path, "probe", 2685, rng, power=250.0, power_limit=250.0)
    assert cal.show_session(d)["at_power_limit"] is True
    d2 = _write_session(tmp_path, "probe", 1500, rng, power=120.0, power_limit=250.0)
    assert cal.show_session(d2)["at_power_limit"] is False


def test_fan_ramp_during_warmup_is_noted(tmp_path):
    """Desktop cards power their fans from the board, so a fan ramp adds to the 'leakage' rise."""
    rng = np.random.default_rng(14)
    out = cal.calibrate([_write_session(tmp_path, "warmup", 1400, rng, seconds=900, warm=True, fan_ramp=True)])
    assert out["fits"]["leakage"]["ok"] and out["fits"]["leakage"]["fan_pct_range"][1] > 70
    assert any("fan speed rose" in n for n in out["notes"])


# ------------------------------------------------------------- what may be transferred to the simulator
def _desktop_summary_candidates():
    """The estimates printed by the first desktop fit (2026-10-26), as the fitter produced them."""
    return [
        {"name": "beta_compute", "value": 0.983, "se": 0.004465, "evidence": "B", "at_bound": []},
        {"name": "beta_memory", "value": -0.0557, "se": 0.04027, "evidence": "B", "at_bound": []},
        {"name": "v_min_ratio", "value": 0.3, "se": 0.1848, "evidence": "B", "at_bound": ["v_min_ratio"]},
        {"name": "kappa_leak", "value": 0.2, "se": 0.05612, "evidence": "B", "at_bound": ["kappa"]},
        {"name": "p_leak_ref", "value": 22.74, "se": None, "evidence": "E", "at_bound": [], "derived_from": "kappa_leak"},
    ]


def test_first_desktop_fit_would_not_have_transferred_failed_fits():
    acc, rej = cal.accept_estimates(_desktop_summary_candidates())
    assert acc["beta_compute"]["status"] == "accepted" and acc["beta_compute"]["value"] == 0.983
    assert acc["beta_memory"]["value"] == 0.0 and acc["beta_memory"]["measured"] == -0.0557   # R3, CI reaches 0
    assert "edge of its allowed range" in rej["v_min_ratio"]["reason"]                         # R1
    assert "edge of its allowed range" in rej["kappa_leak"]["reason"]                          # R1
    assert "derived from kappa_leak" in rej["p_leak_ref"]["reason"]
    make_config({k: v["value"] for k, v in acc.items()})


def test_imprecise_and_unphysical_estimates_are_rejected():
    acc, rej = cal.accept_estimates([
        {"name": "kappa_leak", "value": 0.02, "se": 0.05, "evidence": "B", "at_bound": []},      # CI wider than range
        {"name": "beta_memory", "value": -0.5, "se": 0.04, "evidence": "B", "at_bound": []},     # far below 0
        {"name": "beta_compute", "value": 1.004, "se": 0.004, "evidence": "B", "at_bound": []},  # CI reaches 1
    ])
    assert "wider than the registry range" in rej["kappa_leak"]["reason"]
    assert "physical range" in rej["beta_memory"]["reason"]
    assert acc["beta_compute"]["value"] == 1.0 and acc["beta_compute"]["status"] == "at physical limit"


def test_flat_then_steep_power_curve_is_caught_at_the_bound():
    """Real voltage-frequency curves stay near a floor, then rise steeply. The registry's linear v(s)
    cannot follow that, and the fit runs to its lower bound instead of failing loudly."""
    summ = [{"ok": True, "s": s, "power_W": P} for s, P in zip([0.5, 0.625, 0.75, 0.875, 1.0], [60, 62, 66, 120, 250])]
    r = cal.fit_power_clock(summ)
    assert r["at_bound"] == ["v_min_ratio"] and r["r2"] < 0.95


def test_simulator_refuses_unphysical_clock_sensitivity():
    for bad in ({"beta_memory": -0.06}, {"beta_compute": 1.2}, {"v_min_ratio": 0.0}, {"kappa_leak": -0.01}):
        with pytest.raises(ValueError):
            make_config(bad)


def test_ingest_preserves_rejected_estimates(tmp_path):
    acc, rej = cal.accept_estimates(_desktop_summary_candidates())
    calib = {"device": {"name": "Desktop GPU"}, "overrides": acc, "rejected": rej, "notes": []}
    st = Store(tmp_path / "m.sqlite")
    run = st.runs(cal.ingest(st, calib, "abc"))[0]
    assert run["metrics"]["v_min_ratio_rejected"] == 0.3 and "v_min_ratio" not in run["metrics"]
    assert run["metrics"]["beta_memory"] == 0.0 and run["metrics"]["beta_memory_measured"] == -0.0557
    assert st.verify_chain()[0]
    st.close()
    with pytest.raises(ValueError, match="no accepted"):
        cal.apply_calibration({"key": "E001", "title": "t", "design": {}}, {"overrides": {}}, "abc")



# ------------------------------------------------------------- lessons from the RTX 5070 data
def test_power_cap_flag_on_a_held_lock_far_below_the_limit_is_not_a_limit(tmp_path):
    """RTX 5070, 2026-10-26: power-cap flag in 100% of samples at 1342 MHz locked (measured 1335),
    87 W of a 250 W limit. Reporting that as 'clock held down by a limit' was wrong."""
    rng = np.random.default_rng(15)
    ds = [_write_session(tmp_path, "compute", c, rng, label_clk=lc, power=p, reasons=0x4, power_limit=250.0)
          for c, lc, p in ((1335, 1342, 87.4), (1657, 1680, 105.4), (2002, 2017, 132.0))]
    ds.append(_write_session(tmp_path, "compute", 2340, rng, label_clk=2347, power=168.5, reasons=0x4, power_limit=250.0))
    ds.append(_write_session(tmp_path, "compute", 2670, rng, label_clk=2685, power=247.7, reasons=0, power_limit=250.0))
    out = cal.calibrate(ds)
    assert not any("held down" in n for n in out["notes"])
    assert any("does not indicate a limit" in n and "4 session" in n for n in out["notes"])
    assert "not a limit" in cal.interpret_limits(out["sessions"][0])[0]


def test_unsteady_load_is_left_out_of_the_leakage_fit(tmp_path):
    rng = np.random.default_rng(16)
    d = _write_session(tmp_path, "warmup", 1400, rng, seconds=900, warm=True, dip=(300.0, 450.0, 0.08))
    good = cal.fit_leakage(cal.load_session(d))
    bad = cal.fit_leakage(cal.load_session(d), load_tol=1.0)
    assert good["n_load_excluded"] > 1000 and bad["n_load_excluded"] == 0
    assert good["kappa"] == pytest.approx(TRUE["kappa"], abs=0.003)
    assert abs(bad["kappa"] - TRUE["kappa"]) > abs(good["kappa"] - TRUE["kappa"])
    assert good["dPdT_W_per_K"] > 0


def test_energy_per_work_curve_finds_the_most_efficient_clock(tmp_path):
    """Measured on the RTX 5070: energy per FP16 TFLOP lowest at 1657 MHz, 32% below the top clock."""
    rng = np.random.default_rng(17)
    pts = [(1335, 87.4), (1657, 105.4), (2002, 132.0), (2340, 168.5), (2670, 247.7)]
    ds = [_write_session(tmp_path, "compute", c, rng, power=p, f_top=2670.0) for c, p in pts]
    e = cal.calibrate(ds)["energy_per_work"]["compute"]
    assert e["min_at_clock_MHz"] == 1657.0 and e["saving_vs_top"] == pytest.approx(0.32, abs=0.02)



# ------------------------------------------------------------- second warm-up (RTX 5070, 2347 MHz)
def test_clock_step_during_warmup_is_left_out(tmp_path):
    """Both RTX 5070 warm-ups dropped one clock step (2340 -> 2332 MHz) as they warmed, with power
    falling ~4 W. Keeping both steps made power appear to FALL with temperature (-0.22 W/K)."""
    rng = np.random.default_rng(18)
    d = _write_session(tmp_path, "warmup", 1400, rng, seconds=900, warm=True, clk_step=(60.0, 1392, 4.0))
    good = cal.fit_leakage(cal.load_session(d))
    loose = cal.fit_leakage(cal.load_session(d), clock_tol_MHz=15.0)
    assert good["clock_MHz"] == 1392.0 and good["n_clock_excluded"] > 500
    true_slope = TRUE["kappa"] * TRUE["L"] * np.exp(TRUE["kappa"] * (np.mean([60, 70]) - 60))
    assert abs(good["slope"]["dPdT_W_per_K"] - true_slope) < abs(loose["slope"]["dPdT_W_per_K"] - true_slope)


def test_slope_is_kept_when_the_range_is_too_narrow_for_a_fit(tmp_path):
    rng = np.random.default_rng(19)
    d = _write_session(tmp_path, "warmup", 1400, rng, seconds=120, warm=True)    # first 120 s of the warm-up only
    r = cal.fit_leakage(cal.load_session(d))
    narrow = _write_session(tmp_path, "warmup", 1500, rng, seconds=600, warm=False, folder="flat")
    rn = cal.fit_leakage(cal.load_session(narrow))
    assert not rn["ok"] and rn["slope"] is None                                   # flat 62 C: nothing to fit
    assert r["slope"] is not None and r["slope"]["dPdT_W_per_K"] > 0


def test_ingest_records_leakage_slopes(tmp_path):
    rng = np.random.default_rng(20)
    out = cal.calibrate([_write_session(tmp_path, "warmup", 1400, rng, seconds=900, warm=True)])
    st = Store(tmp_path / "m.sqlite")
    out["overrides"] = out["overrides"] or {}
    run = st.runs(cal.ingest(st, out, "abc", key="M002"))[0]
    assert run["metrics"]["leak_dPdT_W_per_K"] > 0 and "leak_dPdT_rel_per_K" in run["metrics"]
    st.close()


# ------------------------------------------------------------- M003: fan-sweep leakage
def _fan_power(f):
    return 8.0 * (f / 100.0) ** 3


def _write_sweep(root, kind, fan, rng, clk=2017, slope=0.25, seconds=480.0, ramp=False, reasons=0, label=None,
                 report_fan=True):
    d = Path(root) / f"sweep_{kind}_{fan}_{clk}"
    d.mkdir()
    t = np.arange(0, seconds, 0.5)
    if kind == "idle":
        T = np.full_like(t, 35.0 + 0.1 * (100 - fan))
        P = 20.0 + _fan_power(fan) + rng.normal(0, 0.3, t.size)
        clks = np.full(t.size, 210.0)
    else:
        T_ss = 50.0 + 0.4 * (100 - fan)                       # 100% fan -> 50 C, 40% -> 74 C
        T = T_ss - (12.0 * (1 - t / seconds) if ramp else 15.0 * np.exp(-t / 40.0))
        P = 180.0 + slope * (T - 60.0) + _fan_power(fan) + rng.normal(0, 0.8, t.size)
        clks = np.full(t.size, float(clk))
    T = np.round(T)                                           # NVML reports whole degrees
    with open(d / "telemetry.csv", "w") as f:
        f.write(",".join(telemetry.FIELDS) + "\n")
        for ti, Ti, Pi, ci in zip(t, T, P, clks):
            f.write(f"{1000 + ti},0,{Pi},,{Ti},{ci:g},9000,99,50,0,{reasons},{fan if report_fan else ''},{kind},250\n")
    thr = np.zeros(t.size) if kind == "idle" else 100.0 * (1 + rng.normal(0, 0.003, t.size))
    np.savetxt(d / "workload.csv", np.column_stack([1000 + t, thr]), delimiter=",", header="t_unix,throughput", comments="")
    lab = label or (f"sweep fan={fan}" + ("" if kind == "idle" else f" clk={clk}"))
    (d / "session.json").write_text(json.dumps({"kind": kind, "label": lab, "device": {
        "index": 0, "name": "Synthetic", "uuid": None, "max_sm_clock_MHz": 3000, "power_limit_W": 250}}))
    return d


def test_fan_sweep_recovers_the_leakage_slope_and_removes_fan_power(tmp_path):
    rng = np.random.default_rng(3)
    fans = (100, 85, 70, 55, 40)
    ds = [_write_sweep(tmp_path, k, f, rng) for f in fans for k in ("compute", "idle")]
    ds.append(_write_session(tmp_path, "compute", 1500, rng))           # not part of the sweep: no fan= label
    r = cal.fit_leakage_sweep(ds)
    assert r["ok"] and len(r["points"]) == 5 and len(r["idle_points"]) == 5
    assert r["fit_basis"] == "fan-power corrected"
    assert r["fit"]["slope_W_per_K"] == pytest.approx(0.25, abs=0.03)
    assert r["fit"]["ci95"][0] < 0.25 < r["fit"]["ci95"][1]
    # faster fans are cooler AND draw more power, so the raw slope is biased low
    assert r["fit_uncorrected"]["slope_W_per_K"] < r["fit"]["slope_W_per_K"] - 0.1
    assert r["fit"]["T_range_C"][1] - r["fit"]["T_range_C"][0] >= 20


def test_fan_sweep_leaves_out_unsettled_throttled_and_off_clock_points(tmp_path):
    rng = np.random.default_rng(4)
    ds = [_write_sweep(tmp_path, "compute", f, rng) for f in (100, 85, 70)]
    ds.append(_write_sweep(tmp_path, "compute", 55, rng, ramp=True))                 # still warming in the last half
    ds.append(_write_sweep(tmp_path, "compute", 40, rng, reasons=0x20))              # driver temperature target acting
    ds.append(_write_sweep(tmp_path, "compute", 60, rng, clk=1700))                  # wrong clock
    r = cal.fit_leakage_sweep(ds)
    why = {x["name"]: x["reason"] for x in r["excluded"]}
    assert "not settled" in why["sweep_compute_55_2017"]
    assert "thermal limit" in why["sweep_compute_40_2017"]
    assert "1700" in why["sweep_compute_60_1700"]
    assert r["ok"] and len(r["points"]) == 3
    assert r["fit_basis"].startswith("uncorrected") and any("idle sessions" in n for n in r["notes"])


def test_fan_sweep_needs_three_fan_speeds_and_uses_the_label_when_fan_is_not_reported(tmp_path):
    rng = np.random.default_rng(5)
    ds = [_write_sweep(tmp_path, "compute", f, rng, report_fan=False) for f in (100, 70)]
    r = cal.fit_leakage_sweep(ds)
    assert not r["ok"] and "need at least 3" in r["reason"]
    assert all(p["fan_source"] == "label" for p in r["points"])


def test_leakage_sweep_plan_leaves_clocks_and_fans_to_the_user():
    txt = cal.plan_leakage_sweep(2017, [40, 100, 70])
    assert txt.index("fan=100") < txt.index("fan=70") < txt.index("fan=40")            # step down from the top
    assert "-rgc" in txt and "85 C" in txt and "thermal protection stays on" in txt
    assert txt.index("-rgc    # reset clocks") < txt.index("--kind idle")              # idle at default clocks
    assert "calib leak" in txt


def test_idle_session_needs_no_pytorch(tmp_path, monkeypatch):
    monkeypatch.setattr(cal, "torch_workload", lambda *a, **k: (_ for _ in ()).throw(AssertionError("torch used")))
    state = {"P": 25.0, "T": 40, "clk": 210}
    d = cal.run_session("idle", 0.3, tmp_path, label="sweep fan=70", interval_s=0.02, nvml=fake_nvml(state))
    meta = json.loads((d / "session.json").read_text())
    assert meta["kind"] == "idle" and meta["throughput_unit"] == "-"


def test_clock_fit_leaves_fan_sweep_sessions_to_calib_leak(sessions, tmp_path):
    rng = np.random.default_rng(6)
    extra = [_write_sweep(tmp_path, k, 70, rng) for k in ("compute", "idle")]
    a, b = cal.calibrate(sessions), cal.calibrate(sessions + extra)
    assert a["overrides"] == b["overrides"]
    assert any("fan-sweep" in n for n in b["notes"])
