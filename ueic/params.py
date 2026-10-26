"""Parameter registry.

Every number the simulator uses lives here, with:
  value, unit, evidence class, source/rationale, and a sensitivity range.

Evidence classes (from the UEIC charter, section 3):
  A  established physical principle / property
  B  published experimental result
  C  published simulation result
  D  existing commercial capability
  E  engineering extrapolation
  F  unvalidated hypothesis (placeholder chosen for this study)
  G  new proposed design / configuration choice

Nothing in classes E/F is a measurement. Conclusions that depend on them are
conditional, which is why every E/F parameter carries a (low, high) range that
the sensitivity experiment (E002) sweeps.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Mapping


@dataclass(frozen=True)
class Param:
    name: str
    value: float
    unit: str
    evidence: str
    source: str
    low: float | None = None
    high: float | None = None
    group: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_P = Param
_REGISTRY: list[Param] = [
    # ---------------------------------------------------------------- physics
    _P("water_cp", 4180.0, "J/(kg*K)", "A",
       "Liquid water near 25 C. NIST WebBook (Shomate eq.) gives ~4.184 J/(g K) at 25 C and ~4.178 at 40-45 C; see reference_values.md", group="physics"),
    _P("water_rho", 997.0, "kg/m^3", "A",
       "Density of liquid water near 25 C", group="physics"),
    _P("k_boltzmann", 1.380649e-23, "J/K", "A",
       "SI exact value (NIST); see reference_values.md", group="physics"),

    # ------------------------------------------------------------ accelerator
    _P("n_accel", 8, "count", "G", "Size of simulated cluster (one 8-accelerator node)", group="accelerator"),
    _P("p_dyn_max", 480.0, "W", "F",
       "Dynamic power at s=1, V=Vmax, activity=1. Total ~620 W at s=1 and 60 C, comparable to the "
       "'up to 700 W' max TDP NVIDIA lists for H100 SXM (class D, reference_values.md). Not a model of any product", 300.0, 700.0, "accelerator"),
    _P("p_leak_ref", 90.0, "W", "F",
       "Leakage at t_leak_ref and Vmax, ~15% of total. Breen et al. 2011 (L26, simulation) put typical chip "
       "leakage near 10% with projections up to ~50%; the range brackets both", 30.0, 180.0, "accelerator"),
    _P("t_leak_ref", 60.0, "degC", "G", "Reference junction temperature for leakage", group="accelerator"),
    _P("kappa_leak", 0.020, "1/K", "E",
       "P_leak ~ exp(kappa*(T-Tref)); 0.02/K doubles every ~35 K. Form is an approximation: Price et al. 2015 "
       "(L28, measured on a K20 GPU) fit a T^2*exp(-b/T) law instead. Needs refitting on a current GPU (Phase 4)", 0.005, 0.040, "accelerator"),
    _P("p_static_other", 50.0, "W", "F",
       "Temperature-independent board power (memory, I/O, fans excluded)", 20.0, 100.0, "accelerator"),
    _P("idle_dyn_frac", 0.05, "-", "F",
       "Fraction of full dynamic power drawn when idle (clock tree etc.)", 0.0, 0.15, "accelerator"),
    _P("activity_memory", 0.70, "-", "F",
       "Relative switching activity of memory-bound work vs compute-bound work", 0.5, 1.0, "accelerator"),
    _P("s_min", 0.5, "-", "G", "Lowest normalized clock frequency available (f/fmax)", group="accelerator"),
    _P("v_min_ratio", 0.70, "-", "E",
       "Vmin/Vmax at s_min; voltage assumed linear in frequency between s_min and 1", 0.60, 0.85, "accelerator"),
    _P("beta_compute", 0.95, "-", "E",
       "Throughput ~ s**beta for compute-bound work (beta=1 is perfectly clock-bound)", 0.85, 1.0, "workload"),
    _P("beta_memory", 0.35, "-", "E",
       "Throughput ~ s**beta for memory-bound work. Maliakel et al. 2025 (L09, preprint) report LLM decode "
       "latency changing <1% across clock settings, i.e. beta near 0, which is BELOW this range; a lower value "
       "would make DVFS look even better", 0.15, 0.60, "workload"),

    # ------------------------------------------------------------- thermal
    _P("c_th", 300.0, "J/K", "F",
       "Lumped heat capacity of die + package + cold plate", 100.0, 1000.0, "thermal"),
    _P("r_cond", 0.035, "K/W", "F",
       "Conduction resistance junction -> wetted cold-plate surface (die, TIM, lid, base)", 0.020, 0.060, "thermal"),
    _P("r_conv_ref", 0.015, "K/W", "F",
       "Convective resistance at design flow. For scale: a measured direct-to-chip cold plate (heater rig, not a "
       "GPU) showed 7.6-10.4 mK/W total at ~1 kW (reference_values.md, class B)", 0.008, 0.030, "thermal"),
    _P("n_conv", 0.6, "-", "E",
       "R_conv ~ flow**(-n). ~0.8 for turbulent (Dittus-Boelter), lower for developing laminar flow", 0.33, 0.8, "thermal"),
    _P("t_target", 80.0, "degC", "G", "Junction temperature limit that controllers must respect", group="thermal"),
    _P("t_throttle", 85.0, "degC", "G",
       "Independent hardware protection trip point (throttles to s_min regardless of controller)", group="thermal"),
    _P("throttle_hyst", 3.0, "K", "G", "Throttle release hysteresis", group="thermal"),

    # ---------------------------------------------------------------- loop
    _P("flow_design_lpm", 1.2, "L/min per accelerator", "E",
       "Gives ~8 K coolant rise at ~650 W (Q = m_dot*cp*dT)", group="loop"),
    _P("flow_min_factor", 0.5, "-", "G", "Lowest allowed flow / design flow", group="loop"),
    _P("flow_max_factor", 2.0, "-", "G", "Highest allowed flow / design flow", group="loop"),
    _P("dp_ref", 150e3, "Pa", "F", "Loop pressure drop at design flow", 50e3, 300e3, "loop"),
    _P("m_dp", 1.8, "-", "E",
       "dP ~ flow**m. m=1 laminar (Hagen-Poiseuille), ~1.75-2 turbulent (Darcy-Weisbach)", 1.0, 2.0, "loop"),
    _P("eta_pump", 0.5, "-", "F", "Pump wire-to-water efficiency", 0.3, 0.7, "loop"),
    _P("t_sup_min", 12.0, "degC", "G", "Lowest supply temperature the plant can deliver", group="loop"),
    _P("t_sup_max", 45.0, "degC", "G", "Highest supply temperature allowed; ASHRAE class W45 upper supply limit (reference_values.md)", group="loop"),

    # --------------------------------------------------------------- plant
    _P("eta_ii_chiller", 0.50, "-", "E",
       "Chiller second-law efficiency: COP = eta_II * COP_Carnot", 0.30, 0.65, "plant"),
    _P("dt_evap", 3.0, "K", "F", "Evaporator approach (T_evap = T_sup - dt_evap)", 1.0, 6.0, "plant"),
    _P("dt_cond", 8.0, "K", "F", "Condenser approach (T_cond = T_amb + dt_cond)", 4.0, 15.0, "plant"),
    _P("dt_drycooler", 5.0, "K", "F", "Dry-cooler approach to ambient", 3.0, 10.0, "plant"),
    _P("fan_ratio", 0.02, "W/W", "F", "Heat-rejection fan power per W of heat rejected to ambient", 0.005, 0.05, "plant"),
    _P("cop_max", 20.0, "-", "G", "Numerical cap on chiller COP when lift approaches zero", group="plant"),
    _P("eta_conv", 0.94, "-", "F", "Grid-to-chip power conversion efficiency (UPS, PSU, VRs)", 0.88, 0.97, "plant"),
    _P("t_reuse_min", 45.0, "degC", "F", "Return temperature needed for heat to count as reusable", 35.0, 60.0, "plant"),

    # ------------------------------------------------------------ workload
    _P("job_work_mean", 20.0, "s", "F", "Mean job size in seconds at s=1 (lognormal)", 5.0, 120.0, "workload"),
    _P("job_work_sigma", 0.6, "-", "F", "Lognormal sigma of job size", 0.2, 1.2, "workload"),
    _P("frac_memory", 0.40, "-", "F", "Fraction of jobs that are memory-bound", 0.1, 0.8, "workload"),
    _P("slo_base", 30.0, "s", "G", "Latency SLO = slo_base + slo_factor * nominal work", group="workload"),
    _P("slo_factor", 5.0, "-", "G", "Latency SLO multiplier on nominal work", group="workload"),
    _P("u_max", 0.85, "-", "G", "Max planned utilization (queueing headroom) for optimizing controllers", group="workload"),

    # ------------------------------------------------------------- routing (all hypothetical)
    _P("frac_easy", 0.60, "-", "F", "Fraction of tasks a small model can handle", 0.2, 0.9, "routing"),
    _P("small_cost_ratio", 0.20, "-", "F", "Small-model work / large-model work", 0.05, 0.5, "routing"),
    _P("verify_cost_ratio", 0.05, "-", "F", "Verifier work / large-model work", 0.0, 0.2, "routing"),
    _P("p_small_easy", 0.92, "-", "F", "Small-model success probability on easy tasks", 0.6, 0.99, "routing"),
    _P("p_small_hard", 0.30, "-", "F", "Small-model success probability on hard tasks", 0.0, 0.6, "routing"),
    _P("p_large", 0.97, "-", "F", "Large-model success probability", 0.8, 0.995, "routing"),
    _P("verifier_false_accept", 0.0, "-", "F", "P(verifier accepts a wrong small-model answer)", 0.0, 0.2, "routing"),
    _P("verifier_false_reject", 0.0, "-", "F", "P(verifier rejects a correct small-model answer)", 0.0, 0.2, "routing"),

    # ----------------------------------------------------- loop dynamics (Phase 3)
    _P("loop_mass_kg", 0.0, "kg water", "G",
       "0 selects the quasi-steady plant of E001-E005 (no loop thermal mass). E006 uses 40 kg and 150 kg; "
       "those values are placeholders (class F) for a CDU tank + piping, not measurements", group="loop"),
    _P("warm_start", 0.0, "0/1", "G",
       "1 = controllers start with the demand estimate and chip-heat estimate of the initial offered load, as if "
       "the system had been running, so each policy starts in its own steady state. 0 = cold start with zero "
       "demand estimate (E001-E005, E006 v1). Needed with a loop thermal mass: in E006 v1 a cold start let the "
       "first (zero-demand) decision set the initial tank temperature, a confound found in analysis", group="loop"),
    _P("tsup_ramp_K_per_min", 0.0, "K/min", "G",
       "Max rate at which the plant can move its outlet temperature. 0 = instantaneous (E001-E005). "
       "E006 uses 1.0 and 0.25 (class F placeholders)", group="loop"),

    # ------------------------------------------------------------- policies
    _P("fixed_t_sup", 18.0, "degC", "G",
       "Supply temperature of the fixed (conventional) baseline; within ASHRAE W17/W27-class supply ranges", 12.0, 27.0, "policy"),
    _P("fixed_flow", 1.0, "x design", "G", "Flow factor of the fixed baseline policy", group="policy"),
    _P("t_assume_compute", 65.0, "degC", "G",
       "Junction temperature a compute-only controller (no thermal model) assumes", group="policy"),
    _P("t_sup_step", 1.0, "K", "G", "Supply-temperature grid resolution for optimizing controllers", group="policy"),
    _P("joint_switch_rel", 0.0, "-", "G",
       "Move suppression: the joint controller keeps its previous action unless the new optimum is predicted "
       "to use this fraction less grid power (0 = always switch, as in E001-E005)", group="policy"),
    _P("joint_bias_gain", 0.5, "-", "G",
       "EWMA gain of the joint_robust controller's temperature-bias estimate (measured minus predicted peak "
       "junction temperature, clipped at 0); used only by joint_robust", group="policy"),

    # --------------------------------------------------------- simulation
    _P("dt", 1.0, "s", "G", "Simulation time step", group="simulation"),
    _P("control_interval", 60.0, "s", "G", "Controller decision period", group="simulation"),
    _P("log_interval", 60.0, "s", "G", "Time-series logging period", group="simulation"),
    _P("demand_window", 300.0, "s", "G", "Window for demand estimation (EWMA time constant)", group="simulation"),
    _P("backlog_clear_s", 120.0, "s", "G", "Controllers plan to clear current backlog within this time", group="simulation"),
    _P("drain_max_s", 3600.0, "s", "G", "Max time after last arrival to finish queued work", group="simulation"),
]

REGISTRY: dict[str, Param] = {p.name: p for p in _REGISTRY}


class Config(dict):
    """Read-only attribute view over parameter values (plus scenario fields)."""

    def __getattr__(self, k: str) -> Any:
        try:
            return self[k]
        except KeyError as e:  # pragma: no cover - programming error
            raise AttributeError(k) from e

    def __setitem__(self, k, v):  # pragma: no cover
        raise TypeError("Config is read-only; build a new one with make_config()")


def make_config(overrides: Mapping[str, Any] | None = None) -> Config:
    vals: dict[str, Any] = {k: p.value for k, p in REGISTRY.items()}
    for k, v in (overrides or {}).items():
        if k not in REGISTRY and not k.startswith("scn_"):
            raise KeyError(f"Unknown parameter '{k}'. Add it to the registry with provenance first.")
        vals[k] = v
    cfg = Config()
    dict.update(cfg, vals)
    validate(cfg)
    return cfg


def validate(cfg: Mapping[str, Any]) -> None:
    """Input validation: reject physically meaningless configurations early."""
    pos = ["water_cp", "water_rho", "p_dyn_max", "c_th", "r_cond", "r_conv_ref", "dp_ref", "dt",
           "control_interval", "job_work_mean", "flow_design_lpm"]
    for k in pos:
        if not cfg[k] > 0:
            raise ValueError(f"{k} must be > 0 (got {cfg[k]})")
    frac = ["idle_dyn_frac", "activity_memory", "frac_memory", "frac_easy", "p_small_easy", "p_small_hard",
            "p_large", "verifier_false_accept", "verifier_false_reject", "u_max", "eta_pump",
            "eta_ii_chiller", "eta_conv"]
    for k in frac:
        if not 0.0 <= cfg[k] <= 1.0:
            raise ValueError(f"{k} must be in [0,1] (got {cfg[k]})")
    if not 0 < cfg["s_min"] < 1:
        raise ValueError("s_min must be in (0,1)")
    if not cfg["t_target"] < cfg["t_throttle"]:
        raise ValueError("t_target must be below t_throttle")
    if not cfg["t_sup_min"] < cfg["t_sup_max"]:
        raise ValueError("t_sup_min must be below t_sup_max")
    if cfg["dt"] > cfg["control_interval"]:
        raise ValueError("dt must not exceed control_interval")
    for k in ("loop_mass_kg", "tsup_ramp_K_per_min", "joint_switch_rel"):
        if cfg[k] < 0:
            raise ValueError(f"{k} must be >= 0")
    if cfg["warm_start"] not in (0, 0.0, 1, 1.0):
        raise ValueError("warm_start must be 0 or 1")
    if not 0.0 <= cfg["joint_bias_gain"] <= 1.0:
        raise ValueError("joint_bias_gain must be in [0,1]")


def assumptions_table() -> list[dict[str, Any]]:
    return [p.to_dict() for p in _REGISTRY]
