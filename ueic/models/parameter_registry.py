"""Parameters with uncertainty, provenance and validity domains (Stage 1, Part 2.2).

The legacy registry (``ueic.params.REGISTRY``) stores one value, an evidence class and, for
class E/F values, a sensitivity range. That range is a *what-if* interval for one-at-a-time
sweeps, not a probability statement. This module keeps that distinction explicit:

  kind = "point"    physical constant (A) or design choice (G); no uncertainty attached
  kind = "range"    placeholder or extrapolation (E/F) with a sensitivity range; sampling it
                    uniformly is a stress test, NOT a credible distribution
  kind = "normal"   measured value with a standard error (B on the measured hardware)

Each entry also records its uncertainty type, the hardware and date of a measurement, the model
version, and the *domain* of operating variables (e.g. clock ratio, junction temperature) over
which it was measured. Using a measured value outside that domain is extrapolation and raises a
warning through ``ParameterSet.check_domain``.

Uncertainty types (kept separate, as the research plan requires):
  parameter     value of a parameter in a model of known form
  structural    the model form itself may be wrong (e.g. one well-mixed tank for a real loop)
  measurement   noise and resolution of the instruments (e.g. NVML 1 degC steps)
  numerical     discretisation and solver error (E004 measured ~0.5% decision-path sensitivity)
  workload      the synthetic workload vs real traffic
"""
from __future__ import annotations

import json
import warnings
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

MODEL_VERSION = "ueic-ng-stage1"
UNCERTAINTY_TYPES = ("parameter", "structural", "measurement", "numerical", "workload", "none")


class ExtrapolationWarning(UserWarning):
    """An operating point lies outside the domain where a parameter was measured or calibrated."""


@dataclass(frozen=True)
class UncertainParameter:
    name: str
    value: float
    unit: str
    evidence: str
    source: str
    kind: str = "point"                       # point | range | normal
    sd: float | None = None                   # standard deviation (kind = normal)
    low: float | None = None                  # sensitivity range (kind = range)
    high: float | None = None
    uncertainty_type: str = "none"
    hardware: str | None = None
    calibration_date: str | None = None
    model_version: str = MODEL_VERSION
    domain: dict[str, tuple[float, float]] = field(default_factory=dict)   # operating variable -> measured range
    note: str = ""

    def __post_init__(self):
        if self.kind not in ("point", "range", "normal"):
            raise ValueError(f"{self.name}: unknown kind {self.kind}")
        if self.kind == "normal" and not (self.sd is not None and self.sd >= 0):
            raise ValueError(f"{self.name}: a measured (normal) parameter needs sd >= 0")
        if self.kind == "range" and not (self.low is not None and self.high is not None and self.low <= self.high):
            raise ValueError(f"{self.name}: a range parameter needs low <= high")
        if self.uncertainty_type not in UNCERTAINTY_TYPES:
            raise ValueError(f"{self.name}: unknown uncertainty type {self.uncertainty_type}")

    def interval(self, level: float = 0.95) -> tuple[float, float]:
        """Two-sided interval: normal -> mean +/- z sd; range -> the sensitivity range; point -> (v, v)."""
        if self.kind == "normal":
            from scipy.stats import norm
            z = float(norm.ppf(0.5 + level / 2))
            return self.value - z * self.sd, self.value + z * self.sd
        if self.kind == "range":
            return float(self.low), float(self.high)
        return self.value, self.value

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["domain"] = {k: list(v) for k, v in self.domain.items()}
        return d


