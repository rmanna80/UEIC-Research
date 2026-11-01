"""Stage 1 (next generation): physics package components, opt-in NTU plant, parameter uncertainty,
identifiability and validation utilities. The legacy behaviour is guarded separately by the bitwise
E001 reproduction test in test_phase3.py."""
import warnings
from pathlib import Path

import numpy as np
import pytest

from ueic import physics as ph
from ueic.params import make_config
from ueic.physics import chiller, coolant, dry_cooler, heat_pump, heat_reuse, hydraulics, power_delivery, thermal_storage
from ueic.models import identifiability as ident
from ueic.models import model_validation as mv
from ueic.models import parameter_registry as preg
from ueic.models import uncertainty as unc

ROOT = Path(__file__).resolve().parents[1]
NTU = make_config({"plant_model": 1})
LEG = make_config()


# ------------------------------------------------------------------ package conversion
def test_physics_package_keeps_every_legacy_name():
    for name in ("voltage_ratio", "leakage_power", "chip_power", "idle_power", "r_total", "thermal_step",
                 "steady_temperature", "pump_power", "chiller_cop", "carnot_cop", "plant", "plant_split",
                 "tank_step", "stream_exergy_rate", "landauer_energy", "KELVIN"):
        assert hasattr(ph, name), name


def test_default_plant_is_the_legacy_plant():
    assert LEG.plant_model == 0
    r = ph.plant(4000.0, 30.0, 1.0, 20.0, LEG)
    assert "fan_speed" not in r and r["P_fan"] == pytest.approx(LEG.fan_ratio * r["Q_amb"] / (1 + LEG.fan_ratio))


# ------------------------------------------------------------------ dry cooler
def test_crossflow_effectiveness_limits_and_monotonicity():
    ntu = np.linspace(0, 10, 200)
    for cr in (0.0, 0.3, 0.7, 1.0):
        e = dry_cooler.crossflow_effectiveness(ntu, cr)
        assert np.all(np.diff(e) >= -1e-12) and e[0] == 0 and np.all(e <= 1)
    assert dry_cooler.crossflow_effectiveness(2.0, 0.0) == pytest.approx(1 - np.exp(-2.0))


def test_ntu_dry_cooler_matches_legacy_at_its_design_point():
    d = dry_cooler.DryCoolerDesign.from_config(NTU)
    r = ph.plant(d.Q_d, 20.0 + NTU.dt_drycooler, 1.0, 20.0, NTU)
    r0 = ph.plant(d.Q_d, 20.0 + LEG.dt_drycooler, 1.0, 20.0, LEG)
    assert float(r["fan_speed"]) == pytest.approx(1.0, abs=1e-6)
    assert float(r["P_fan"]) == pytest.approx(float(r0["P_fan"]), rel=1e-6)
    assert float(r["W_ch"]) == pytest.approx(0.0, abs=1e-6)


def test_fan_power_falls_with_approach_and_part_load():
    d = dry_cooler.DryCoolerDesign.from_config(NTU)
    fans = [float(ph.plant(d.Q_d, T, 1.0, 20.0, NTU)["P_fan"]) for T in (25, 28, 31, 34, 37, 40)]
    assert all(a > b for a, b in zip(fans, fans[1:]))
    half = float(ph.plant(0.5 * d.Q_d, 25.0, 1.0, 20.0, NTU)["P_fan"])
    assert half < fans[0]


