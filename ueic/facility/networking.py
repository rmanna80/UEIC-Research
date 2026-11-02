"""Communication and placement costs (illustrative, stated forms; class G).

  * A job spread over several nodes runs at (1 - c_node) of its single-node rate; over several racks at
    (1 - c_node)(1 - c_rack).
  * Each rack's uplink carries ``uplink_jobs`` cross-node jobs without slowdown; with n > uplink_jobs
    such jobs touching the rack, each is slowed by uplink_jobs / n (fair share of a saturated link).
  * Migration of a running job costs state_GB / bandwidth seconds without progress. Implemented as a
    cost function; no scheduler in E018/E020 migrates jobs.
"""
from __future__ import annotations


def comm_factor(n_nodes: int, n_racks: int, c_node: float = 0.10, c_rack: float = 0.10) -> float:
    f = 1.0
    if n_nodes > 1:
        f *= 1.0 - c_node
    if n_racks > 1:
        f *= 1.0 - c_rack
    return f


def uplink_factor(n_cross_jobs_on_rack: int, uplink_jobs: int) -> float:
    return 1.0 if n_cross_jobs_on_rack <= uplink_jobs else uplink_jobs / n_cross_jobs_on_rack


def migration_cost_s(state_GB: float, bandwidth_GBps: float = 10.0, fixed_s: float = 5.0) -> float:
    if bandwidth_GBps <= 0:
        raise ValueError("bandwidth must be positive")
    return fixed_s + state_GB / bandwidth_GBps
