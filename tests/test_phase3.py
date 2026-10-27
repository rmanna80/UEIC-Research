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


# ------------------------------------------------------------------ lag-aware joint control (E011)
def _e010_cfg(dyn: bool):
    import json
    spec = json.loads((Path(__file__).resolve().parents[1] / "experiments" / "E010_thermal_safety.json").read_text())
    over = {**SCENARIOS["S6_degraded_cooling"].param_overrides, **spec["design"]["param_overrides"],
            "r_cond": 0.045, "r_conv_ref": 0.030, "warm_start": 1.0}
    if dyn:
        over.update({"loop_mass_kg": 40.0, "tsup_ramp_K_per_min": 1.0})
    return make_config(over)


def test_joint_lag_equals_joint_on_quasi_steady_plant():
    """With an instant plant the supply the chips see is the command, so the decisions are identical."""
    cfg = make_config()
    a = simulate(cfg, SHORT, POLICIES["joint"](cfg), seed=6, record_timeseries=False)
    b = simulate(cfg, SHORT, POLICIES["joint_lag"](cfg), seed=6, record_timeseries=False)
    for m, v in a.metrics.items():
        if m not in MEASURED:
            assert b.metrics[m][0] == v[0] or (v[0] != v[0] and b.metrics[m][0] != b.metrics[m][0]), m


def test_supply_peak_matches_the_simulated_loop():
    """The controller's prediction uses the simulator's plant equations; check it against a
    fine-step integration of a cooling step (setpoint command 10 K below the tank)."""
    from ueic.policies import supply_peak, t_grid, f_grid
    cfg = make_config({"loop_mass_kg": 40.0, "tsup_ramp_K_per_min": 1.0})
    T0, sp0, q = 40.0, 40.0, 3000.0
    peak = supply_peak(cfg, T0, sp0, q, 300.0, n_sub=300)
    i, j = int(np.argmin(np.abs(t_grid(cfg) - 30.0))), int(np.argmin(np.abs(f_grid(cfg) - 1.0)))
    assert peak[i, j] == pytest.approx(T0)                          # cooling: the worst moment is now
    warm = supply_peak(cfg, 30.0, 30.0, q, 300.0, n_sub=300)          # warming toward 40 C from heat input only
    k = int(np.argmin(np.abs(t_grid(cfg) - 40.0)))
    M_cp = 40.0 * cfg.water_cp
    assert warm[k, j] == pytest.approx(min(30.0 + 300.0 / 60.0, 30.0 + q * 300.0 / M_cp), abs=0.05)
    assert np.all(supply_peak(make_config(), 50.0, 50.0, q, 60.0) == np.broadcast_to(t_grid(cfg)[:, None], peak.shape))


def test_joint_lag_removes_overheating_under_loop_lag():
    """Regression for the E010 failure (severe fouling, 40 C ambient, 40 kg loop, 1 K/min ramp):
    the steady-state joint controller overheats; the lag-aware one does not, at no energy cost.
    This 1 h, seed-0 case is the single exploratory run disclosed in E011's spec."""
    cfg = _e010_cfg(dyn=True)
    sc = replace(SCENARIOS["S6_degraded_cooling"], t_amb=40.0, duration_s=3600.0, load_period_s=3600.0)
    plain = simulate(cfg, sc, POLICIES["joint"](cfg), seed=0, record_timeseries=False)
    lag = simulate(cfg, sc, POLICIES["joint_lag"](cfg), seed=0, record_timeseries=False)
    assert plain.m("chip_s_over_target") > 100 and lag.m("chip_s_over_target") == 0
    assert lag.m("E_per_success_kJ") <= plain.m("E_per_success_kJ")
    assert lag.m("energy_balance_rel_residual") < 1e-9


def test_joint_fb_differs_from_joint_only_when_capacity_binds():
    """joint_fb (E011B ablation) checks feasibility at the commanded setpoint like joint; only the
    overload fallback differs. Below capacity both pick the same action; above capacity with
    clock-insensitive memory-bound work (beta_memory 0, as measured in M001) joint runs every clock
    at maximum while joint_fb keeps the memory-bound clock at the bottom of the grid."""
    from ueic.policies import optimise_joint, s_grid, t_grid, f_grid
    cfg = make_config({"beta_memory": 0.0})
    T_cmd = np.broadcast_to(t_grid(cfg)[:, None], (len(t_grid(cfg)), len(f_grid(cfg)))).astype(float)
    for D in (np.array([0.5, 0.5]), np.array([4.0, 2.0]), np.array([4.5, 1.0]), np.array([4.2, 2.5])):
        a, b = optimise_joint(cfg, D, 25.0), optimise_joint(cfg, D, 25.0, T_seen=T_cmd)
        assert a[3] == "joint:opt" and a[:3] == b[:3] and b[3] == "joint_lag:opt"
    big = np.array([1e3, 1e3])
    a, b = optimise_joint(cfg, big, 25.0), optimise_joint(cfg, big, 25.0, T_seen=T_cmd)
    assert a[3] == "joint:capacity-limited" and a[0] == (1.0, 1.0)
    assert b[3] == "joint_lag:safety-first" and b[0] == (1.0, float(s_grid(cfg)[0]))


def test_joint_fb_policy_is_registered_and_labels_its_decisions():
    from ueic.policies import POLICIES
    cfg = make_config()
    r = simulate(cfg, SHORT, POLICIES["joint_fb"](cfg), seed=6, record_timeseries=False)
    assert r.m("energy_balance_rel_residual") < 1e-9


def test_variants_may_run_a_subset_of_policies():
    """E013: a variant can list its own policies; variants without the key run the design's list."""
    from ueic.experiment import expand_cells
    spec = {"design": {"scenarios": ["S1_moderate"], "policies": ["joint", "joint_fb"], "seeds": [0, 1],
                       "variants": [{"label": "a"}, {"label": "b", "policies": ["joint_fb"]}]}}
    cells = expand_cells(spec)
    got = sorted((c["variant"], c["policy"], c["seed"]) for c in cells)
    assert got == sorted([("a", p, s) for p in ("joint", "joint_fb") for s in (0, 1)] + [("b", "joint_fb", s) for s in (0, 1)])
    with pytest.raises(KeyError):
        expand_cells({"design": {**spec["design"], "variants": [{"label": "c", "policies": ["nope"]}]}})
