"""System-level validation of the time-stepped simulator."""
from dataclasses import replace

import numpy as np
import pytest

from ueic import physics as ph
from ueic import twin
from ueic.params import make_config
from ueic.policies import POLICIES, Action, Policy
from ueic.sim import simulate
from ueic.workload import SCENARIOS, Workload, generate

SHORT = replace(SCENARIOS["S1_moderate"], duration_s=1800.0, load_period_s=1800.0)
MEASURED = {"controller_wall_mean_ms", "sim_wall_s"}


@pytest.mark.parametrize("name", list(POLICIES))
def test_energy_balance_closes_for_every_policy(name):
    cfg = make_config()
    r = simulate(cfg, SHORT, POLICIES[name](cfg), seed=3, record_timeseries=False)
    assert r.m("energy_balance_rel_residual") < 1e-9
    # grid = IT + conversion + pump + fan + chiller
    parts = sum(r.m(k) for k in ("E_it_kWh", "E_conv_loss_kWh", "E_pump_kWh", "E_fan_kWh", "E_chiller_kWh"))
    assert r.m("E_grid_kWh") == pytest.approx(parts, rel=1e-12)


def test_same_seed_is_bitwise_reproducible_and_seeds_differ():
    cfg = make_config()
    a = simulate(cfg, SHORT, POLICIES["joint"](cfg), seed=5, record_timeseries=False)
    b = simulate(cfg, SHORT, POLICIES["joint"](cfg), seed=5, record_timeseries=False)
    c = simulate(cfg, SHORT, POLICIES["joint"](cfg), seed=6, record_timeseries=False)
    for k in a.metrics:
        if k in MEASURED:
            continue
        va, vb = a.m(k), b.m(k)
        assert (np.isnan(va) and np.isnan(vb)) or va == vb, k
    assert a.m("E_grid_kWh") != c.m("E_grid_kWh")


def test_work_is_conserved_and_every_task_finishes():
    cfg = make_config()
    wl = generate(cfg, SHORT, 7)
    r = simulate(cfg, SHORT, POLICIES["independent"](cfg), seed=7, workload=wl, record_timeseries=False)
    assert r.m("tasks_completed") == wl.n
    assert r.m("work_done_s") == pytest.approx(wl.work.sum(), rel=1e-9)
    assert r.m("work_enqueued_s") == pytest.approx(wl.work.sum(), rel=1e-12)


def test_policies_see_identical_workloads():
    cfg = make_config()
    counts = {simulate(cfg, SHORT, P(cfg), seed=9, record_timeseries=False).m("tasks") for P in POLICIES.values()}
    assert len(counts) == 1


def _saturating_workload(cfg, hours=1.0, cls=0):
    """Enough compute-bound work at t=0 to keep every chip busy for `hours`."""
    n = cfg.n_accel * int(hours * 3600 / 100) + cfg.n_accel
    z = np.zeros(n)
    return Workload(arrival=z, work=np.full(n, 100.0), cls=np.full(n, cls, dtype=np.int8),
                    easy=np.zeros(n, bool), u_small=z, u_verify=z, u_large=z, slo=np.full(n, 1e9))


def test_simulated_steady_state_matches_twin_prediction():
    """All chips continuously busy at fixed settings: after ~10 time constants the
    time-stepped junction temperature and power must equal the twin's analytic
    steady state (including leakage feedback)."""
    cfg = make_config({"drain_max_s": 1800.0})
    sc = replace(SCENARIOS["S1_moderate"], duration_s=1.0, t_amb=20.0)
    wl = _saturating_workload(cfg, hours=0.5)
    pol = POLICIES["fixed"](cfg)
    r = simulate(cfg, sc, pol, seed=0, workload=wl, record_timeseries=True, initial_T=30.0)
    ts = r.timeseries
    i = 10  # t = 600 s, well past the ~17 s thermal time constant, chips still saturated
    D = np.array([cfg.n_accel * 1.0, 0.0])  # u = 1 at s = 1
    pred = twin.evaluate(cfg, D, 1.0, 1.0, cfg.fixed_t_sup, cfg.fixed_flow, 20.0)
    assert ts["busy"][i] == cfg.n_accel
    assert ts["T_mean"][i] == pytest.approx(float(pred["T_c"]), abs=0.01)
    assert ts["P_it"][i] == pytest.approx(float(pred["P_it"]), rel=1e-3)
    assert ts["P_grid"][i] == pytest.approx(float(pred["P_grid"]), rel=1e-3)


class _AbusivePolicy(Policy):
    """Asks for the hottest legal supply water and the lowest flow at full clock."""
    name = "abusive"

    def _decide(self, obs):
        return Action((1.0, 1.0), self.cfg.t_sup_max, self.cfg.flow_min_factor, "abusive")


def test_independent_hardware_protection_bounds_temperature():
    cfg = make_config({"r_cond": 0.06, "drain_max_s": 1800.0})
    sc = replace(SCENARIOS["S1_moderate"], duration_s=1.0, t_amb=20.0)
    wl = _saturating_workload(cfg, hours=0.25)
    r = simulate(cfg, sc, _AbusivePolicy(cfg), seed=0, workload=wl, record_timeseries=False)
    assert r.m("chip_s_throttled") > 0
    # Throttled steady state must lie below the release point for protection to be effective
    R = float(ph.r_total(cfg.flow_min_factor, cfg))
    A = float(ph.temp_independent_power(cfg.s_min, 1.0, cfg))
    L = cfg.p_leak_ref * float(ph.voltage_ratio(cfg.s_min, cfg))
    T_thr, ok = ph.steady_temperature(cfg.t_sup_max, R, A, L, cfg)
    assert ok and float(T_thr) < cfg.t_throttle - cfg.throttle_hyst
    # Overshoot is bounded by one step of heating at full power
    max_step_rise = float(ph.chip_power(1.0, 120.0, 1.0, cfg)) * cfg.dt / cfg.c_th
    assert r.m("peak_T_j_C") <= cfg.t_throttle + max_step_rise


def test_time_step_convergence():
    """Halving dt should change total grid energy by well under 1%."""
    sc = replace(SCENARIOS["S1_moderate"], duration_s=3600.0, load_period_s=3600.0)
    e = {}
    for dt in (0.5, 1.0):
        cfg = make_config({"dt": dt})
        e[dt] = simulate(cfg, sc, POLICIES["fixed"](cfg), seed=2, record_timeseries=False).m("E_grid_kWh")
    assert abs(e[1.0] - e[0.5]) / e[0.5] < 0.01


def test_optimising_policies_respect_thermal_target_in_default_scenario():
    cfg = make_config()
    for name in ("joint", "cooling_only", "independent"):
        r = simulate(cfg, SHORT, POLICIES[name](cfg), seed=4, record_timeseries=False)
        assert r.m("chip_s_throttled") == 0, name


def test_chiller_energy_never_negative_when_supply_rises_above_idle_chips():
    """Regression (E001 v1 bug): cool ambient + controller raising supply temperature."""
    cfg = make_config()
    sc = replace(SCENARIOS["S4_cool"], duration_s=3600.0, load_period_s=3600.0)
    for name in ("independent", "cooling_only", "joint"):
        r = simulate(cfg, sc, POLICIES[name](cfg), seed=0, record_timeseries=True)
        assert r.m("E_chiller_kWh") >= 0.0, name
        assert min(r.timeseries["W_ch"]) >= 0.0, name
        assert r.m("E_loop_storage_kWh") <= 0.0
        assert r.m("energy_balance_rel_residual") < 1e-9
