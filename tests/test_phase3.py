"""Phase 3: dynamic coolant loop, move suppression, self-correcting joint controller,
and a guarantee that the legacy (E001-E005) configuration still reproduces bitwise."""
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from ueic import physics as ph
from ueic import twin
from ueic.params import make_config
from ueic.policies import POLICIES, Action, Policy
from ueic.sim import simulate
from ueic.workload import SCENARIOS, Workload

DB = Path(__file__).resolve().parents[1] / "results" / "ueic.sqlite"
MEASURED = {"controller_wall_mean_ms", "sim_wall_s"}
DYN = {"loop_mass_kg": 40.0, "tsup_ramp_K_per_min": 1.0}
SHORT = replace(SCENARIOS["S1_moderate"], duration_s=1800.0, load_period_s=1800.0)


@pytest.mark.skipif(not DB.exists(), reason="results database not present")
def test_legacy_configuration_reproduces_stored_e001_bitwise():
    from ueic.experiment import expand_cells, run_cell
    from ueic.store import Store
    s = Store(DB)
    eid = s.latest_experiment("E001")
    spec, runs = s.experiment(eid)["spec"], s.runs(eid)
    for sc, pol, seed in [("S3_hot", "joint", 3), ("S6_degraded_cooling", "independent", 1), ("S2_high_load", "compute_only", 0)]:
        cell = next(c for c in expand_cells(spec) if (c["scenario"], c["policy"], c["seed"]) == (sc, pol, seed))
        ref = next(r for r in runs if (r["scenario"], r["policy"], r["seed"]) == (sc, pol, seed))["metrics"]
        out = run_cell(cell)["metrics"]
        for m, v in ref.items():
            if m in MEASURED:
                continue
            assert out[m][0] == v or (v is None and out[m][0] != out[m][0]), (sc, pol, seed, m)
    s.close()


@pytest.mark.parametrize("name", ["fixed", "independent", "joint", "joint_robust"])
def test_dynamic_loop_energy_balance_closes(name):
    cfg = make_config(DYN)
    r = simulate(cfg, SHORT, POLICIES[name](cfg), seed=1, record_timeseries=True)
    assert r.m("energy_balance_rel_residual") < 1e-9
    assert r.m("E_chiller_kWh") >= 0 and min(r.timeseries["W_ch"]) >= 0
    assert r.m("tasks_completed") == r.m("tasks")


def test_supply_temperature_respects_ramp_limit():
    cfg = make_config(DYN)
    r = simulate(cfg, SHORT, POLICIES["joint"](cfg), seed=2, record_timeseries=True)
    T = np.array(r.timeseries["T_sup"])
    max_step = cfg.tsup_ramp_K_per_min * cfg.log_interval / 60.0
    assert np.all(np.abs(np.diff(T)) <= max_step + 1e-6)


def _saturating(cfg, n_per_chip=20, work=100.0):
    n = cfg.n_accel * n_per_chip
    z = np.zeros(n)
    return Workload(arrival=z, work=np.full(n, work), cls=np.zeros(n, dtype=np.int8), easy=np.zeros(n, bool),
                    u_small=z, u_verify=z, u_large=z, slo=np.full(n, 1e9))


def test_dynamic_loop_settles_to_twin_steady_state():
    cfg = make_config({**DYN, "drain_max_s": 2400.0})
    sc = replace(SCENARIOS["S1_moderate"], duration_s=1.0, t_amb=20.0)
    r = simulate(cfg, sc, POLICIES["fixed"](cfg), seed=0, workload=_saturating(cfg), initial_T=30.0)
    ts = r.timeseries
    i = 25  # t = 1500 s: >> tank time constant (M/m_dot ~ 250 s) and chip time constant
    pred = twin.evaluate(cfg, np.array([cfg.n_accel, 0.0]), 1.0, 1.0, cfg.fixed_t_sup, cfg.fixed_flow, 20.0)
    assert ts["busy"][i] == cfg.n_accel
    assert ts["T_sup"][i] == pytest.approx(cfg.fixed_t_sup, abs=0.01)
    assert ts["T_mean"][i] == pytest.approx(float(pred["T_c"]), abs=0.02)
    assert ts["P_grid"][i] == pytest.approx(float(pred["P_grid"]), rel=2e-3)


class _StepUpSetpoint(Policy):
    """18 C for the first interval, then the hottest legal setpoint."""
    name = "step_up"

    def _decide(self, obs):
        return Action((0.5, 0.5), 18.0 if obs.t == 0 else self.cfg.t_sup_max, 1.0, "step")


