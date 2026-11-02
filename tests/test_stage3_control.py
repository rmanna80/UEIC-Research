"""Stage 3 (next generation): forecasts, plant futures, safety filter, fallback and multi-step MPC."""
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from ueic import physics as ph
from ueic.control import forecast as fc
from ueic.control import futures as fu
from ueic.control.fallback import fallback_action, safest_clocks
from ueic.control.safety_filter import SafetyFilter
from ueic.params import make_config
from ueic.policies import POLICIES, Action, Observation
from ueic.sim import simulate
from ueic.workload import SCENARIOS, ambient, generate, offered_load

ROOT = Path(__file__).resolve().parents[1]
E011 = json.loads((ROOT / "experiments" / "E011_lag_aware.json").read_text())


def _cfg(**kw):
    return make_config({**E011["design"]["param_overrides"], "r_cond": 0.045, "r_conv_ref": 0.030, "warm_start": 1.0, **kw})


def _obs(t=600.0, T_sup=40.0, D=(3.0, 1.0), backlog=(0.0, 0.0), T_amb=30.0, T_j=None):
    return Observation(t=t, D_est=np.array(D), backlog=np.array(backlog), T_amb=T_amb, p_chip_peak=500.0, q_chips=4000.0,
                       T_j=np.array([60.0] * 8 if T_j is None else T_j), T_j_peak=60.0, T_sup_actual=T_sup)


# ------------------------------------------------------------------ scenario extensions
def test_bursts_ambient_profile_and_legacy_scenarios_unchanged():
    sc = SCENARIOS["S1_moderate"]
    assert offered_load(1000.0, sc) == pytest.approx(sc.load_mean + sc.load_amp * np.sin(2 * np.pi * 1000 / sc.load_period_s))
    b = replace(sc, bursts=((600.0, 300.0, 0.3),), t_amb_profile=((0.0, 20.0), (3600.0, 40.0)))
    assert offered_load(700.0, b) - offered_load(700.0, sc) == pytest.approx(0.3)
    assert offered_load(1000.0, b) == pytest.approx(offered_load(1000.0, sc))
    assert ambient(1800.0, b) == pytest.approx(30.0) and ambient(1800.0, sc) == sc.t_amb
    cfg = make_config()
    w0, w1 = generate(cfg, sc, 3), generate(cfg, replace(sc, description="x"), 3)
    assert np.array_equal(w0.arrival, w1.arrival)                      # unchanged generator for old scenarios
    wb = generate(cfg, b, 3)
    inb = lambda w: np.sum((w.arrival >= 600) & (w.arrival < 900))
    assert inb(wb) > inb(w0)


def test_command_delay_reaches_the_plant_late():
    class Script:
        name = "script"
        def __init__(self): self.decision_wall_s = []
        def decide(self, obs):
            return Action((1.0, 0.5), 30.0 if obs.t < 600 else 20.0, 1.0, "s")
    sc = replace(SCENARIOS["S1_moderate"], duration_s=1500.0)
    for delay in (0.0, 180.0):
        cfg = make_config({"tsup_cmd_delay_s": delay})
        r = simulate(cfg, sc, Script(), seed=1)
        ts = r.timeseries
        Ts = dict(zip(ts["t"], ts["T_sup"]))
        assert Ts[600.0 + 60] == pytest.approx(20.0 if delay == 0 else 30.0)
        assert Ts[600.0 + 240] == pytest.approx(20.0)
        assert r.m("energy_balance_rel_residual") < 1e-9


# ------------------------------------------------------------------ forecasts
def test_forecasters():
    cfg = make_config()
    sc = replace(SCENARIOS["S1_moderate"], bursts=((900.0, 300.0, 0.4),))
    obs = _obs(t=600.0)
    p = fc.PersistenceForecaster().demand(obs, 5, 60.0, cfg)
    assert p.shape == (5, 2) and np.all(p == obs.D_est)
    o = fc.ScenarioForecaster(sc, 0).demand(obs, 10, 60.0, cfg)
    t = 600.0 + (np.arange(10) + 0.5) * 60
    assert o[:, 0] == pytest.approx(offered_load(t, sc) * 8 * (1 - cfg.frac_memory))
    blind = fc.ScenarioForecaster(sc, 0, see_bursts=False).demand(obs, 10, 60.0, cfg)
    assert o[6, 0] > blind[6, 0] and o[0, 0] == pytest.approx(blind[0, 0])
    n1 = fc.ScenarioForecaster(sc, 5, noise=0.3).demand(obs, 10, 60.0, cfg)
    n2 = fc.ScenarioForecaster(sc, 5, noise=0.3).demand(obs, 10, 60.0, cfg)
    assert np.array_equal(n1, n2) and not np.allclose(n1, o)
    assert fc.ScenarioForecaster(sc, 0, bias=-0.3).demand(obs, 3, 60.0, cfg) == pytest.approx(0.7 * o[:3])


