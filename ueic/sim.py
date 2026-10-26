"""Time-stepped cluster + cooling-loop simulator.

Boundary of the energy accounting (document this with every result):
  grid electricity -> power conversion -> accelerators (IT)
                   -> coolant pump, heat-rejection fans, trim chiller
Not modelled: room air handling for conversion losses, lighting, networking gear,
host CPUs, storage, building loads, loop thermal mass, plant setpoint dynamics.

Conservation identity checked on every run (and in tests):
  E_grid = E_rejected_to_ambient + E_conversion_loss + dU_chips + dU_loop
where dU_loop (<= 0) books transient heat flow from coolant into chips that the
quasi-steady loop (no thermal mass) cannot otherwise represent.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

import numpy as np

from . import physics as ph
from .policies import Action, Observation, Policy
from .workload import Scenario, Workload, generate, offered_load

PROV_SIM = "simulator_output"
PROV_MEAS = "physical_measurement"


@dataclass
class SimResult:
    metrics: dict[str, tuple[float, str, str]]          # name -> (value, unit, provenance)
    timeseries: dict[str, list[float]]
    warnings: list[str] = field(default_factory=list)
    latencies: np.ndarray | None = None

    def m(self, name: str) -> float:
        return self.metrics[name][0]


def simulate(cfg, scenario: Scenario, policy: Policy, seed: int, workload: Workload | None = None,
             record_timeseries: bool = True, initial_T: float = 35.0) -> SimResult:
    wall0 = perf_counter()
    wl = workload if workload is not None else generate(cfg, scenario, seed)
    N, dt = int(cfg.n_accel), float(cfg.dt)
    beta = np.array([cfg.beta_compute, cfg.beta_memory])
    act = np.array([1.0, cfg.activity_memory])
    routing = scenario.routing
    rs_rv = cfg.small_cost_ratio + cfg.verify_cost_ratio
    T_amb = float(scenario.t_amb)
    C = float(cfg.c_th)
    warnings: list[str] = []

    # ---- chip state
    T = np.full(N, initial_T, dtype=float)
    U0 = C * T.sum()
    busy = np.zeros(N, dtype=bool)
    rem = np.zeros(N)                 # remaining nominal work of the current stage
    ccls = np.zeros(N, dtype=np.int8)
    ctask = np.full(N, -1, dtype=np.int64)
    cstage = np.zeros(N, dtype=np.int8)
    throttled = np.zeros(N, dtype=bool)

    # ---- task state
    n = wl.n
    done_t = np.full(n, np.nan)
    success = np.zeros(n, dtype=bool)
    escalated = np.zeros(n, dtype=bool)
    queue: deque[tuple[int, int, float]] = deque()   # (task, stage, work)
    q_work = np.zeros(2)
    next_arr = 0
    work_enqueued = 0.0
    work_done = 0.0

    # ---- controller state
    ci = float(cfg.control_interval)
    alpha = 1.0 - np.exp(-ci / cfg.demand_window)
    D_est = np.zeros(2)
    arrived_int = np.zeros(2)
    k_window = max(1, int(round(cfg.demand_window / ci)))
    peak_hist: deque[float] = deque(maxlen=k_window)
    p_peak_int = 0.0
    q_int = 0.0
    p_design_peak = float(ph.chip_power(1.0, cfg.t_leak_ref, 1.0, cfg))
    q_last = float(N * ph.idle_power(initial_T, cfg))
    action: Action | None = None
    next_ctrl = 0.0
    notes: dict[str, int] = {}

    # ---- accumulators (J)
    E = dict(it=0.0, conv=0.0, pump=0.0, fan=0.0, ch=0.0, q_dc=0.0, q_ch=0.0, q_amb=0.0,
             q_cool=0.0, exergy=0.0, reusable=0.0, loop=0.0)
    t_over_target = 0.0
    t_throttled = 0.0
    peak_T = float(T.max())
    busy_time = np.zeros(2)

    ts: dict[str, list[float]] = {k: [] for k in (
        "t", "P_grid", "P_it", "P_pump", "P_fan", "W_ch", "T_sup", "flow", "T_ret", "T_max", "T_mean",
        "queue", "busy", "s_c", "s_m", "throttled", "util_offered")}
    acc = dict(P_grid=0.0, P_it=0.0, P_pump=0.0, P_fan=0.0, W_ch=0.0, T_ret=0.0, T_mean=0.0, busy=0.0, n=0)
    acc_Tmax = -np.inf
    acc_throttled = 0
    next_log = cfg.log_interval

    t = 0.0
    t_end_arrivals = scenario.duration_s
    t_hard_stop = scenario.duration_s + cfg.drain_max_s
    steps = 0
    while True:
        # ---------------- control
        if t >= next_ctrl - 1e-9:
            if t > 0:
                D_est = alpha * (arrived_int / ci) + (1 - alpha) * D_est
                peak_hist.append(p_peak_int)
                q_last = q_int / ci
            obs = Observation(
                t=t, D_est=D_est.copy(), backlog=q_work.copy(), T_amb=T_amb,
                p_chip_peak=max(peak_hist) if peak_hist else p_design_peak,
                q_chips=q_last, T_j=T.copy())
            action = policy.decide(obs)
            notes[action.note] = notes.get(action.note, 0) + 1
            arrived_int[:] = 0.0
            p_peak_int = 0.0
            q_int = 0.0
            next_ctrl += ci
        assert action is not None
        s_cls = np.array(action.s, dtype=float)
        T_sup = float(np.clip(action.t_sup, cfg.t_sup_min, cfg.t_sup_max))
        flow = float(np.clip(action.flow, cfg.flow_min_factor, cfg.flow_max_factor))

        # ---------------- arrivals (released at the start of the step they arrive in)
        while next_arr < n and wl.arrival[next_arr] <= t:
            w = wl.work[next_arr] * (rs_rv if routing else 1.0)
            c = int(wl.cls[next_arr])
            queue.append((next_arr, 0, w))
            q_work[c] += w
            arrived_int[c] += w
            work_enqueued += w
            next_arr += 1

        # ---------------- dispatch (FCFS; escalations are pushed to the front)
        if queue:
            for i in np.flatnonzero(~busy):
                if not queue:
                    break
                k, stage, w = queue.popleft()
                c = int(wl.cls[k])
                q_work[c] -= w
                busy[i], rem[i], ccls[i], ctask[i], cstage[i] = True, w, c, k, stage

        # ---------------- execution
        s = np.where(busy, s_cls[ccls], cfg.s_min)
        s = np.where(throttled, cfg.s_min, s)
        rate = s ** beta[ccls]
        need = np.where(busy, rem / rate, 0.0)
        bfrac = np.where(busy, np.minimum(1.0, need / dt), 0.0)
        P_busy = ph.chip_power(s, T, act[ccls], cfg, busy=True)
        P_idle = ph.idle_power(T, cfg)
        P = bfrac * P_busy + (1.0 - bfrac) * P_idle
        prog = np.minimum(rem, rate * dt) * busy
        rem = rem - prog
        work_done += prog.sum()
        for c in (0, 1):
            busy_time[c] += float((bfrac * dt * (ccls == c) * busy).sum())

        # ---------------- thermal
        R = float(ph.r_total(flow, cfg))
        T_new, Qj = ph.thermal_step(T, P, T_sup, R, C, dt)
        q_rate = float(Qj.sum()) / dt
        T = T_new
        peak_T = max(peak_T, float(T.max()))
        t_over_target += float((T > cfg.t_target).sum()) * dt
        throttled = np.where(T > cfg.t_throttle, True, np.where(T < cfg.t_throttle - cfg.throttle_hyst, False, throttled))
        t_throttled += float(throttled.sum()) * dt

        # ---------------- completions
        fin = busy & (need <= dt + 1e-12)
        for i in np.flatnonzero(fin):
            k, stage = int(ctask[i]), int(cstage[i])
            t_fin = t + float(need[i])
            if routing and stage == 0:
                p_s = cfg.p_small_easy if wl.easy[k] else cfg.p_small_hard
                ok_small = wl.u_small[k] < p_s
                accept = (wl.u_verify[k] >= cfg.verifier_false_reject) if ok_small else (wl.u_verify[k] < cfg.verifier_false_accept)
                if accept:
                    done_t[k], success[k] = t_fin, ok_small
                else:
                    escalated[k] = True
                    w = float(wl.work[k])
                    c = int(wl.cls[k])
                    queue.appendleft((k, 1, w))
                    q_work[c] += w
                    arrived_int[c] += w
                    work_enqueued += w
            else:
                done_t[k], success[k] = t_fin, wl.u_large[k] < cfg.p_large
            busy[i], rem[i], ctask[i] = False, 0.0, -1

        # ---------------- plant + electrical
        P_it = float(P.sum())
        P_pump = float(ph.pump_power(flow, cfg))
        pl = ph.plant(q_rate + P_pump, T_sup, flow, T_amb, cfg)
        W_ch, P_fan = float(pl["W_ch"]), float(pl["P_fan"])
        P_conv = P_it * (1.0 / cfg.eta_conv - 1.0)
        P_grid = P_it + P_conv + P_pump + P_fan + W_ch
        T_ret = float(pl["T_ret"])
        E["it"] += P_it * dt
        E["conv"] += P_conv * dt
        E["pump"] += P_pump * dt
        E["fan"] += P_fan * dt
        E["ch"] += W_ch * dt
        E["q_dc"] += float(pl["Q_dc"]) * dt
        E["q_ch"] += float(pl["Q_ch"]) * dt
        E["q_amb"] += float(pl["Q_amb"]) * dt
        E["q_cool"] += q_rate * dt
        E["loop"] += float(pl["Q_loop_storage"]) * dt
        ex = float(ph.stream_exergy_rate(pl["Cdot"], T_ret, T_sup, T_amb))
        E["exergy"] += ex * dt
        if T_ret >= cfg.t_reuse_min:
            E["reusable"] += (q_rate + P_pump) * dt
        p_peak_int = max(p_peak_int, float(P_busy[busy].max()) if busy.any() else float(P.max()))
        q_int += q_rate * dt

        # ---------------- logging
        if record_timeseries:
            acc["P_grid"] += P_grid; acc["P_it"] += P_it; acc["P_pump"] += P_pump; acc["P_fan"] += P_fan
            acc["W_ch"] += W_ch; acc["T_ret"] += T_ret; acc["T_mean"] += float(T.mean()); acc["busy"] += float(busy.sum())
            acc["n"] += 1
            acc_Tmax = max(acc_Tmax, float(T.max()))
            acc_throttled = max(acc_throttled, int(throttled.sum()))
        t += dt
        steps += 1
        if record_timeseries and t >= next_log - 1e-9:
            k_ = max(acc["n"], 1)
            ts["t"].append(t)
            for key in ("P_grid", "P_it", "P_pump", "P_fan", "W_ch", "T_ret", "T_mean", "busy"):
                ts[key].append(acc[key] / k_)
            ts["T_sup"].append(T_sup); ts["flow"].append(flow); ts["T_max"].append(acc_Tmax)
            ts["queue"].append(len(queue)); ts["s_c"].append(float(s_cls[0])); ts["s_m"].append(float(s_cls[1]))
            ts["throttled"].append(acc_throttled)
            ts["util_offered"].append(float(offered_load(t, scenario)) if t <= scenario.duration_s else 0.0)
            acc = dict.fromkeys(acc, 0.0); acc["n"] = 0
            acc_Tmax, acc_throttled = -np.inf, 0
            next_log += cfg.log_interval

        if next_arr >= n and not queue and not busy.any() and t >= t_end_arrivals:
            break
        if t >= t_hard_stop:
            warnings.append(f"hard stop at t={t:.0f}s with {len(queue)} queued and {int(busy.sum())} running stages")
            break

    # ---------------- metrics
    dU = C * T.sum() - U0
    E_grid = E["it"] + E["conv"] + E["pump"] + E["fan"] + E["ch"]
    balance_resid = E_grid - (E["q_amb"] + E["conv"] + dU + E["loop"])
    rel_resid = abs(balance_resid) / max(E_grid, 1e-9)
    if rel_resid > 1e-9:
        warnings.append(f"energy balance residual {rel_resid:.2e}")

    completed = ~np.isnan(done_t)
    lat = done_t[completed] - wl.arrival[completed]
    on_time = np.zeros(n, dtype=bool)
    on_time[completed] = lat <= wl.slo[completed]
    good = success & on_time & completed
    n_good = int(good.sum())
    J = 1.0 / 3.6e6
    sim_wall = perf_counter() - wall0
    dec = np.array(policy.decision_wall_s) if policy.decision_wall_s else np.zeros(1)
    S = PROV_SIM
    metrics: dict[str, tuple[float, str, str]] = {
        "E_grid_kWh": (E_grid * J, "kWh", S),
        "E_it_kWh": (E["it"] * J, "kWh", S),
        "E_conv_loss_kWh": (E["conv"] * J, "kWh", S),
        "E_pump_kWh": (E["pump"] * J, "kWh", S),
        "E_fan_kWh": (E["fan"] * J, "kWh", S),
        "E_chiller_kWh": (E["ch"] * J, "kWh", S),
        "E_cooling_kWh": ((E["pump"] + E["fan"] + E["ch"]) * J, "kWh", S),
        "Q_free_cooling_kWh": (E["q_dc"] * J, "kWh", S),
        "Q_chiller_kWh": (E["q_ch"] * J, "kWh", S),
        "Q_rejected_kWh": (E["q_amb"] * J, "kWh", S),
        "Q_reusable_kWh": (E["reusable"] * J, "kWh", S),
        "Ex_rejected_kWh": (E["exergy"] * J, "kWh", S),
        "E_loop_storage_kWh": (E["loop"] * J, "kWh", S),
        "grid_to_it_ratio": (E_grid / max(E["it"], 1e-9), "-", S),
        "energy_balance_rel_residual": (rel_resid, "-", S),
        "tasks": (float(n), "count", S),
        "tasks_completed": (float(completed.sum()), "count", S),
        "tasks_correct": (float((success & completed).sum()), "count", S),
        "tasks_successful": (float(n_good), "count", S),
        "success_rate": (n_good / max(n, 1), "-", S),
        "slo_violations": (float((completed & ~on_time).sum() + (~completed).sum()), "count", S),
        "escalations": (float(escalated.sum()), "count", S),
        "E_per_success_kJ": (E_grid / 1e3 / max(n_good, 1), "kJ/task", S),
        "E_per_task_kJ": (E_grid / 1e3 / max(n, 1), "kJ/task", S),
        "work_done_s": (work_done, "nominal s", S),
        "work_enqueued_s": (work_enqueued, "nominal s", S),
        "latency_mean_s": (float(lat.mean()) if lat.size else np.nan, "s", S),
        "latency_p95_s": (float(np.percentile(lat, 95)) if lat.size else np.nan, "s", S),
        "peak_T_j_C": (peak_T, "degC", S),
        "chip_s_over_target": (t_over_target, "chip*s", S),
        "chip_s_throttled": (t_throttled, "chip*s", S),
        "sim_time_s": (t, "s", S),
        "busy_time_compute_s": (busy_time[0], "chip*s", S),
        "busy_time_memory_s": (busy_time[1], "chip*s", S),
        "controller_decisions": (float(len(policy.decision_wall_s)), "count", S),
        "controller_wall_mean_ms": (float(dec.mean() * 1e3), "ms", PROV_MEAS),
        "sim_wall_s": (sim_wall, "s", PROV_MEAS),
    }
    for note, cnt in notes.items():
        if "infeasible" in note or "capacity-limited" in note:
            warnings.append(f"controller note '{note}' x{cnt}")
    return SimResult(metrics, ts if record_timeseries else {}, warnings, lat)
