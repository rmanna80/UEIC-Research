"""Stages 5-6: thermal capacity budgets, placement policies and the multi-node facility simulator."""
from __future__ import annotations

import numpy as np
import pytest

from ueic import physics as ph
from ueic.facility import cooling_network as cn
from ueic.facility import networking as net
from ueic.facility.cluster import from_dict, make_topology
from ueic.facility.facility_simulator import FacilityConfig, FacilitySim, FacilityView
from ueic.facility.jobs import Job, JobSpec, generate
from ueic.facility.power_network import cap_group
from ueic.params import make_config
from ueic.scheduling.placement import SCHEDULERS, make_scheduler
from ueic.scheduling.thermal_capacity import energy_budget, power_budget, time_to_limit
from ueic.scheduling.thermal_admission import admit


def test_power_budget_is_exact_for_the_lumped_node():
    T0, T_in, R, C, P, T_lim = 50.0, 30.0, 0.06, 300.0, 300.0, 80.0
    for H in (5.0, 30.0, 120.0, 1e4):
        dP = float(power_budget(T0, T_in, R, C, P, T_lim, H))
        T = T0
        for _ in range(1000):
            T, _ = ph.thermal_step(T, P + dP, T_in, R, C, H / 1000)
        assert T == pytest.approx(T_lim, abs=1e-6)
    short = float(power_budget(T0, T_in, R, C, P, T_lim, 0.01))
    assert short == pytest.approx(C * (T_lim - T0) / 0.01, rel=0.01)                   # stored-heat limit
    assert float(power_budget(T0, T_in, R, C, P, T_lim, 1e6)) == pytest.approx((T_lim - T_in) / R - P)   # steady
    assert float(energy_budget(T0, T_in, R, C, P, T_lim, 60.0)) == pytest.approx(60 * float(power_budget(T0, T_in, R, C, P, T_lim, 60.0)))


def test_time_to_limit():
    t = float(time_to_limit(50.0, 30.0, 0.06, 300.0, 1000.0, 80.0))
    T = 50.0
    T, _ = ph.thermal_step(T, 1000.0, 30.0, 0.06, 300.0, t)
    assert T == pytest.approx(80.0, abs=1e-9)
    assert np.isinf(time_to_limit(50.0, 30.0, 0.06, 300.0, 100.0, 80.0))
    assert time_to_limit(85.0, 30.0, 0.06, 300.0, 100.0, 80.0) == 0.0


def test_flow_distribution_analytic_cases():
    qd = np.array([9.6, 9.6])
    q, dp = cn.distribute(19.2, qd, np.ones(2), np.ones(2), 50e3)
    assert np.allclose(q, 9.6) and dp == pytest.approx(50e3)
    q, dp = cn.distribute(19.2, qd, np.array([1.0, 4.0]), np.ones(2), 50e3)
    assert q[0] / q[1] == pytest.approx(2.0) and q.sum() == pytest.approx(19.2)
    for i in range(2):                                    # every branch sees the same pressure drop
        assert 50e3 * [1.0, 4.0][i] * (q[i] / qd[i]) ** 2 == pytest.approx(dp)
    v = cn.heat_proportional_valves(np.array([4000.0, 1000.0]), qd, np.ones(2))
    q, _ = cn.distribute(19.2, qd, np.ones(2), v, 50e3)
    assert q[0] / q[1] == pytest.approx(4.0, rel=1e-6)          # floor 0.3 x mean = 750 < 1000: proportional
    v = cn.heat_proportional_valves(np.array([4000.0, 100.0]), qd, np.ones(2))
    q, _ = cn.distribute(19.2, qd, np.ones(2), v, 50e3)
    assert q[0] / q[1] == pytest.approx(4000.0 / 615.0, rel=1e-6)   # floor 0.3 x 2050 = 615 > 100
    cfg = make_config({})
    assert cn.pump_power(qd[0], 50e3 * 0 + cfg.dp_ref, cfg.eta_pump) == pytest.approx(float(ph.pump_power(1.0, cfg)))


def test_power_cap_and_network_factors():
    s = np.ones(4); busy = np.array([True, True, True, False])
    pf = lambda x: 100.0 * x ** 3 + 10.0          # noqa: E731
    capped, hit = cap_group(s, busy, pf, 250.0, 0.5)
    assert hit and pf(capped).sum() <= 250.0 + 1e-6 and capped[3] == 1.0
    same, hit = cap_group(s, busy, pf, 1e6, 0.5)
    assert not hit and np.array_equal(same, s)
    assert net.comm_factor(1, 1) == 1.0 and net.comm_factor(2, 2) == pytest.approx(0.81)
    assert net.uplink_factor(8, 4) == 0.5 and net.migration_cost_s(20.0, 10.0) == 7.0


def _sim(topo, sched="least_loaded", load=0.6, dur=1200.0, seed=0, dt=2.0, **fc):
    cl = from_dict(topo)
    jobs = generate(JobSpec(load=load), cl.n_gpus, dur, seed)
    return FacilitySim(cl, make_scheduler(sched), jobs, FacilityConfig(dt=dt, duration_s=dur, drain_s=600.0, **fc),
                       {"plant_model": 1})