class ParameterSet:
    """A set of uncertain parameters with optional correlations (Gaussian copula for sampling)."""

    def __init__(self, params: Iterable[UncertainParameter], correlation: Mapping[tuple[str, str], float] | None = None):
        self.params: dict[str, UncertainParameter] = {p.name: p for p in params}
        self.correlation: dict[tuple[str, str], float] = {}
        for (a, b), r in (correlation or {}).items():
            self.set_correlation(a, b, r)

    def __getitem__(self, k: str) -> UncertainParameter:
        return self.params[k]

    def __contains__(self, k: str) -> bool:
        return k in self.params

    def set_correlation(self, a: str, b: str, r: float) -> None:
        if a not in self.params or b not in self.params:
            raise KeyError(f"unknown parameter in correlation ({a}, {b})")
        if not -1.0 < r < 1.0:
            raise ValueError("correlation must be in (-1, 1)")
        self.correlation[(a, b)] = self.correlation[(b, a)] = float(r)

    def uncertain(self) -> list[str]:
        return [k for k, p in self.params.items() if p.kind != "point"]

    def values(self) -> dict[str, float]:
        return {k: p.value for k, p in self.params.items()}

    def update(self, p: UncertainParameter) -> "ParameterSet":
        new = ParameterSet(list(self.params.values()))
        new.params[p.name] = p
        new.correlation = dict(self.correlation)
        return new

    def sample(self, n: int, rng: np.random.Generator, names: list[str] | None = None) -> list[dict[str, float]]:
        """n joint draws of the uncertain parameters (others fixed at their values).

        Gaussian copula: correlated standard normals z (Cholesky of the correlation matrix) are mapped to
        each marginal: normal -> value + sd z (truncated to physical bounds by the caller's validation),
        range -> low + (high - low) Phi(z) (uniform, a stress test, not a credible distribution)."""
        from scipy.stats import norm
        names = names or self.uncertain()
        k = len(names)
        R = np.eye(k)
        for i, a in enumerate(names):
            for j, b in enumerate(names):
                if i != j and (a, b) in self.correlation:
                    R[i, j] = self.correlation[(a, b)]
        Lc = np.linalg.cholesky(R)                 # raises if the correlation matrix is not positive definite
        z = rng.standard_normal((n, k)) @ Lc.T
        out = []
        base = self.values()
        for row in z:
            d = dict(base)
            for zi, name in zip(row, names):
                p = self.params[name]
                if p.kind == "normal":
                    d[name] = p.value + p.sd * zi
                elif p.kind == "range":
                    d[name] = p.low + (p.high - p.low) * float(norm.cdf(zi))
            out.append(d)
        return out

    def check_domain(self, operating_point: Mapping[str, float], names: Iterable[str] | None = None,
                     warn: bool = True) -> list[str]:
        """Messages for every parameter whose measured domain does not contain the operating point."""
        msgs = []
        for k in (names or self.params):
            p = self.params[k]
            for var, (lo, hi) in p.domain.items():
                if var in operating_point and not lo <= operating_point[var] <= hi:
                    msgs.append(f"{k} was measured for {var} in [{lo:g}, {hi:g}]; using it at {var} = "
                                f"{operating_point[var]:g} is extrapolation ({p.hardware or 'unknown hardware'})")
        if warn:
            for m in msgs:
                warnings.warn(m, ExtrapolationWarning, stacklevel=2)
        return msgs

    def to_json(self) -> str:
        return json.dumps({"model_version": MODEL_VERSION, "parameters": [p.to_dict() for p in self.params.values()],
                           "correlation": [[a, b, r] for (a, b), r in self.correlation.items() if a < b]}, indent=1)


def from_registry() -> ParameterSet:
    """Wrap the legacy registry without changing any value."""
    from ..params import REGISTRY
    out = []
    for p in REGISTRY.values():
        if p.evidence in ("E", "F") and p.low is not None and p.high is not None:
            out.append(UncertainParameter(p.name, float(p.value), p.unit, p.evidence, p.source, kind="range",
                                          low=float(p.low), high=float(p.high), uncertainty_type="parameter",
                                          note="sensitivity range for stress tests, not a probability distribution"))
        else:
            ut = "parameter" if p.evidence in ("E", "F") else "none"
            out.append(UncertainParameter(p.name, float(p.value), p.unit, p.evidence, p.source, kind="point",
                                          uncertainty_type=ut,
                                          note="no range recorded" if ut == "parameter" else ""))
    return ParameterSet(out)


def with_calibration(ps: ParameterSet, calibration_json: str | Path) -> ParameterSet:
    """Overlay accepted measurements from a ``calib fit`` file (e.g. M001) with their standard errors,
    hardware identity, date and measured domain (clock ratios of the sweep)."""
    c = json.loads(Path(calibration_json).read_text())
    dev = c.get("device") or {}
    hw = f"{dev.get('name', 'unknown GPU')} {dev.get('uuid', '')}".strip()
    date = c.get("created_utc")
    s_vals = [p["s"] for p in c.get("energy_per_work", {}).get("compute", {}).get("points", [])]
    domain = {"s": (min(s_vals), max(s_vals))} if s_vals else {}
    for name, v in c.get("overrides", {}).items():
        old = ps[name] if name in ps else None
        p = UncertainParameter(name, float(v["value"]), old.unit if old else "-", v.get("evidence", "B"),
                               f"measured: {Path(calibration_json).name}" + (f"; {v['note']}" if v.get("note") else ""),
                               kind="normal", sd=float(v.get("se") or 0.0), uncertainty_type="parameter",
                               hardware=hw, calibration_date=date, domain=domain,
                               note="transfer to the simulated accelerator is class E")
        ps = ps.update(p)
    return ps


def with_leakage_slope(ps: ParameterSet, rel_per_K: float, se: float, T_window: tuple[float, float], hardware: str,
                       date: str | None = None) -> ParameterSet:
    """Record a measured leakage temperature slope (relative to board power per K) with its window.

    The simulator does not take this slope directly; it is matched through kappa_leak and p_leak_ref
    (E009). Recording it here lets controllers warn when junction temperatures leave the window."""
    p = UncertainParameter("leak_slope_rel_per_K", rel_per_K, "1/K", "B", "warm-up slope at constant fan (M001/M002)",
                           kind="normal", sd=se, uncertainty_type="parameter", hardware=hardware, calibration_date=date,
                           domain={"T_j_C": (float(T_window[0]), float(T_window[1]))},
                           note="window too narrow to identify kappa and leakage power separately")
    return ParameterSet(list(ps.params.values()) + [p]) if p.name not in ps else ps.update(p)


def evidence_summary(ps: ParameterSet) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in ps.params.values():
        key = f"{p.evidence}/{p.kind}"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


__all__ = ["UncertainParameter", "ParameterSet", "ExtrapolationWarning", "from_registry", "with_calibration",
           "with_leakage_slope", "evidence_summary", "UNCERTAINTY_TYPES", "replace"]
