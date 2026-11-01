# 13 · Physics models (Stage 1)

**Status:** implemented and tested; *not yet calibrated against any plant hardware*.
* Every new component is a class F placeholder in its parameters. Only the forms carry class A/E justification.
* The simulator uses the new heat-rejection plant only when `plant_model = 1`. Every experiment up to E014 used the legacy plant, and the bitwise E001 reproduction test confirms the legacy path is unchanged.

## 1. Why the physics changed

E012 asked whether warm coolant could be the energy optimum. The independent audit showed the legacy plant made that impossible:
* Fan power was a fixed fraction of the heat rejected.
* The dry cooler reached any outlet temperature down to ambient + 5 K at the same cost.

So above the free-cooling limit, warmer water saved nothing on the facility side, and any leakage slope pushed the optimum to the coldest water. A defensible answer needs a heat-rejection model in which:
* fan power depends on how close to ambient the water must be cooled;
* the chiller's efficiency depends on load and temperature lift.

## 2. Package layout and data flow

`ueic/physics/` replaced `ueic/physics.py`. The old file moved verbatim to `ueic/physics/__init__.py`, so `from ueic import physics as ph` and every existing call behave as before. The one addition is a guarded branch in `plant` and `plant_split`: when `cfg.plant_model == 1` they delegate to `dry_cooler.plant_ntu` / `plant_split_ntu`, which return the same keys plus `fan_speed`.

```
sim.py / twin.py ──ph.plant / ph.plant_split──► legacy plant           (plant_model = 0)
                                             └► dry_cooler.plant_ntu    (plant_model = 1)
                                                   ├─ DryCoolerDesign.from_config(cfg)  sizing
                                                   ├─ dry_cooler_operate(...)           fan speed by bisection
                                                   └─ chiller.chiller_cop_part_load(...) trim chiller
```

Components not yet wired into the simulator: `hydraulics` (pump curve), `coolant` (transport delay), `thermal_storage` (stratified tank), `heat_pump`, `heat_reuse` and `power_delivery`. Each is tested on its own. They are wired in when an experiment needs them, behind a registry flag whose default keeps the legacy behaviour.

## 3. Components

All internal quantities are SI: W, J, K (temperature differences), kg, m³, s. Temperatures are in °C where only differences matter, and in K inside any ratio (COP, exergy).

### 3.1 Dry cooler: `dry_cooler.py`

| Quantity | Equation | Unit |
|---|---|---|
| Water capacity rate | C_w = ṁ_w c_p,w | W/K |
| Air capacity rate | C_a(x) = C_a,d · x, with x = fan speed / design | W/K |
| Conductance | UA(x) = UA_d · x^n_air | W/K |
| NTU, ratio | NTU = UA / C_min; Cr = C_min / C_max | – |
| Effectiveness (crossflow, both unmixed; Incropera & DeWitt approximation) | ε = 1 − exp[(NTU^0.22/Cr)(exp(−Cr·NTU^0.78) − 1)] | – |
| Heat rejected | Q_dc = ε C_min (T_w,in − T_amb) | W |
| Fan power (affinity law, fixed system curve) | P_fan = P_fan,d · x³ | W |

* **Sizing (class G choice).**
  * Design heat Q_d is the node's full-load heat: n·P_chip(s=1, T_ref) + pump.
  * C_a,d = `dc_air_ratio` · C_w,d.
  * UA_d is solved so that, at design flow and full fan speed, the outlet reaches T_amb + `dt_drycooler`.
  * Fan power at full speed is `fan_ratio` · Q_d.
  * At that one point the new model reproduces the legacy plant exactly (tested).
* **Operation.**
  * The lowest fan speed in [`dc_fan_min`, 1] that reaches the required outlet is found by bisection; Q_dc is monotonic in x.
  * A bypass prevents undershoot.
  * If full speed cannot reach the target, the dry cooler runs flat out and the chiller trims the rest.
  * Fans are off when the water is not warmer than the air.
* **Parameters:** `dc_air_ratio` 2.0 (F, range 1–4); `dc_ua_exponent` 0.6 (F, 0.4–0.8); `dc_fan_min` 0.1 (G); `dt_drycooler` 5 K and `fan_ratio` 0.02 (F, legacy).
* **Assumptions and failure modes:**
  * dry operation only: no adiabatic or wet-bulb assist;
  * the water-side film is ignored in the UA scaling;
  * the correlation is approximate.
  * Too small an air ratio or approach makes the design point unreachable, and the constructor raises (tested).
* **Validation strategy:** compare with a manufacturer's dry-cooler selection table once one is obtained. Until then the cubic fan law is the only part with strong (class A) support.
* **What it changes:** at the node's design heat and 20 °C ambient, fan power at 25 °C supply equals the legacy 100 W. At 30, 35 and 40 °C supply it falls to about 14, 4 and 1.4 W, against a constant 100 W in the legacy plant (`python -c` check in the Stage 1 commit message; reproduced by `test_fan_power_falls_with_approach_and_part_load`).

### 3.2 Chiller: `chiller.py`

