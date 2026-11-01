"""Multi-node facility simulator (Stage 6): discrete jobs on heterogeneous accelerators sharing one
coolant plant, with rack/facility power caps, unequal flow distribution, series cold plates and
communication costs. Simulation only; every quantity is synthetic.

Per step dt (all GPUs vectorised):
  1. arrivals -> queue; if the queue is non-empty and GPUs are free, the scheduler places jobs (EDF order,
     backfilling) and may request a clock s_req per job.
  2. clocks: s = min(s_req, s_thr) on busy GPUs (s_min when idle); the power-capping layer then scales
     clocks per rack and facility (``power_network.cap_group``). Schedulers cannot bypass either layer.
  3. chip power P = p_dyn a s v(s)^2 + p_static + p_leak v e^(kappa (T - T_ref)) (registry forms, scaled
     per accelerator type); a = activity of the job's class, idle GPUs at s_min with idle activity.
  4. coolant: branch flows from the manifold (``cooling_network.distribute``); plate flow factor
     f = (q_n / branches) / flow_design; R = r_cond + r_conv(f) + r_caloric(f); inlet of a plate =
     supply + heat of the plates upstream in its branch (previous step) / (m_dot c_p).
  5. junction: exact first-order step (``physics.thermal_step``); energy is conserved by construction and
     the balance is reported (``energy_balance_rel``).
  6. hardware throttle (independent): above t_throttle s_thr falls 0.05/s to s_min; below
     t_throttle - throttle_hyst it recovers 0.02/s.
  7. job progress: rate = min over its GPUs of speed s^beta, times communication factors.
  8. plant: G / n_accel identical plant modules (each the registry's per-node plant) reject the coolant
     heat (chips + pump) at the supply temperature; instant supply (plant lag is not modelled here; E015
     covers it on one node).
Facility controller (every ``control_interval_s``): supply "fixed" or "warmest_safe" (highest supply,
in 0.5 K steps, at which every busy GPU's steady junction at its current power, inlet rise and R stays
<= t_target - margin; measured state, nothing credited in advance); valves "equal" or "heat_proportional".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .. import physics as ph
from ..params import make_config
from . import cooling_network as cn
from . import networking as net
from .cluster import Cluster
from .jobs import Job
from .power_network import cap_group


@dataclass
class FacilityConfig:
    dt: float = 2.0
    duration_s: float = 7200.0
    drain_s: float = 1800.0
    T_amb: float = 20.0
    supply: str = "fixed"            # fixed | warmest_safe
    T_set: float = 30.0
    supply_margin_K: float = 3.0
    valves: str = "equal"            # equal | heat_proportional
    pump_flow_factor: float = 1.0
    control_interval_s: float = 30.0
    c_node: float = 0.10
    c_rack: float = 0.10
    record_every_s: float = 30.0


class FacilityView:
    """Read-only snapshot handed to schedulers (arrays are copies)."""

    def __init__(self, sim: "FacilitySim"):
        self._sim = sim
        self.T, self.T_in, self.R, self.C, self.P = (x.copy() for x in (sim.T, sim.T_in, sim.R, sim.C, sim.P))
        self.busy = sim.job_of >= 0
        self.mem, self.node, self.rack, self.speed = sim.mem, sim.node_of, sim.rack_of, sim.speed
        self.t_target, self.t_throttle, self.s_min = sim.cfg.t_target, sim.cfg.t_throttle, sim.cfg.s_min
        self.rack_limits, self.n_racks = sim.rack_limits, sim.n_racks
        self.cfg = sim.cfg

    def downstream(self, g: int) -> list[int]:
        return self._sim.downstream[g]

    def cdot(self, g: int) -> float:
        return float(self._sim.cdot[g])

    def eligible(self, job: Job) -> np.ndarray:
        return (~self.busy) & (self.mem >= job.mem_GB)

    def job_power(self, gpus, job: Job, s: float) -> np.ndarray:
        g = np.asarray(gpus)
        return self._sim.power_at(g, np.full(g.size, s), self.T[g], job.memory_bound, True)

    def rack_power(self) -> np.ndarray:
        return np.bincount(self.rack, weights=self.P, minlength=self.n_racks)


class FacilitySim:
    def __init__(self, cluster: Cluster, scheduler, jobs: list[Job], fc: FacilityConfig | None = None,
                 param_overrides: dict | None = None):
        self.cl, self.sched, self.fc = cluster, scheduler, fc or FacilityConfig()
        self.cfg = make_config(param_overrides or {})
        cfg = self.cfg
        rack_idx = {r.name: i for i, r in enumerate(cluster.racks)}
        self.n_racks = len(cluster.racks)
        self.rack_limits = np.array([r.power_limit_W or np.inf for r in cluster.racks])
        self.uplink = np.array([r.uplink_jobs for r in cluster.racks])
        cols: dict[str, list] = {k: [] for k in ("node", "rack", "pos", "prev", "pdyn", "stat", "speed", "mem", "C", "rcond")}
        for nd in cluster.nodes:
            base = len(cols["node"])
            for j, tn in enumerate(nd.gpus):
                ty = cluster.types[tn]
                pos = j % nd.chain
                cols["node"].append(nd.index); cols["rack"].append(rack_idx[nd.rack]); cols["pos"].append(pos)
                cols["prev"].append(base + j - 1 if pos > 0 else -1)
                cols["pdyn"].append(cfg.p_dyn_max * ty.p_dyn_scale); cols["stat"].append(ty.static_scale)
                cols["speed"].append(ty.speed); cols["mem"].append(ty.mem_GB)
                cols["C"].append(cfg.c_th * ty.c_th_scale); cols["rcond"].append(cfg.r_cond * ty.r_cond_scale)
        a = {k: np.array(v) for k, v in cols.items()}
        self.node_of, self.rack_of, self.pos, self.prev = a["node"], a["rack"], a["pos"], a["prev"]
        self.pdyn, self.stat, self.speed, self.mem, self.C, self.rcond = (a[k].astype(float) for k in
                                                                           ("pdyn", "stat", "speed", "mem", "C", "rcond"))
        self.G = self.node_of.size
        self.downstream = [[] for _ in range(self.G)]
        for g in range(self.G):
            p = self.prev[g]
            while p >= 0:
                self.downstream[p].append(g)
                p = self.prev[p]
        self.n_branches = np.array([nd.n_branches for nd in cluster.nodes], dtype=float)
        self.q_design = np.array([nd.n_branches * cfg.flow_design_lpm for nd in cluster.nodes])
        self.h = np.array([nd.hydraulic_scale for nd in cluster.nodes])
        self.valve = np.ones(len(cluster.nodes))
        self.n_mod = self.G / cfg.n_accel
        self.jobs = sorted(jobs, key=lambda j: j.arrival)
        self.t = 0.0
        self.T_sup = float(self.fc.T_set if self.fc.supply == "fixed" else cfg.t_sup_min)
        self.T = np.full(self.G, self.T_sup + 5.0)
        self.T_in = np.full(self.G, self.T_sup)
        self.Qrate = np.zeros(self.G)
        self.P = np.zeros(self.G)
        self.R = np.full(self.G, float(ph.r_total(1.0, cfg)))
        self.cdot = np.ones(self.G)
        self.s_thr = np.ones(self.G)
        self.s_req = np.ones(self.G)
        self.s_eff = np.full(self.G, cfg.s_min)
        self.job_of = np.full(self.G, -1)
        self.mb = np.zeros(self.G, dtype=bool)

    # ------------------------------------------------------------------ physics helpers
    def power_at(self, g, s, T, memory_bound, busy) -> np.ndarray:
        cfg = self.cfg
        v = ph.voltage_ratio(s, cfg)
        act = np.where(busy, np.where(memory_bound, cfg.activity_memory, 1.0), cfg.idle_dyn_frac)
        return self.pdyn[g] * act * s * v ** 2 + self.stat[g] * (cfg.p_static_other + ph.leakage_power(T, v, cfg))

    def _hydraulics(self):
        cfg = self.cfg
        F = self.fc.pump_flow_factor * self.q_design.sum()
        q, dp = cn.distribute(F, self.q_design, self.h, self.valve, cfg.dp_ref)
        f_node = (q / self.n_branches) / cfg.flow_design_lpm
        f = f_node[self.node_of]
        self.R = self.rcond + ph.r_conv(f, cfg) + ph.r_caloric(f, cfg)
        self.cdot = ph.mass_flow_per_accel(f, cfg) * cfg.water_cp
        return F, dp, f_node

    def _inlets(self):
        self.T_in = np.full(self.G, self.T_sup)
        for p in range(1, int(self.pos.max()) + 1):
            m = self.pos == p
            pr = self.prev[m]
            self.T_in[m] = self.T_in[pr] + self.Qrate[pr] / self.cdot[pr]

    # ------------------------------------------------------------------ control
    def _control(self):
        cfg, fc = self.cfg, self.fc
        if fc.valves == "heat_proportional":
            Qn = np.bincount(self.node_of, weights=self.Qrate, minlength=len(self.q_design))
            self.valve = cn.heat_proportional_valves(Qn, self.q_design, self.h)
        if fc.supply == "warmest_safe":
            busy = self.job_of >= 0
            if busy.any():
                rise = (self.T_in - self.T_sup)[busy]
                lim = cfg.t_target - fc.supply_margin_K - rise - self.R[busy] * self.P[busy]
                T = float(np.floor(lim.min() * 2) / 2)
            else:
                T = cfg.t_sup_max
            self.T_sup = float(np.clip(T, cfg.t_sup_min, cfg.t_sup_max))

    def _schedule(self):
        view = FacilityView(self)
        queue = sorted(self.queue, key=lambda j: (j.deadline, j.id))
        for job in queue:
            if not ((self.job_of < 0) & (self.mem >= job.mem_GB)).any():
                continue
            out = self.sched.select(job, view, self.t)
            if out is None:
                continue
            gpus, s = out
            gpus = np.asarray(gpus, dtype=int)
            if gpus.size != job.n_gpus or (self.job_of[gpus] >= 0).any() or (self.mem[gpus] < job.mem_GB).any():
                raise RuntimeError(f"scheduler {self.sched.name} returned an invalid placement for job {job.id}")
            job.gpus, job.s_req, job.start = list(gpus), float(s), self.t
            self.job_of[gpus] = job.id
            self.s_req[gpus] = s
            self.mb[gpus] = job.memory_bound
            self.queue.remove(job)
            self.running.append(job)
            view = FacilityView(self)

    # ------------------------------------------------------------------ main loop
    def run(self) -> dict[str, Any]:
        cfg, fc, dt = self.cfg, self.fc, self.fc.dt
        self.queue: list[Job] = []
        self.running: list[Job] = []
        done: list[Job] = []
        ia = 0
        acc = {k: 0.0 for k in ("E_it", "E_grid", "E_pump", "E_fan", "E_ch", "E_chip", "dU", "Q_cool", "work",
                                "throttle_gpu_s", "chip_s_over_target", "cap_steps", "busy_gpu_s", "T_sup_int")}
        T_max = -np.inf
        P_grid_max = 0.0
        ts: dict[str, list[float]] = {k: [] for k in ("t", "T_sup", "P_grid_kW", "T_max", "running", "queued")}
        F, dp, f_node = self._hydraulics()
        next_ctrl, next_rec = 0.0, 0.0
        t_end = fc.duration_s + fc.drain_s
        n_steps = int(round(t_end / dt))
        for _ in range(n_steps):
            while ia < len(self.jobs) and self.jobs[ia].arrival <= self.t:
                self.queue.append(self.jobs[ia]); ia += 1
            if self.t >= next_ctrl:
                self._control(); next_ctrl += fc.control_interval_s
                F, dp, f_node = self._hydraulics()
            self._inlets()
            if self.queue and (self.job_of < 0).any():
                self._schedule()
            busy = self.job_of >= 0
            s = np.where(busy, np.minimum(self.s_req, self.s_thr), cfg.s_min)
            pw = lambda idx: (lambda x: self.power_at(idx, x, self.T[idx], self.mb[idx], busy[idx]))   # noqa: E731
            for r in range(self.n_racks):
                if np.isfinite(self.rack_limits[r]):
                    idx = np.nonzero(self.rack_of == r)[0]
                    s[idx], hit = cap_group(s[idx], busy[idx], pw(idx), self.rack_limits[r], cfg.s_min)
                    acc["cap_steps"] += hit
            if self.cl.facility_power_limit_W:
                idx = np.arange(self.G)
                s, hit = cap_group(s, busy, pw(idx), self.cl.facility_power_limit_W, cfg.s_min)
                acc["cap_steps"] += hit
            self.s_eff = s
            self.P = self.power_at(np.arange(self.G), s, self.T, self.mb, busy)
            T_new, Q = ph.thermal_step(self.T, self.P, self.T_in, self.R, self.C, dt)
            acc["E_chip"] += self.P.sum() * dt; acc["dU"] += float((self.C * (T_new - self.T)).sum()); acc["Q_cool"] += Q.sum()
            self.T, self.Qrate = T_new, Q / dt
            hot = self.T > cfg.t_throttle
            cool = self.T < cfg.t_throttle - cfg.throttle_hyst
            self.s_thr = np.where(hot, np.maximum(cfg.s_min, self.s_thr - 0.05 * dt),
                                  np.where(cool, np.minimum(1.0, self.s_thr + 0.02 * dt), self.s_thr))
            acc["throttle_gpu_s"] += dt * float((self.s_thr < 1.0).sum())
            acc["chip_s_over_target"] += dt * float((self.T > cfg.t_target).sum())
            acc["busy_gpu_s"] += dt * float(busy.sum())
            T_max = max(T_max, float(self.T.max()))
            # job progress, with communication and uplink factors
            cross_on_rack = np.zeros(self.n_racks)
            spans = {}
            for j in self.running:
                nodes = set(self.node_of[j.gpus]); racks = set(self.rack_of[j.gpus])
                spans[j.id] = (len(nodes), racks)
                if len(nodes) > 1:
                    for r in racks:
                        cross_on_rack[r] += 1
            finished = []
            for j in self.running:
                g = np.asarray(j.gpus)
                beta = cfg.beta_memory if j.memory_bound else cfg.beta_compute
                rate = float((self.speed[g] * s[g] ** beta).min())
                nn, racks = spans[j.id]
                rate *= net.comm_factor(nn, len(racks), fc.c_node, fc.c_rack)
                if nn > 1:
                    rate *= min(net.uplink_factor(int(cross_on_rack[r]), int(self.uplink[r])) for r in racks)
                prog = min(j.remaining, rate * dt)
                j.remaining -= prog
                acc["work"] += prog * j.n_gpus
                if j.remaining <= 1e-9:
                    j.finish = self.t + dt
                    finished.append(j)
            for j in finished:
                self.running.remove(j); done.append(j)
                self.job_of[np.asarray(j.gpus)] = -1
                self.s_req[np.asarray(j.gpus)] = 1.0
            P_pump = cn.pump_power(F, dp, cfg.eta_pump)
            Q_tot = float(self.Qrate.sum()) + P_pump
            f_avg = F / self.q_design.sum()
            pl = ph.plant(Q_tot / self.n_mod, self.T_sup, f_avg, fc.T_amb, cfg)
            P_fan, W_ch = self.n_mod * float(pl["P_fan"]), self.n_mod * float(pl["W_ch"])
            P_it = float(self.P.sum())
            P_grid = P_it / cfg.eta_conv + P_pump + P_fan + W_ch
            for k, v in (("E_it", P_it), ("E_grid", P_grid), ("E_pump", P_pump), ("E_fan", P_fan), ("E_ch", W_ch),
                         ("T_sup_int", self.T_sup)):
                acc[k] += v * dt
            P_grid_max = max(P_grid_max, P_grid)
            if self.t >= next_rec:
                for k, v in (("t", self.t), ("T_sup", self.T_sup), ("P_grid_kW", P_grid / 1e3), ("T_max", float(self.T.max())),
                             ("running", len(self.running)), ("queued", len(self.queue))):
                    ts[k].append(float(v))
                next_rec += fc.record_every_s
            self.t += dt
        return self._metrics(done, acc, T_max, P_grid_max, t_end, ts)

    def _metrics(self, done, acc, T_max, P_grid_max, t_end, ts) -> dict[str, Any]:
        J = 1.0 / 3.6e6
        arrived = [j for j in self.jobs if j.arrival < self.fc.duration_s]
        on_time = [j for j in done if j.finish <= j.deadline]
        waits = [j.start - j.arrival for j in done]
        n_done = len(done)
        bal = (acc["E_chip"] - acc["dU"] - acc["Q_cool"]) / max(acc["E_chip"], 1e-9)
        m = {
            "jobs_arrived": float(len(arrived)), "jobs_completed": float(n_done), "jobs_on_time": float(len(on_time)),
            "on_time_frac": len(on_time) / max(len(arrived), 1), "jobs_unfinished": float(len(arrived) - n_done),
            "work_done_gpu_s": acc["work"], "mean_wait_s": float(np.mean(waits)) if waits else float("nan"),
            "p95_wait_s": float(np.percentile(waits, 95)) if waits else float("nan"),
            "E_grid_kWh": acc["E_grid"] * J, "E_it_kWh": acc["E_it"] * J, "E_pump_kWh": acc["E_pump"] * J,
            "E_fan_kWh": acc["E_fan"] * J, "E_chiller_kWh": acc["E_ch"] * J,
            "E_per_job_kJ": acc["E_grid"] / 1e3 / max(n_done, 1), "E_per_work_kJ": acc["E_grid"] / 1e3 / max(acc["work"], 1e-9),
            "E_per_on_time_job_kJ": acc["E_grid"] / 1e3 / max(len(on_time), 1),
            "chip_s_over_target": acc["chip_s_over_target"], "throttle_gpu_s": acc["throttle_gpu_s"],
            "T_max_C": T_max, "T_sup_mean_C": acc["T_sup_int"] / t_end, "cap_steps": acc["cap_steps"],
            "P_grid_peak_kW": P_grid_max / 1e3, "utilisation": acc["busy_gpu_s"] / (self.G * t_end),
            "energy_balance_rel": float(bal), "n_gpus": float(self.G),
        }
        return {"metrics": m, "timeseries": ts}