def test_ntu_plant_conserves_energy_and_never_runs_backwards():
    rng = np.random.default_rng(0)
    for _ in range(200):
        Q = rng.uniform(0, 8000); T = rng.uniform(12, 45); f = rng.uniform(0.5, 2.0); Ta = rng.uniform(-5, 45)
        r = ph.plant(Q, T, f, Ta, NTU)
        assert float(r["Q_dc"]) >= -1e-9 and float(r["Q_ch"]) >= -1e-9 and float(r["W_ch"]) >= -1e-9
        assert float(r["Q_dc"] + r["Q_ch"]) == pytest.approx(Q, rel=1e-9, abs=1e-6)
        assert float(r["Q_amb"]) == pytest.approx(Q + float(r["W_ch"] + r["P_fan"]), rel=1e-9, abs=1e-6)
        s = ph.plant_split(Q, T, f, Ta, NTU)
        assert float(s["Q_dc"] + s["Q_ch"]) == pytest.approx(Q, rel=1e-9, abs=1e-6)


def test_dry_cooler_is_off_when_air_is_warmer_than_water():
    r = ph.plant(3000.0, 30.0, 1.0, 45.0, NTU)
    assert float(r["Q_dc"]) == 0.0 and float(r["fan_speed"]) == 0.0 and float(r["Q_ch"]) == pytest.approx(3000.0)


def test_unreachable_design_is_rejected():
    with pytest.raises(ValueError):
        dry_cooler.DryCoolerDesign.from_config(make_config({"plant_model": 1, "dc_air_ratio": 0.2, "dt_drycooler": 3.0}))
    with pytest.raises(ValueError):
        make_config({"plant_model": 2})


# ------------------------------------------------------------------ chiller, pump, power
def test_chiller_part_load_default_is_legacy_and_never_beats_carnot():
    T, Ta = np.linspace(12, 30, 10), 35.0
    full = chiller.chiller_cop_part_load(T, Ta, 2000.0, 5000.0, NTU)
    assert np.allclose(full, np.minimum(ph.chiller_cop(T, Ta, NTU), ph.carnot_cop(T, Ta, NTU)))
    cfg = make_config({"plant_model": 1, "chiller_plr_a": 0.2, "chiller_plr_b": 0.6, "chiller_plr_c": 0.2})
    low = chiller.chiller_cop_part_load(T, Ta, 500.0, 5000.0, cfg)
    assert np.all(low < full) and np.all(low > 0) and np.all(low <= ph.carnot_cop(T, Ta, cfg))


def test_pump_curve_reduces_to_constant_efficiency_and_peaks_at_bep():
    f = np.linspace(0.5, 2.0, 7)
    assert np.allclose(hydraulics.pump_power_curve(f, LEG, k=0.0), ph.pump_power(f, LEG))
    eta = hydraulics.pump_efficiency(np.linspace(0.2, 1.8, 81), 0.6)
    assert np.argmax(eta) == 40 and eta.max() == pytest.approx(0.6)
    with pytest.raises(ValueError):
        hydraulics.system_pressure_drop(-1.0, LEG)


def test_power_delivery_loss_model():
    c = power_delivery.coefficients_for_constant(0.94)
    assert power_delivery.efficiency(np.array([100.0, 5000.0]), 6000.0, **c) == pytest.approx(0.94)
    eta = power_delivery.efficiency(np.linspace(1, 6000, 500), 6000.0, P0=50.0, k1=0.02, k2=0.03)
    assert np.all(eta < 1) and 0 < np.argmax(eta) < 499


# ------------------------------------------------------------------ transport and storage
def test_delay_line_delays_by_volume_and_conserves_energy():
    dl = coolant.DelayLine(0.01, 30.0)
    V_dot, dt = 0.001, 1.0                                   # 10 s delay
    E0 = dl.stored_energy()
    outs, e_in, e_out = [], 0.0, 0.0
    for k in range(40):
        T_in = 30.0 if k < 5 else 40.0
        o = dl.step(T_in, V_dot, dt)
        outs.append(o)
        e_in += 997 * 4180 * V_dot * dt * T_in
        e_out += 997 * 4180 * V_dot * dt * o
    assert outs[14] == pytest.approx(30.0) and outs[15] == pytest.approx(40.0)
    assert e_in - e_out == pytest.approx(dl.stored_energy() - E0, rel=1e-9)


