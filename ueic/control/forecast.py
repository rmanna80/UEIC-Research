"""Demand and ambient forecasts for predictive control (Stage 3).

Demand is in nominal work-seconds per second per job class (compute, memory), the unit the twin
uses. Three forecasters, selected by ``mpc_forecast_mode``:

  0 persistence   D_k = D_est (the controller's EWMA of recent arrivals) for every future step;
                  ambient held at its current value. Needs no knowledge of the future.
  1 scenario      the scenario's offered-load function (including scheduled bursts), with optional
                  multiplicative bias b and i.i.d. lognormal noise of log-sd sigma per step:
                      D_k = L(t + (k + 1/2) dt) * N * [1 - f_mem, f_mem] * w * (1 + b) * exp(sigma z_k - sigma^2/2)
                  where w is the work per task (cascade) and z_k ~ N(0, 1), drawn from a generator
                  seeded by (seed, decision index) so runs are reproducible. Ambient follows the
                  scenario's profile.
  2 no-bursts     as 1, but bursts are invisible to the forecast (an incorrect forecast).

Forecast error here is synthetic: it represents forecast quality levels for E015, not any real
forecasting model's skill.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from ..workload import Scenario, ambient, offered_load


class PersistenceForecaster:
    name = "persistence"

    def demand(self, obs, H: int, dt: float, cfg) -> np.ndarray:
        return np.tile(np.maximum(np.asarray(obs.D_est, dtype=float), 0.0), (H, 1))

    def ambient(self, obs, H: int, dt: float) -> np.ndarray:
        return np.full(H, float(obs.T_amb))


class ScenarioForecaster:
    def __init__(self, sc: Scenario, seed: int, bias: float = 0.0, noise: float = 0.0, see_bursts: bool = True):
        if bias <= -1.0 or noise < 0:
            raise ValueError("need bias > -1 and noise >= 0")
        self.sc = sc if see_bursts else replace(sc, bursts=())
        self.amb_sc = sc
        self.seed, self.bias, self.noise = int(seed), float(bias), float(noise)
        self.name = "scenario" if see_bursts else "no_bursts"
        self._k = 0

    def demand(self, obs, H: int, dt: float, cfg) -> np.ndarray:
        t = obs.t + (np.arange(H) + 0.5) * dt
        load = offered_load(t, self.sc)
        work = (cfg.small_cost_ratio + cfg.verify_cost_ratio) if self.sc.routing else 1.0
        D = load[:, None] * cfg.n_accel * np.array([1.0 - cfg.frac_memory, cfg.frac_memory])[None, :] * work
        D = D * (1.0 + self.bias)
        if self.noise > 0:
            rng = np.random.default_rng([self.seed, self._k, 7919])
            D = D * np.exp(self.noise * rng.standard_normal((H, 1)) - 0.5 * self.noise ** 2)
        self._k += 1
        return np.maximum(D, 0.0)

    def ambient(self, obs, H: int, dt: float) -> np.ndarray:
        t = obs.t + (np.arange(H) + 0.5) * dt
        return np.array([ambient(x, self.amb_sc) for x in t])


def make_forecaster(cfg, sc: Scenario | None, seed: int):
    mode = int(cfg.mpc_forecast_mode)
    if mode == 0 or sc is None:
        return PersistenceForecaster()
    return ScenarioForecaster(sc, seed, bias=float(cfg.mpc_forecast_bias), noise=float(cfg.mpc_forecast_noise),
                              see_bursts=(mode == 1))
