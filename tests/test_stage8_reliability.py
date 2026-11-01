"""Stage 8: sensor validation, residual CUSUM, degradation, recovery, fault injection and supervisors."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from ueic.params import make_config
from ueic.reliability.anomaly_detection import ResidualCUSUM
from ueic.reliability.fault_injection import make_stack
from ueic.reliability.recovery import RecoveryManager
from ueic.reliability.sensor_validation import SensorValidator
from ueic.sim import simulate
from ueic.workload import SCENARIOS

OVER = {"beta_compute": 0.983, "beta_memory": 0.0, "kappa_leak": 0.02, "p_leak_ref": 28.962, "warm_start": 1.0,
        "r_cond": 0.04, "r_conv_ref": 0.0225, "loop_mass_kg": 40.0, "tsup_ramp_K_per_min": 1.0}


def _obs(t, T, sup=30.0, q=2000.0):
    return SimpleNamespace(t=t, T_j=np.asarray(T, dtype=float), T_sup_actual=sup, q_chips=q)


def test_sensor_validator_rules():
    v = SensorValidator()
    assert v.check(_obs(0, [50, 51]))["valid_T"]
    assert "dropout" in v.check(_obs(60, [np.nan, 51]))["problems"]
    v = SensorValidator()
    v.check(_obs(0, [50, 51])); assert "rate" in v.check(_obs(1, [70, 51]))["problems"]
    v = SensorValidator()
    v.check(_obs(0, [50, 51], q=2000)); v.check(_obs(60, [50, 51], q=2500))
    assert "stale" in v.check(_obs(120, [50, 51], q=3000))["problems"]
    v = SensorValidator()
    v.check(_obs(0, [50, 51], q=2000)); v.check(_obs(60, [50, 51], q=2000))
    assert v.check(_obs(120, [50, 51], q=2000))["valid_T"]          # unchanged load: identical readings are plausible
    assert not SensorValidator().check(_obs(0, [50, 51], sup=float("nan")))["valid_sup"]


def test_cusum_false_alarm_rate_and_detection():
    fa = 0
    for seed in range(100):                                   # 180 in-control samples after learning
        rng = np.random.default_rng(seed)
        c = ResidualCUSUM()
        for i, x in enumerate(rng.normal(2.0, 0.5, 200)):
            c.update(float(x), i)
        fa += c.alarm is not None
    assert fa <= 15                                            # measured: 14 of 200 sequences (docs/21)
    rng = np.random.default_rng(1)
    c = ResidualCUSUM()
    for i, x in enumerate(rng.normal(2.0, 0.5, 20)):
        c.update(float(x), i)
    for i in range(20, 30):
        c.update(2.0 - 3.0 + float(rng.normal(0, 0.5)), i)
    assert c.alarm == "residual_low" and c.alarm_t <= 23       # a 6-sigma low bias is caught within 4 samples


def test_recovery_hysteresis():
    r = RecoveryManager(clear_intervals=3)
    seq = ["NORMAL", "SAFE", "NORMAL", "NORMAL", "NORMAL", "NORMAL"]
    modes = [r.step(i * 60.0, w) for i, w in enumerate(seq)]
    assert modes == ["NORMAL", "SAFE", "SAFE", "SAFE", "NORMAL", "NORMAL"]
    assert r.first_alarm_t == 60.0 and r.recovered_t == 240.0


def _run(inner, aware, kind, mag=0.0, seed=0):
    sc = replace(SCENARIOS["S6_degraded_cooling"], t_amb=38.0, load_mean=0.6, load_amp=0.0, duration_s=5400.0)
    cfg = make_config({**sc.param_overrides, **OVER})
    pol = make_stack(cfg, inner, aware, kind=kind, t_start=1800.0, t_end=3600.0, magnitude=mag)
    m = simulate(cfg, sc, pol, seed).metrics
    return {k: v[0] for k, v in m.items()}


def test_fault_free_supervisor_is_transparent():
    a, b = _run("joint_meas", False, 0), _run("joint_meas", True, 0)
    assert b["diag_first_alarm_t"] == -1.0 and b["diag_safe_intervals"] == 0
    assert b["E_per_success_kJ"] == pytest.approx(a["E_per_success_kJ"], rel=1e-9)


def test_clock_stuck_is_detected_and_contained():
    nom, aw = _run("joint_meas", False, 4), _run("joint_meas", True, 4)
    assert 1800.0 <= aw["diag_first_alarm_t"] <= 1800.0 + 3 * 60
    assert aw["chip_s_over_target"] <= nom["chip_s_over_target"] and aw["diag_recovered_t"] >= 3600.0


def test_dropout_and_crash_handled_without_run_failure():
    for kind in (1, 6, 7, 5, 3):
        m = _run("joint_meas", True, kind)
        assert m["diag_first_alarm_t"] >= 1800.0 and np.isfinite(m["E_per_success_kJ"])
    assert _run("joint_meas", False, 6)["diag_exceptions"] > 0
