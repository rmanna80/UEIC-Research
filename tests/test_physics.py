"""Analytic validation of the physical models (charter section 8: 'validated analytically')."""
import numpy as np
import pytest
from scipy.optimize import brentq

from ueic import physics as ph
from ueic.params import make_config

cfg = make_config()


def test_thermal_step_matches_analytic_solution():
    """Lumped RC with constant P: T(t) = T_ss + (T0 - T_ss) exp(-t/RC)."""
    P, R, C, T_in, T0 = 600.0, 0.05, 300.0, 30.0, 25.0
    T_ss = T_in + P * R
    for dt in (0.1, 1.0, 7.5):
        T = np.array([T0])
        t = 0.0
        while t < 120.0 - 1e-9:
            T, _ = ph.thermal_step(T, P, T_in, R, C, dt)
            t += dt
            expected = T_ss + (T0 - T_ss) * np.exp(-t / (R * C))
            assert T[0] == pytest.approx(expected, abs=1e-9)


def test_thermal_step_conserves_energy_exactly():
    rng = np.random.default_rng(0)
    T = rng.uniform(20, 90, 50)
    P = rng.uniform(0, 800, 50)
    T_new, Q = ph.thermal_step(T, P, 25.0, 0.05, 300.0, 1.0)
    assert np.allclose(P * 1.0, 300.0 * (T_new - T) + Q, rtol=0, atol=1e-9)


def test_steady_temperature_matches_root_finder():
    rng = np.random.default_rng(1)
    for _ in range(200):
        T_in = rng.uniform(10, 45)
        R = rng.uniform(0.03, 0.08)
        A = rng.uniform(100, 600)
        L = rng.uniform(20, 150)
        T, ok = ph.steady_temperature(T_in, R, A, L, cfg)
        exists = ph.leakage_steady_state_exists(T_in, R, A, L, cfg)
        assert bool(ok) == bool(exists)
        if ok:
            g = lambda x: x - T_in - R * (A + L * np.exp(cfg.kappa_leak * (x - cfg.t_leak_ref)))
            # stable root is the smaller one: bracket it between T_in + R*A and the maximum of g
            T_star = cfg.t_leak_ref + np.log(1.0 / (R * L * cfg.kappa_leak)) / cfg.kappa_leak
            root = brentq(g, T_in + R * A - 1e-9, T_star)
            assert float(T) == pytest.approx(root, abs=1e-6)


def test_thermal_runaway_boundary_is_detected():
    """Sweep R across the analytic existence boundary; solver must flip exactly there."""
    T_in, A, L = 40.0, 400.0, 200.0
    Rs = np.linspace(0.01, 0.3, 400)
    T, ok = ph.steady_temperature(T_in, Rs, A, L, cfg)
    exists = ph.leakage_steady_state_exists(T_in, Rs, A, L, cfg)
    assert np.array_equal(ok, exists)
    assert ok[0] and not ok[-1]   # both regimes present in the sweep


def test_coolant_energy_balance_hand_calculation():
    """Q = m_dot cp dT. 8 x 1.2 L/min water: m_dot = 0.15952 kg/s; Q = 5 kW -> dT = 7.4985 K."""
    out = ph.plant(5000.0, 25.0, 1.0, 10.0, cfg)
    m_dot = 8 * 1.2 / 60e3 * 997.0
    assert m_dot == pytest.approx(0.159520, rel=1e-6)
    assert float(out["T_ret"]) - 25.0 == pytest.approx(5000.0 / (m_dot * 4180.0), rel=1e-12)
    assert float(out["Q_dc"] + out["Q_ch"]) == pytest.approx(5000.0, rel=1e-12)


def test_pump_power_hand_calculation_and_scaling():
    # 150 kPa x 1.6e-4 m^3/s / 0.5 = 48 W
    assert float(ph.pump_power(1.0, cfg)) == pytest.approx(48.0, rel=1e-12)
    ratio = float(ph.pump_power(2.0, cfg) / ph.pump_power(1.0, cfg))
    assert ratio == pytest.approx(2.0 ** (cfg.m_dp + 1.0), rel=1e-12)