def test_stratified_tank_conserves_energy_and_one_layer_is_the_mixed_tank():
    for n in (1, 5, 20):
        tk = thermal_storage.StratifiedTank(100.0, n, 30.0)
        E0, e_flow = tk.energy(), 0.0
        for k in range(300):
            T_in = 45.0 if k < 150 else 25.0
            out = tk.step(T_in, 600.0, 2.0)
            e_flow += 600.0 * 2.0 * (T_in - out)
        assert tk.energy() - E0 == pytest.approx(e_flow, rel=1e-9, abs=1e-3)
    tk = thermal_storage.StratifiedTank(100.0, 1, 30.0)
    tk.step(45.0, 600.0, 7.0)
    assert tk.outlet == pytest.approx(float(ph.tank_step(30.0, 45.0, 600.0, 100.0 * 4180.0, 7.0)))


# ------------------------------------------------------------------ heat pump and reuse
def test_heat_pump_obeys_first_and_second_law():
    r = heat_pump.upgrade(1000.0, 40.0, 70.0)
    assert r["Q_delivered"] == pytest.approx(1000.0 + r["W"])
    T_e, T_c = 40 - 3 + 273.15, 70 + 3 + 273.15
    assert float(r["cop"]) <= T_c / (T_c - T_e) + 1e-9
    assert float(heat_pump.upgrade(500.0, 80.0, 70.0)["W"]) == 0.0


def test_heat_reuse_never_delivers_more_than_demand_or_available():
    out = heat_reuse.reuse(np.array([2000.0, 2000.0, 500.0]), np.array([60.0, 35.0, 35.0]),
                           np.array([1000.0, 1000.0, 1000.0]), 55.0)
    assert np.all(out["Q_used"] <= 1000.0 + 1e-9) and np.all(out["Q_src"] <= np.array([2000.0, 2000.0, 500.0]) + 1e-9)
    assert out["direct"][0] and not out["direct"][1] and out["W_hp"][0] == 0.0 and out["W_hp"][1] > 0


# ------------------------------------------------------------------ parameters with uncertainty
def test_registry_wrapper_keeps_values_and_labels_ranges_as_stress_tests():
    ps = preg.from_registry()
    assert ps["kappa_leak"].value == LEG.kappa_leak and ps["kappa_leak"].kind == "range"
    assert ps["water_cp"].kind == "point" and "not a probability" in ps["kappa_leak"].note


def test_calibration_overlay_carries_hardware_date_domain_and_warns_on_extrapolation():
    ps = preg.with_calibration(preg.from_registry(), ROOT / "data" / "calibration" / "M001_calibration.json")
    p = ps["beta_compute"]
    assert p.kind == "normal" and p.value == pytest.approx(0.983) and "RTX 5070" in p.hardware and p.calibration_date
    assert ps.check_domain({"s": 0.8}, ["beta_compute"], warn=False) == []
    with pytest.warns(preg.ExtrapolationWarning):
        ps.check_domain({"s": 0.3}, ["beta_compute"])


def test_correlated_sampling_respects_correlation_and_ranges():
    ps = preg.ParameterSet([preg.UncertainParameter("a", 1.0, "-", "B", "x", kind="normal", sd=0.1),
                            preg.UncertainParameter("b", 2.0, "-", "B", "x", kind="normal", sd=0.2),
                            preg.UncertainParameter("c", 5.0, "-", "F", "x", kind="range", low=4.0, high=6.0)])
    ps.set_correlation("a", "b", 0.8)
    d = ps.sample(4000, np.random.default_rng(1))
    a, b, c = (np.array([x[k] for x in d]) for k in "abc")
    assert np.corrcoef(a, b)[0, 1] == pytest.approx(0.8, abs=0.03)
    assert c.min() >= 4.0 and c.max() <= 6.0
    with pytest.raises(ValueError):
        preg.UncertainParameter("bad", 1.0, "-", "B", "x", kind="normal")