def test_plant_passes_water_through_instead_of_heating():
    """After the setpoint jumps above the return temperature the plant must do no work:
    the tank warms only from chip and pump heat, never faster than that heat allows."""
    cfg = make_config({"loop_mass_kg": 40.0})
    sc = replace(SCENARIOS["S1_moderate"], duration_s=900.0, load_mean=0.3, load_amp=0.0, t_amb=10.0)
    r = simulate(cfg, sc, _StepUpSetpoint(cfg), seed=0, record_timeseries=True, initial_T=25.0)
    T = np.array(r.timeseries["T_sup"])
    assert r.m("E_chiller_kWh") == 0.0
    assert r.m("E_loop_storage_kWh") > 0.0
    assert np.all(np.diff(T[1:]) > 0) and T[-1] < cfg.t_sup_max
    assert r.m("energy_balance_rel_residual") < 1e-9


def test_tiny_loop_mass_approaches_quasi_steady_plant():
    legacy = make_config()
    tiny = make_config({"loop_mass_kg": 0.05})
    for name in ("fixed", "joint"):
        a = simulate(legacy, SHORT, POLICIES[name](legacy), seed=3, record_timeseries=False).m("E_grid_kWh")
        b = simulate(tiny, SHORT, POLICIES[name](tiny), seed=3, record_timeseries=False).m("E_grid_kWh")
        assert abs(b - a) / a < 0.01, name


def test_move_suppression_reduces_switching_at_small_cost():
    sc = SCENARIOS["S1_moderate"]
    base = make_config()
    held = make_config({"joint_switch_rel": 0.05})
    a = simulate(base, sc, POLICIES["joint"](base), seed=4, record_timeseries=False)
    b = simulate(held, sc, POLICIES["joint"](held), seed=4, record_timeseries=False)
    assert b.m("action_changes") < a.m("action_changes")
    assert abs(b.m("E_grid_kWh") - a.m("E_grid_kWh")) / a.m("E_grid_kWh") < 0.03


def test_robust_joint_reduces_overheating_when_twin_underestimates_leakage():
    truth = {"kappa_leak": 0.03, "p_leak_ref": 130.0}
    wrong = {**truth, "kappa_leak": 0.012, "p_leak_ref": 70.0}
    sc = replace(SCENARIOS["S3_hot"], duration_s=3600.0, load_period_s=3600.0)
    cfg = make_config(truth)
    model = make_config(wrong)
    plain = simulate(cfg, sc, POLICIES["joint"](model), seed=0, record_timeseries=False)
    robust = simulate(cfg, sc, POLICIES["joint_robust"](model), seed=0, record_timeseries=False)
    assert plain.m("chip_s_over_target") > 0
    assert robust.m("chip_s_over_target") < 0.5 * plain.m("chip_s_over_target")


def test_robust_joint_matches_joint_when_twin_is_right():
    cfg = make_config()
    a = simulate(cfg, SHORT, POLICIES["joint"](cfg), seed=5, record_timeseries=False).m("E_grid_kWh")
    b = simulate(cfg, SHORT, POLICIES["joint_robust"](cfg), seed=5, record_timeseries=False).m("E_grid_kWh")
    assert abs(b - a) / a < 0.02


def test_tank_step_is_exact_first_order_response():
    M_cp, Cdot = 40 * 4180.0, 666.8
    T = 30.0
    for _ in range(100):
        T = float(ph.tank_step(T, 18.0, Cdot, M_cp, 1.0))
    assert T == pytest.approx(18.0 + 12.0 * np.exp(-Cdot * 100 / M_cp), abs=1e-9)


def test_warm_start_removes_initial_condition_artifact_in_dynamic_loop():
    """Regression (E006 v1): with a cold start, the joint controller's zero-demand first decision set
    a 12 C initial tank, whose stored 'coldness' it then used up during the run. With a warm start each
    policy starts in its own steady state; the load cycle ends where it began, so storage change is small."""
    sc = replace(SCENARIOS["S3_hot"], duration_s=7200.0, load_period_s=7200.0)
    cold = make_config({"loop_mass_kg": 150.0, "tsup_ramp_K_per_min": 0.25})
    warm = make_config({"loop_mass_kg": 150.0, "tsup_ramp_K_per_min": 0.25, "warm_start": 1.0})
    rc = simulate(cold, sc, POLICIES["joint"](cold), seed=0, record_timeseries=False)
    rw = simulate(warm, sc, POLICIES["joint"](warm), seed=0, record_timeseries=False)
    assert abs(rc.m("E_loop_storage_kWh")) > 0.02 * rc.m("E_grid_kWh")      # the artifact
    for name in ("joint", "independent", "fixed"):
        r = rw if name == "joint" else simulate(warm, sc, POLICIES[name](warm), seed=0, record_timeseries=False)
        assert abs(r.m("E_loop_storage_kWh")) < 0.005 * r.m("E_grid_kWh"), name