# ------------------------------------------------------------------ plant futures
def test_trajectories_instant_ramp_and_tank_match_the_simulator_equations():
    cmd, flow = np.array([30.0, 40.0]), np.array([1.0])
    inst = fu.trajectories(make_config(), 35.0, 35.0, 35.0, [], cmd, flow, 4000.0, 3, 60.0)
    assert inst["T_peak"][:, 0, 0] == pytest.approx([30.0] * 3) and inst["T_peak"][0, 1, 0] == pytest.approx(40.0)
    ramp = fu.trajectories(make_config({"tsup_ramp_K_per_min": 1.0}), 35.0, 35.0, 35.0, [], cmd, flow, 4000.0, 3, 60.0)
    assert ramp["T_mean"][:, 0, 0][-1] == pytest.approx(33.0 - 21.0 / 36.0, abs=1e-6)   # 1 K/min; mean of 6 sub-step ends in minute 3
    cfg = make_config({"loop_mass_kg": 40.0, "tsup_ramp_K_per_min": 1.0})
    q = 4000.0
    tr = fu.trajectories(cfg, 40.0, 40.0, 40.0, [], np.array([30.0]), flow, q, 4, 60.0, n_sub=60)
    # reference: the simulator's dynamic-plant equations at 1 s steps
    T, sp, M_cp = 40.0, 40.0, 40.0 * cfg.water_cp
    Cdot = float(cfg.n_accel * ph.mass_flow_per_accel(1.0, cfg) * cfg.water_cp)
    last = []
    for i in range(240):
        sp += np.clip(30.0 - sp, -1 / 60, 1 / 60)
        T = float(ph.tank_step(T, sp, Cdot, M_cp, 1.0)) if sp < T + q / Cdot else T + q / M_cp
        if i >= 180:
            last.append(T)
    assert tr["T_mean"][-1, 0, 0] == pytest.approx(np.mean(last), abs=1e-6)


def test_setpoint_tracker_follows_delay_and_ramp():
    cfg = make_config({"tsup_ramp_K_per_min": 1.0, "tsup_cmd_delay_s": 120.0})
    tr = fu.PlantSetpointTracker(cfg)
    tr.advance(0.0); tr.issue(0.0, 40.0)
    tr.advance(60.0); tr.issue(60.0, 30.0)
    assert tr.advance(120.0) == pytest.approx(40.0)                  # command not arrived yet
    assert tr.advance(300.0) == pytest.approx(38.0)                   # arrived at 180 s, 2 min down at 1 K/min
    assert tr.advance(1200.0) == pytest.approx(30.0)


def test_supply_bound_never_credits_cooling_and_never_exceeds_target():
    cfg = make_config({"loop_mass_kg": 40.0, "tsup_ramp_K_per_min": 1.0})
    b = fu.supply_upper_bound(cfg, 40.0, np.array([30.0, 40.0, 45.0, 60.0]), np.array([1.0]), 60.0)
    assert b[0] == 40.0 and b[1] == 40.0 and 40.0 < b[2] <= 45.0 and b[3] <= 40.0 + fu.warming_rate_bound(cfg) * 60 + 1e-9


# ------------------------------------------------------------------ safety filter and fallback
def test_filter_approves_safe_actions_and_lowers_clocks_when_the_cold_water_has_not_arrived():
    cfg = _cfg(loop_mass_kg=40.0, tsup_ramp_K_per_min=1.0)
    f = SafetyFilter(cfg)
    f.validate(Action((0.6, 0.5), 45.0, 1.0, "init"), _obs(t=0.0, T_sup=45.0))
    ok = f.validate(Action((0.5, 0.5), 45.0, 2.0, "p"), _obs(t=60.0, T_sup=45.0))
    assert ok.s == (0.5, 0.5) and f.counts["ok"] == 2
    st = fu.chip_states(cfg, 1.0, 0.5, 25.0, 2.0)
    assert bool(fu.temps_ok(st, cfg))                                 # full clock is safe at 25 C ...
    out = f.validate(Action((1.0, 0.5), 25.0, 2.0, "p"), _obs(t=120.0, T_sup=45.0))
    assert out.s[0] < 1.0 and out.note.endswith("filtered")          # ... but the chips still see 45 C