def test_monte_carlo_reports_rejected_draws_and_interpretation():
    ps = preg.ParameterSet([preg.UncertainParameter("x", 0.0, "-", "F", "x", kind="range", low=-1.0, high=1.0)])
    def g(d):
        if d["x"] < 0:
            raise ValueError("non-physical")
        return d["x"]
    r = unc.monte_carlo(g, ps, 1000, seed=2)
    assert 400 < r["n_rejected"] < 600 and "stress-test" in r["interpretation"]


# ------------------------------------------------------------------ identifiability and validation
def test_identifiability_flags_collinear_parameters_and_matches_ols_errors():
    x = np.linspace(0, 1, 50)
    J = np.column_stack([np.ones_like(x), x, 2 * x])       # third column is a copy of the second
    r = ident.identifiability(J, ["a", "b", "c"], [1.0, 1.0, 1.0], 0.1)
    assert r["rank"] == 2 and r["null_directions"]
    assert not next(p for p in r["parameters"] if p["name"] == "c")["identifiable"]
    J2 = J[:, :2]
    r2 = ident.identifiability(J2, ["a", "b"], [1.0, 1.0], 0.1)
    ols = np.sqrt(np.diag(np.linalg.inv(J2.T @ J2)) * 0.01)
    assert [p["crlb_se"] for p in r2["parameters"]] == pytest.approx(ols.tolist())


def test_narrow_warmup_window_cannot_identify_leakage_with_realistic_sample_count():
    """M001/M002: 1 C resolution and autocorrelated 10 Hz samples leave ~10 independent levels."""
    narrow = ident.leakage_warmup_identifiability((48, 57), 128.0, 0.02, 0.2, 0.84, n=10)
    wide = ident.leakage_warmup_identifiability((45, 80), 128.0, 0.02, 0.2, 0.84, n=36)
    k_n = next(p for p in narrow["parameters"] if p["name"] == "kappa")
    k_w = next(p for p in wide["parameters"] if p["name"] == "kappa")
    assert not k_n["identifiable"] and k_w["rel_se"] < k_n["rel_se"] / 5


def test_holdout_metrics_and_cross_validation():
    m = mv.holdout_metrics([1, 2, 3], [1.5, 2, 2.5], lo=[0, 0, 0], hi=[2, 2, 2])
    assert m["rmse"] == pytest.approx(np.sqrt(0.5 / 3)) and m["coverage"] == pytest.approx(2 / 3)
    X = np.linspace(0, 1, 40); y = 3 * X + 1
    cv = mv.cross_validate(lambda X, y: np.polyfit(X, y, 1), lambda m, X: np.polyval(m, X), X, y, k=4)
    assert cv["rmse"] < 1e-9
    assert mv.information_criteria(1.0, 10, 2)["aic"] < mv.information_criteria(1.0, 10, 3)["aic"]


def test_simulator_runs_with_the_ntu_plant_and_closes_the_energy_balance():
    from dataclasses import replace
    from ueic.policies import POLICIES
    from ueic.sim import simulate
    from ueic.workload import SCENARIOS
    sc = replace(SCENARIOS["S1_moderate"], duration_s=1800.0, load_period_s=1800.0)
    out = {}
    for pm in (0, 1):
        for dyn in (0.0, 40.0):
            cfg = make_config({"plant_model": pm, "loop_mass_kg": dyn, "tsup_ramp_K_per_min": 1.0 if dyn else 0.0,
                               "warm_start": 1.0})
            r = simulate(cfg, sc, POLICIES["joint"](cfg), seed=3, record_timeseries=False)
            assert r.m("energy_balance_rel_residual") < 1e-9
            out[(pm, dyn)] = r
    # the joint controller sees the cheaper warm-water fans and runs warmer water with the NTU plant
    assert out[(1, 0.0)].m("E_fan_kWh") < out[(0, 0.0)].m("E_fan_kWh")