* COP_full = η_II · T_evap/(T_cond − T_evap), capped at `cop_max` (legacy). T_evap = T_sup − `dt_evap`; T_cond = T_amb + `dt_cond`.
* Part load (DOE-2 EIR-fPLR form): W/W_full = a + b·PLR + c·PLR², so COP(PLR) = COP_full · PLR/(a + b·PLR + c·PLR²). PLR = Q_ch/Q_d, clipped to (0, 1.2].
* Defaults (0, 1, 0) mean no part-load effect, which is the legacy behaviour. Any other coefficients are placeholders.
* COP never exceeds the Carnot COP for the same temperatures (tested).

### 3.3 Pump: `hydraulics.py`

* System curve Δp = Δp_ref·f^m.
* Parabolic best-efficiency curve η(f) = η_bep(1 − k((f − f_bep)/f_bep)²), clipped.
* P = Δp·V̇/η.
* Affinity laws: V ∝ r, Δp ∝ r², P ∝ r³.
* k = 0 reproduces the legacy constant efficiency (tested).

### 3.4 Coolant transport: `coolant.py`

* Volume-based plug-flow delay line: the outlet sees the parcel that entered V_pipe earlier in cumulative volume, so τ = V_pipe/V̇ at constant flow.
* Stored energy is tracked, and inflow − outflow equals the change in storage (tested).
* No dispersion and no wall losses.

### 3.5 Thermal storage: `thermal_storage.py`

* n mixed layers in series, each advanced with its exact exponential solution and fed by the previous layer's step-mean outlet.
* Energy is conserved to round-off (tested for n = 1, 5, 20).
* n = 1 equals the legacy well-mixed `tank_step` exactly (tested).
* For n > 1 the dynamics are first-order accurate in dt.

### 3.6 Heat pump and heat reuse: `heat_pump.py`, `heat_reuse.py`

* **Heat pump.**
  * COP_h = η_II·T_cond/(T_cond − T_evap), capped.
  * Q_del = Q_src + W.
  * W = Q_src/(COP − 1).
  * W = 0 when the source is already hot enough.
  * First and second laws are tested.
* **Reuse.**
  * Direct reuse if the waste heat is at least `dt_hx` above the customer's required temperature; otherwise the heat pump upgrades it.
  * Used heat is capped by demand and availability (tested).
  * Economic value is kept in its own account: price_heat·E_heat − price_el·E_el. Reused heat is never subtracted from facility electricity.

### 3.7 Power delivery: `power_delivery.py`

* P_loss = P0 + k1·P + k2·P²/P_rated; η = P/(P + P_loss).
* `coefficients_for_constant(η)` reproduces the legacy constant efficiency (tested).

### 3.8 GPU and chip thermal views: `gpu.py`, `thermal.py`

These re-export the legacy functions unchanged, with their equations, units and provenance in the module docstrings, and add:
* energy per unit of work;
* the most efficient clock;
* the junction time constant R·C;
* the loop time constant M·c_p/Ċ.

## 4. Parameters with uncertainty: `ueic/models/`

* **`parameter_registry.py`** wraps the legacy registry without changing a value.
  * Each parameter becomes an `UncertainParameter` of kind `point` (A/G), `range` (E/F sensitivity range, explicitly *not* a probability distribution) or `normal` (measured with a standard error).
  * It carries its uncertainty type (parameter, structural, measurement, numerical, workload), hardware, calibration date, model version, and the **domain** of operating variables over which it was measured.
  * `with_calibration` overlays M001's accepted values, with the RTX 5070's identity and the swept clock-ratio domain.
  * `check_domain` raises `ExtrapolationWarning` outside that domain (tested).
  * Sampling uses a Gaussian copula for correlations (tested).
* **`uncertainty.py`** provides the delta method and Monte Carlo propagation. Monte Carlo reports rejected (non-physical) draws and labels results from uniform placeholder ranges as stress-test envelopes.
* **`identifiability.py`** gives the Fisher information J^T J/σ², Cramér–Rao standard errors, near-null directions and a per-parameter verdict (rel_tol 0.5).
  * Applied to the warm-up fit P(T) = c + L·exp(κ(T − 60)), it shows why M001/M002 could not identify κ.
  * With ~10 independent temperature levels over 48–57 °C (1 °C resolution, autocorrelated samples), κ's relative error is far above 0.5. A 45–80 °C window cuts it more than fivefold (tested).
  * This supports M003's design: widen the temperature window at fixed clock.
* **`model_validation.py`** provides held-out RMSE, MAE, bias, maximum error, interval coverage, k-fold cross-validation and AIC/BIC. A more complex model is preferred only if held-out error falls.

## 5. How to run and test

```bash
python -m pytest tests/test_stage1_physics.py        # 23 tests: components, invariants, uncertainty
python -m pytest tests/test_phase3.py -k legacy       # bitwise reproduction of stored E001 runs
python -c "from ueic.params import make_config; from ueic import physics as ph; \
cfg = make_config({'plant_model': 1}); print(ph.plant(5000, 30, 1.0, 20, cfg)['P_fan'])"
```

## 6. Interpretation and limits

* Results produced with `plant_model = 1` are simulations of a placeholder dry cooler and chiller. They show *how* conclusions depend on heat-rejection physics, not what a particular facility would do.
* The fan-power curve's shape is well founded. Its level (`fan_ratio`) and the design approach are not.
* Any warm-water or heat-reuse result (E021) must report its sensitivity to `dc_air_ratio`, `dc_ua_exponent`, `fan_ratio` and `dt_drycooler`.
