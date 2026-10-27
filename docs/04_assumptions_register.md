# 04 · Assumptions register

Generated from `ueic/params.py` by `python -m ueic report`. Do not edit by hand.

Evidence classes: **A** established physical principle/property · **B** published experimental result · **C** published simulation · **D** commercial capability · **E** engineering extrapolation · **F** unvalidated placeholder chosen for this study · **G** design/configuration choice.

Classes E and F are *not measurements*. Every E/F value with a range is swept in E002.

| Group | Parameter | Value | Unit | Class | Sensitivity range | Source / rationale |
|---|---|---|---|---|---|---|
| accelerator | `activity_memory` | 0.7 | - | F | 0.5 – 1 | Relative switching activity of memory-bound work vs compute-bound work |
| accelerator | `idle_dyn_frac` | 0.05 | - | F | 0 – 0.15 | Fraction of full dynamic power drawn when idle (clock tree etc.) |
| accelerator | `kappa_leak` | 0.02 | 1/K | E | 0.005 – 0.04 | P_leak ~ exp(kappa*(T-Tref)); 0.02/K doubles every ~35 K. Form is an approximation: Price et al. 2015 (L28, measured on a K20 GPU) fit a T^2*exp(-b/T) law instead. Needs refitting on a current GPU (Phase 4) |
| accelerator | `n_accel` | 8 | count | G |  | Size of simulated cluster (one 8-accelerator node) |
| accelerator | `p_dyn_max` | 480 | W | F | 300 – 700 | Dynamic power at s=1, V=Vmax, activity=1. Total ~620 W at s=1 and 60 C, comparable to the 'up to 700 W' max TDP NVIDIA lists for H100 SXM (class D, reference_values.md). Not a model of any product |
| accelerator | `p_leak_ref` | 90 | W | F | 30 – 180 | Leakage at t_leak_ref and Vmax, ~15% of total. Breen et al. 2011 (L26, simulation) put typical chip leakage near 10% with projections up to ~50%; the range brackets both |
| accelerator | `p_static_other` | 50 | W | F | 20 – 100 | Temperature-independent board power (memory, I/O, fans excluded) |
| accelerator | `s_min` | 0.5 | - | G |  | Lowest normalized clock frequency available (f/fmax) |
| accelerator | `t_leak_ref` | 60 | degC | G |  | Reference junction temperature for leakage |
| accelerator | `v_min_ratio` | 0.7 | - | E | 0.6 – 0.85 | Vmin/Vmax at s_min; voltage assumed linear in frequency between s_min and 1 |
| accelerator | `vf_knee` | 0 | - | G |  | Voltage-floor form of the V-f curve (Phase 4): voltage stays at v_min_ratio up to clock ratio vf_knee, then rises linearly to 1 at s = 1. 0 = registry linear form from s_min (E001-E011). A value fitted to the RTX 5070's measured power-vs-clock shape is a shape transfer (class E), see docs/10 |
| loop | `dp_ref` | 150000 | Pa | F | 50000 – 300000 | Loop pressure drop at design flow |
| loop | `eta_pump` | 0.5 | - | F | 0.3 – 0.7 | Pump wire-to-water efficiency |
| loop | `flow_design_lpm` | 1.2 | L/min per accelerator | E |  | Gives ~8 K coolant rise at ~650 W (Q = m_dot*cp*dT) |
| loop | `flow_max_factor` | 2 | - | G |  | Highest allowed flow / design flow |
| loop | `flow_min_factor` | 0.5 | - | G |  | Lowest allowed flow / design flow |
| loop | `loop_mass_kg` | 0 | kg water | G |  | 0 selects the quasi-steady plant of E001-E005 (no loop thermal mass). E006 uses 40 kg and 150 kg; those values are placeholders (class F) for a CDU tank + piping, not measurements |
| loop | `m_dp` | 1.8 | - | E | 1 – 2 | dP ~ flow**m. m=1 laminar (Hagen-Poiseuille), ~1.75-2 turbulent (Darcy-Weisbach) |
| loop | `t_sup_max` | 45 | degC | G |  | Highest supply temperature allowed; ASHRAE class W45 upper supply limit (reference_values.md) |
| loop | `t_sup_min` | 12 | degC | G |  | Lowest supply temperature the plant can deliver |
| loop | `tsup_ramp_K_per_min` | 0 | K/min | G |  | Max rate at which the plant can move its outlet temperature. 0 = instantaneous (E001-E005). E006 uses 1.0 and 0.25 (class F placeholders) |
| loop | `warm_start` | 0 | 0/1 | G |  | 1 = controllers start with the demand estimate and chip-heat estimate of the initial offered load, as if the system had been running, so each policy starts in its own steady state. 0 = cold start with zero demand estimate (E001-E005, E006 v1). Needed with a loop thermal mass: in E006 v1 a cold start let the first (zero-demand) decision set the initial tank temperature, a confound found in analysis |
| physics | `k_boltzmann` | 1.38065e-23 | J/K | A |  | SI exact value (NIST); see reference_values.md |
| physics | `water_cp` | 4180 | J/(kg*K) | A |  | Liquid water near 25 C. NIST WebBook (Shomate eq.) gives ~4.184 J/(g K) at 25 C and ~4.178 at 40-45 C; see reference_values.md |
| physics | `water_rho` | 997 | kg/m^3 | A |  | Density of liquid water near 25 C |
| plant | `cop_max` | 20 | - | G |  | Numerical cap on chiller COP when lift approaches zero |
| plant | `dt_cond` | 8 | K | F | 4 – 15 | Condenser approach (T_cond = T_amb + dt_cond) |
| plant | `dt_drycooler` | 5 | K | F | 3 – 10 | Dry-cooler approach to ambient |
| plant | `dt_evap` | 3 | K | F | 1 – 6 | Evaporator approach (T_evap = T_sup - dt_evap) |
| plant | `eta_conv` | 0.94 | - | F | 0.88 – 0.97 | Grid-to-chip power conversion efficiency (UPS, PSU, VRs) |
| plant | `eta_ii_chiller` | 0.5 | - | E | 0.3 – 0.65 | Chiller second-law efficiency: COP = eta_II * COP_Carnot |
| plant | `fan_ratio` | 0.02 | W/W | F | 0.005 – 0.05 | Heat-rejection fan power per W of heat rejected to ambient |
| plant | `t_reuse_min` | 45 | degC | F | 35 – 60 | Return temperature needed for heat to count as reusable |
| policy | `fixed_flow` | 1 | x design | G |  | Flow factor of the fixed baseline policy |
| policy | `fixed_t_sup` | 18 | degC | G | 12 – 27 | Supply temperature of the fixed (conventional) baseline; within ASHRAE W17/W27-class supply ranges |
| policy | `joint_bias_gain` | 0.5 | - | G |  | EWMA gain of the joint_robust controller's temperature-bias estimate (measured minus predicted peak junction temperature, clipped at 0); used only by joint_robust |
| policy | `joint_switch_rel` | 0 | - | G |  | Move suppression: the joint controller keeps its previous action unless the new optimum is predicted to use this fraction less grid power (0 = always switch, as in E001-E005) |
| policy | `t_assume_compute` | 65 | degC | G |  | Junction temperature a compute-only controller (no thermal model) assumes |
| policy | `t_sup_step` | 1 | K | G |  | Supply-temperature grid resolution for optimizing controllers |
| routing | `frac_easy` | 0.6 | - | F | 0.2 – 0.9 | Fraction of tasks a small model can handle |
| routing | `p_large` | 0.97 | - | F | 0.8 – 0.995 | Large-model success probability |
| routing | `p_small_easy` | 0.92 | - | F | 0.6 – 0.99 | Small-model success probability on easy tasks |
| routing | `p_small_hard` | 0.3 | - | F | 0 – 0.6 | Small-model success probability on hard tasks |
| routing | `small_cost_ratio` | 0.2 | - | F | 0.05 – 0.5 | Small-model work / large-model work |
| routing | `verifier_false_accept` | 0 | - | F | 0 – 0.2 | P(verifier accepts a wrong small-model answer) |
| routing | `verifier_false_reject` | 0 | - | F | 0 – 0.2 | P(verifier rejects a correct small-model answer) |
| routing | `verify_cost_ratio` | 0.05 | - | F | 0 – 0.2 | Verifier work / large-model work |
| simulation | `backlog_clear_s` | 120 | s | G |  | Controllers plan to clear current backlog within this time |
| simulation | `control_interval` | 60 | s | G |  | Controller decision period |
| simulation | `demand_window` | 300 | s | G |  | Window for demand estimation (EWMA time constant) |
| simulation | `drain_max_s` | 3600 | s | G |  | Max time after last arrival to finish queued work |
| simulation | `dt` | 1 | s | G |  | Simulation time step |
| simulation | `log_interval` | 60 | s | G |  | Time-series logging period |
| thermal | `c_th` | 300 | J/K | F | 100 – 1000 | Lumped heat capacity of die + package + cold plate |
| thermal | `n_conv` | 0.6 | - | E | 0.33 – 0.8 | R_conv ~ flow**(-n). ~0.8 for turbulent (Dittus-Boelter), lower for developing laminar flow |
| thermal | `r_cond` | 0.035 | K/W | F | 0.02 – 0.06 | Conduction resistance junction -> wetted cold-plate surface (die, TIM, lid, base) |
| thermal | `r_conv_ref` | 0.015 | K/W | F | 0.008 – 0.03 | Convective resistance at design flow. For scale: a measured direct-to-chip cold plate (heater rig, not a GPU) showed 7.6-10.4 mK/W total at ~1 kW (reference_values.md, class B) |
| thermal | `t_target` | 80 | degC | G |  | Junction temperature limit that controllers must respect |
| thermal | `t_throttle` | 85 | degC | G |  | Independent hardware protection trip point (throttles to s_min regardless of controller) |
| thermal | `throttle_hyst` | 3 | K | G |  | Throttle release hysteresis |
| workload | `beta_compute` | 0.95 | - | E | 0.85 – 1 | Throughput ~ s**beta for compute-bound work (beta=1 is perfectly clock-bound) |
| workload | `beta_memory` | 0.35 | - | E | 0.15 – 0.6 | Throughput ~ s**beta for memory-bound work. Maliakel et al. 2025 (L09, preprint) report LLM decode latency changing <1% across clock settings, i.e. beta near 0, which is BELOW this range; a lower value would make DVFS look even better |
| workload | `frac_memory` | 0.4 | - | F | 0.1 – 0.8 | Fraction of jobs that are memory-bound |
| workload | `job_work_mean` | 20 | s | F | 5 – 120 | Mean job size in seconds at s=1 (lognormal) |
| workload | `job_work_sigma` | 0.6 | - | F | 0.2 – 1.2 | Lognormal sigma of job size |
| workload | `slo_base` | 30 | s | G |  | Latency SLO = slo_base + slo_factor * nominal work |
| workload | `slo_factor` | 5 | - | G |  | Latency SLO multiplier on nominal work |
| workload | `u_max` | 0.85 | - | G |  | Max planned utilization (queueing headroom) for optimizing controllers |

Counts by class: A: 3, E: 8, F: 27, G: 30