def test_filter_falls_back_on_missing_or_bad_telemetry():
    cfg = _cfg(loop_mass_kg=40.0, tsup_ramp_K_per_min=1.0)
    f = SafetyFilter(cfg)
    f.validate(Action((0.6, 0.5), 40.0, 1.0, "init"), _obs(t=0.0))
    a = f.validate(Action((1.0, 0.5), 40.0, 1.0, "p"), _obs(t=60.0, T_sup=float("nan")))
    assert a.note.startswith("fallback:no-supply-telemetry") and a.flow == max(a.flow, 2.0)
    b = f.validate(Action((1.0, 0.5), 40.0, 1.0, "p"), _obs(t=120.0, T_j=[60.0] * 7 + [float("nan")]))
    assert b.note.startswith("fallback:bad-junction-telemetry")
    assert f.counts["fallback"] == 2


def test_fallback_is_safe_at_the_assumed_supply_and_prefers_useful_clocks():
    cfg = _cfg(loop_mass_kg=40.0)
    a = fallback_action(cfg, 44.0, "test")
    st = fu.chip_states(cfg, a.s[0], a.s[1], 44.0, a.flow)
    assert bool(fu.temps_ok(st, cfg)) and a.t_sup == cfg.t_sup_min
    assert a.s[1] == 0.5                                              # beta_memory = 0: no point raising it
    worst = fallback_action(cfg, None, "no telemetry")
    assert bool(fu.temps_ok(fu.chip_states(cfg, worst.s[0], worst.s[1], cfg.t_sup_max, worst.flow), cfg))


# ------------------------------------------------------------------ MPC
def test_mpc_falls_back_on_solver_failure_and_timeout_and_stays_safe():
    cfg = _cfg(loop_mass_kg=40.0, tsup_ramp_K_per_min=1.0)
    sc = replace(SCENARIOS["S6_degraded_cooling"], t_amb=35.0, duration_s=1200.0, load_period_s=1200.0)
    for mode in ("raise", "timeout"):
        pol = POLICIES["mpc"](cfg)
        pol.fail_next = mode
        r = simulate(cfg, sc, pol, seed=2, record_timeseries=False)
        key = "fallback:solver-error" if mode == "raise" else "fallback:timeout"
        assert pol.events.get(key, 0) >= 15 and r.m("chip_s_over_target") == 0
        assert r.m("energy_balance_rel_residual") < 1e-9


def test_mpc_on_an_instant_plant_is_safe_and_balanced():
    cfg = _cfg()
    sc = replace(SCENARIOS["S6_degraded_cooling"], t_amb=30.0, duration_s=1800.0, load_period_s=1800.0)
    pol = POLICIES["mpc"](cfg)
    r = simulate(cfg, sc, pol, seed=4, record_timeseries=False)
    assert r.m("chip_s_over_target") == 0 and r.m("energy_balance_rel_residual") < 1e-9 and pol.events.get("opt", 0) > 25


def test_mpc_precools_a_slow_loop_before_a_forecast_burst():
    """Exploratory regression (disclosed in E015): with a scheduled burst the forecast can see, the MPC lowers
    the setpoint before the burst so the tank is cold when the extra heat arrives."""
    cfg = _cfg(loop_mass_kg=150.0, tsup_ramp_K_per_min=0.25, mpc_forecast_mode=1)
    sc = replace(SCENARIOS["S6_degraded_cooling"], t_amb=40.0, duration_s=3600.0, load_period_s=3600.0, load_mean=0.55,
                 load_amp=0.0, bursts=((2400.0, 900.0, 0.35),))
    pol = POLICIES["mpc"](cfg)
    pol.attach_scenario(sc, 0)
    ts = simulate(cfg, sc, pol, seed=0).timeseries
    before = [c for t, c in zip(ts["t"], ts["T_sup_cmd"]) if 1500 <= t < 2400]
    at = [T for t, T in zip(ts["t"], ts["T_sup"]) if t >= 2400][0]
    assert min(before) < 40.0 and at < 40.0


def test_robust_mpc_scenarios_and_policy_registration():
    cfg = _cfg(loop_mass_kg=40.0, tsup_ramp_K_per_min=1.0)
    pol = POLICIES["mpc_robust"](cfg)
    scen = pol._safety_scenarios()
    assert len(scen) == 5 and {c.loop_mass_kg for c in scen} == {20.0, 40.0, 80.0}
    assert "mpc" in POLICIES and "joint" in POLICIES
