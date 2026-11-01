"""Stage 2 (next generation): system identification, drift detection, experiment planning, adaptive twins."""
from dataclasses import replace

import numpy as np
import pytest

from ueic.models import active_experiment_design as aed
from ueic.models import model_drift, parameter_estimator, system_identification as si
from ueic.params import make_config
from ueic.policies import POLICIES, Observation


def _rc_record(R=0.08, C=400.0, T_in=30.0, h=1.0, n=900, noise=0.05, seed=0, steps=((0, 100.0), (300, 400.0), (600, 200.0))):
    rng = np.random.default_rng(seed)
    t = np.arange(n) * h
    P = np.zeros(n)
    for k0, p in steps:
        P[int(k0 / h):] = p
    T = np.empty(n); T[0] = T_in + R * P[0]
    a = np.exp(-h / (R * C))
    for k in range(n - 1):
        T[k + 1] = a * T[k] + (1 - a) * (T_in + R * P[k])
    return t, T + rng.normal(0, noise, n), P


def test_first_order_fit_recovers_r_tau_and_inlet_with_uncertainty():
    t, T, P = _rc_record()
    fit = si.fit_first_order_thermal(t, T, P)
    assert fit.R_K_per_W == pytest.approx(0.08, rel=0.03) and fit.tau_s == pytest.approx(32.0, rel=0.1)
    assert fit.T_in_C == pytest.approx(30.0, abs=0.5) and fit.se["R"] > 0
    assert abs(fit.R_K_per_W - 0.08) < 4 * fit.se["R"]


def test_first_order_fit_warns_when_power_is_constant_or_temperature_quantised():
    t, T, P = _rc_record(steps=((0, 300.0),))
    fit = si.fit_first_order_thermal(t, np.round(T), P)
    assert any("not separately identifiable" in w for w in fit.warnings)
    assert any("quantised" in w for w in fit.warnings)


def test_estimator_front_end_reports_identifiability():
    t, T, P = _rc_record()
    out = parameter_estimator.estimate_thermal_rc(t, T, P)
    assert out["identifiability"]["rank"] == 3 and out["R_K_per_W"] == pytest.approx(0.08, rel=0.05)


def test_step_response_fit_recovers_a_fast_time_constant():
    t = np.arange(0, 20, 0.1)
    T = 37 + 18 * (1 - np.exp(-t / 1.5)) + 0.1 * t
    r = si.fit_step_response(t, T, 140.0, quantum_K=None)
    assert r["tau_s"] == pytest.approx(1.5, rel=0.02) and r["R_fast_K_per_W"] == pytest.approx(18 / 140, rel=0.02)
    rq = si.fit_step_response(t, np.round(T), 140.0)
    assert rq["tau_s"] == pytest.approx(1.5, rel=0.2) and rq["warnings"]


def test_rls_with_forgetting_tracks_drift_and_reports_uncertainty():
    rng = np.random.default_rng(1)
    rls = si.RecursiveLeastSquares(1, lam=0.9, theta0=[0.0], p0=10.0)
    for k in range(300):
        theta = 1.0 if k < 150 else 2.0
        x = rng.uniform(0.5, 1.5)
        rls.update([x], theta * x + rng.normal(0, 0.05))
    assert rls.theta[0] == pytest.approx(2.0, abs=0.05) and rls.se()[0] > 0
    with pytest.raises(ValueError):
        si.RecursiveLeastSquares(1, lam=1.5)


def test_resistance_estimator_finds_excess_resistance():
    est = si.ResistanceEstimator(8, lam=0.9)
    rng = np.random.default_rng(2)
    for k in range(80):
        q = rng.uniform(2000, 5000)
        dT = (0.05 + 0.02) * q / 8 + rng.normal(0, 0.2)
        obs = Observation(t=60.0 * k, D_est=np.zeros(2), backlog=np.zeros(2), T_amb=30.0, p_chip_peak=600.0, q_chips=q,
                          T_j=np.full(8, 35.0 + dT), T_sup_actual=35.0)
        est.update(obs, R_model=0.05)
    assert est.history[-1][1] == pytest.approx(0.02, abs=0.002)


def test_page_hinkley_detects_a_shift_and_stays_quiet_on_noise():
    rng = np.random.default_rng(3)
    quiet = model_drift.PageHinkley(delta=0.5, lam=10.0)
    for k in range(500):
        quiet.update(rng.normal(0, 1.0), t=k)
    assert quiet.alarm_at is None
    det = model_drift.PageHinkley(delta=0.5, lam=10.0)
    for k in range(200):
        det.update(rng.normal(0, 1.0) + (3.0 if k >= 100 else 0.0), t=k)
    assert det.alarm_at is not None and 100 <= det.alarm_at <= 115


def test_planner_excludes_unsafe_designs_and_prefers_wider_windows():
    r = aed.leakage_window_designs()
    names = [x["name"] for x in r["ranking"]]
    unsafe = [x for x in r["ranking"] if not x["safe"]]
    assert unsafe and all(x["score"] == -np.inf for x in unsafe)
    se = {x["name"]: x.get("kappa_rel_se") for x in r["ranking"] if x["safe"]}
    assert se["M003 plan, 5 fan speeds (~50-70 C)"] < se["M001-like warm-up (48-57 C, auto fan)"] < se["narrow high (60-66 C)"]


def test_fixed_tracked_policy_decides_exactly_like_joint_fb_and_reports_diagnostics():
    from ueic.sim import simulate
    from ueic.workload import SCENARIOS
    sc = replace(SCENARIOS["S6_degraded_cooling"], duration_s=1800.0, load_period_s=1800.0)
    cfg = make_config({**sc.param_overrides, "warm_start": 1.0})
    a = simulate(cfg, sc, POLICIES["joint_fb"](cfg), seed=1, record_timeseries=False)
    b = simulate(cfg, sc, POLICIES["joint_fixed"](cfg), seed=1, record_timeseries=False)
    assert a.m("E_per_success_kJ") == b.m("E_per_success_kJ") and "diag_pred_peak_mae_K" in b.metrics


def test_adaptive_policy_raises_its_resistance_after_plant_fouling():
    from ueic.sim import simulate
    from ueic.workload import SCENARIOS
    sc = replace(SCENARIOS["S6_degraded_cooling"], duration_s=3600.0, load_period_s=3600.0, t_amb=25.0)
    cfg = make_config({**sc.param_overrides, "warm_start": 1.0, "r_fouling_step": 0.02, "r_fouling_start_s": 900.0})
    r = simulate(cfg, sc, POLICIES["joint_adaptive"](cfg), seed=1, record_timeseries=False)
    assert r.m("diag_model_dR_final") == pytest.approx(0.02, abs=0.008) and r.m("energy_balance_rel_residual") < 1e-9