def test_chiller_cop_never_exceeds_carnot():
    rng = np.random.default_rng(2)
    T_sup = rng.uniform(12, 45, 1000)
    T_amb = rng.uniform(-5, 45, 1000)
    cop = ph.chiller_cop(T_sup, T_amb, cfg)
    carnot = ph.carnot_cop(T_sup, T_amb, cfg)
    assert np.all(cop <= carnot + 1e-12)
    assert np.all(cop <= cfg.cop_max)
    uncapped = (carnot * cfg.eta_ii_chiller < cfg.cop_max)
    assert np.allclose(cop[uncapped], cfg.eta_ii_chiller * carnot[uncapped])


def test_free_cooling_regimes():
    # ambient cold enough: no chiller work
    out = ph.plant(5000.0, 30.0, 1.0, 10.0, cfg)
    assert float(out["Q_ch"]) == 0.0 and float(out["W_ch"]) == 0.0
    # ambient too hot for the dry cooler to help at all: chiller does everything
    out = ph.plant(5000.0, 18.0, 1.0, 40.0, cfg)
    assert float(out["Q_dc"]) == 0.0
    assert float(out["Q_ch"]) == pytest.approx(5000.0)


def test_exergy_bounds():
    Cdot = 666.8  # W/K
    T0 = 20.0
    # stream at dead state has no exergy
    assert float(ph.stream_exergy_rate(Cdot, T0, T0, T0)) == 0.0
    for T1, T2 in [(45, 35), (60, 40), (30, 25)]:
        Q = Cdot * (T1 - T2)
        ex = float(ph.stream_exergy_rate(Cdot, T1, T2, T0))
        carnot_hot = 1 - (T0 + 273.15) / (T1 + 273.15)
        assert 0 < ex < Q * carnot_hot  # exergy below Carnot factor at the hottest temperature


def test_landauer_bound_value():
    # k_B T ln2 at 300 K = 2.8710e-21 J
    assert float(ph.landauer_energy(300.0, cfg)) == pytest.approx(2.87098e-21, rel=1e-4)


def test_dynamic_power_scales_as_s_v_squared():
    s = np.array([cfg.s_min, 0.75, 1.0])
    T = cfg.t_leak_ref
    dyn = ph.chip_power(s, T, 1.0, cfg) - ph.leakage_power(T, ph.voltage_ratio(s, cfg), cfg) - cfg.p_static_other
    v = ph.voltage_ratio(s, cfg)
    assert np.allclose(dyn, cfg.p_dyn_max * s * v ** 2)
    assert float(v[0]) == pytest.approx(cfg.v_min_ratio) and float(v[-1]) == pytest.approx(1.0)


def test_power_monotonic_in_clock_and_temperature():
    s = np.linspace(cfg.s_min, 1, 20)
    assert np.all(np.diff(ph.chip_power(s, 60.0, 1.0, cfg)) > 0)
    T = np.linspace(20, 90, 20)
    assert np.all(np.diff(ph.chip_power(1.0, T, 1.0, cfg)) > 0)


def test_plant_never_does_negative_work_when_heat_flows_into_chips():
    """Regression (E001 v1 bug): net heat from coolant into chips must not create negative
    chiller work; it is booked as loop storage and the balance still closes."""
    out = ph.plant(-300.0, 30.0, 1.0, 8.0, cfg)
    assert float(out["W_ch"]) == 0.0 and float(out["Q_ch"]) == 0.0 and float(out["Q_dc"]) == 0.0
    assert float(out["Q_loop_storage"]) == -300.0
    assert float(out["T_ret"]) < 30.0


def test_exergy_never_negative_below_ambient():
    """Regression (E001 v2 dashboard check): sub-ambient streams have no reusable work potential."""
    assert float(ph.stream_exergy_rate(666.8, 25.0, 18.0, 35.0)) == 0.0
    # straddling ambient: only the part above T0 counts
    part = float(ph.stream_exergy_rate(666.8, 45.0, 30.0, 35.0))
    above = float(ph.stream_exergy_rate(666.8, 45.0, 35.0, 35.0))
    assert part == pytest.approx(above) and part > 0
