"""Model-routing cascade: simulation vs analytic expectations."""
from dataclasses import replace

import numpy as np
import pytest

from ueic.params import make_config
from ueic.policies import POLICIES
from ueic.sim import simulate
from ueic.workload import SCENARIOS, generate, routing_expectations

SC = replace(SCENARIOS["S1_moderate"], routing=True)


def test_analytic_break_even_perfect_verifier():
    cfg = make_config()
    e = routing_expectations(cfg)
    Ep = cfg.frac_easy * cfg.p_small_easy + (1 - cfg.frac_easy) * cfg.p_small_hard
    assert e["p_reject"] == pytest.approx(1 - Ep)
    assert e["work_ratio"] == pytest.approx(cfg.small_cost_ratio + cfg.verify_cost_ratio + 1 - Ep)
    # perfect verifier: escalations get the large model, so quality is preserved exactly
    assert e["success_cascade"] == pytest.approx(Ep + (1 - Ep) * cfg.p_large)
    # break-even: rs + rv = E[p]  <=> work ratio = 1
    cfg2 = make_config({"small_cost_ratio": Ep - cfg.verify_cost_ratio})
    assert routing_expectations(cfg2)["work_ratio"] == pytest.approx(1.0)


def test_simulated_escalation_rate_and_work_match_analytic():
    cfg = make_config()
    wl = generate(cfg, SC, 11)
    r = simulate(cfg, SC, POLICIES["fixed"](cfg), seed=11, workload=wl, record_timeseries=False)
    e = routing_expectations(cfg)
    n = wl.n
    p_hat = r.m("escalations") / n
    se = np.sqrt(e["p_reject"] * (1 - e["p_reject"]) / n)
    assert abs(p_hat - e["p_reject"]) < 4 * se
    # work enqueued per unit of large-model work: compare against analytic ratio
    ratio = r.m("work_enqueued_s") / wl.work.sum()
    assert ratio == pytest.approx(e["work_ratio"], abs=0.03)
    assert r.m("work_done_s") == pytest.approx(r.m("work_enqueued_s"), rel=1e-9)


def test_false_accepts_reduce_quality():
    base = make_config()
    leaky = make_config({"verifier_false_accept": 0.2})
    wl = generate(base, SC, 12)
    a = simulate(base, SC, POLICIES["fixed"](base), seed=12, workload=wl, record_timeseries=False)
    b = simulate(leaky, SC, POLICIES["fixed"](leaky), seed=12, workload=wl, record_timeseries=False)
    assert b.m("tasks_correct") < a.m("tasks_correct")
    assert routing_expectations(leaky)["success_cascade"] < routing_expectations(base)["success_cascade"]