def test_steady_state_and_series_inlet_rise():
    cl = from_dict(make_topology(1, 1, 2, chain=2))
    job = Job(0, 0.0, 2, 1e9, 10.0, False, 1e12)
    sim = FacilitySim(cl, make_scheduler("least_loaded"), [job], FacilityConfig(duration_s=600, drain_s=0, T_set=30.0))
    sim.run()
    # downstream plate inlet = supply + upstream heat / (m_dot c_p); junction ~ inlet + R P at steady state
    assert sim.T_in[1] == pytest.approx(30.0 + sim.Qrate[0] / sim.cdot[0], rel=1e-3)
    assert sim.T_in[0] == pytest.approx(30.0)
    assert sim.T[1] == pytest.approx(sim.T_in[1] + sim.R[1] * sim.P[1], abs=0.05)


def test_energy_conservation_and_completion():
    out = _sim(make_topology(1, 2, 8, chain=2, hydraulic_spread=0.5), "thermal_credit").run()["metrics"]
    assert abs(out["energy_balance_rel"]) < 1e-9
    assert out["jobs_completed"] > 0 and out["E_grid_kWh"] > out["E_it_kWh"] > 0


def test_scaling_one_to_many_identical_nodes():
    """Four identical, hydraulically equal nodes given four copies of one node's workload must reproduce the
    single node per GPU (each copy fits one node; least_loaded spreads them)."""
    import copy
    base = generate(JobSpec(load=0.6), 8, 2400.0, 3)
    fc = FacilityConfig(duration_s=2400.0, drain_s=600.0)
    one = FacilitySim(from_dict(make_topology(1, 1, 8)), make_scheduler("least_loaded"), copy.deepcopy(base), fc,
                      {"plant_model": 1}).run()["metrics"]
    jobs4 = []
    for k in range(4):
        for j in copy.deepcopy(base):
            j.id = j.id * 4 + k
            jobs4.append(j)
    four = FacilitySim(from_dict(make_topology(2, 2, 8)), make_scheduler("least_loaded"), jobs4, fc,
                       {"plant_model": 1}).run()["metrics"]
    assert four["n_gpus"] == 32 and four["jobs_completed"] == 4 * one["jobs_completed"]
    for k in ("E_per_work_kJ", "utilisation", "E_per_job_kJ"):
        assert four[k] == pytest.approx(one[k], rel=0.02), k
    assert four["E_grid_kWh"] == pytest.approx(4 * one["E_grid_kWh"], rel=0.02)


def test_timestep_convergence():
    a = _sim(make_topology(1, 1, 8, chain=2), dt=1.0, seed=5).run()["metrics"]
    b = _sim(make_topology(1, 1, 8, chain=2), dt=2.0, seed=5).run()["metrics"]
    assert b["E_grid_kWh"] == pytest.approx(a["E_grid_kWh"], rel=0.02)
    assert b["work_done_gpu_s"] == pytest.approx(a["work_done_gpu_s"], rel=0.02)


def test_jobs_are_seeded_and_match_offered_load():
    a, b = generate(JobSpec(load=0.5), 64, 36000, 7), generate(JobSpec(load=0.5), 64, 36000, 7)
    assert [j.arrival for j in a] == [j.arrival for j in b]
    offered = sum(j.work * j.n_gpus for j in a) / 36000 / 64
    assert offered == pytest.approx(0.5, rel=0.1)


def test_every_scheduler_returns_valid_placements():
    for name in SCHEDULERS:
        out = _sim(make_topology(1, 2, 4, chain=2), name, load=0.9, dur=900.0).run()["metrics"]
        assert out["jobs_completed"] > 0, name


def test_thermal_credit_prefers_cool_upstream_capacity():
    """Two nodes, the second with very poor flow: thermal credit should place on the first."""
    cl = from_dict(make_topology(1, 2, 2, chain=2, hydraulic_spread=30.0))
    sim = FacilitySim(cl, make_scheduler("thermal_credit"), [], FacilityConfig(duration_s=10, drain_s=0, T_set=40.0))
    sim._hydraulics(); sim._inlets()
    view = FacilityView(sim)
    g, s = sim.sched.select(Job(0, 0.0, 1, 600.0, 10.0, False, 1e9), view, 0.0)
    assert sim.node_of[g[0]] == 0 and s == 1.0


def test_admission_rule():
    assert admit((0.1, [0], 1.0), None, 100, 50, 60)[0] == "start"
    assert admit((-0.1, [0], 1.0), (0.05, [0], 0.8), 100, 50, 60)[0] == "start_reduced"
    assert admit((-0.1, [0], 1.0), None, 500, 50, 60)[0] == "hold"
    assert admit((-0.1, [0], 1.0), None, 80, 50, 60)[0] == "start_over_budget"
