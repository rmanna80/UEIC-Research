"""Energy of mathematically equivalent kernels at the GPU and (estimated) facility boundaries (E023 harness).

A ``KernelCandidate`` is a callable producing a result for fixed inputs, plus a name. Every candidate must
match the reference result within the *same* tolerance (``rtol``, ``atol``); a candidate that fails is
excluded from energy comparisons, never ranked. For each candidate the harness records repeated timed
runs, GPU board energy over each run window (NVML energy counter or integrated power, via
``ueic.inference.energy_accounting.window_energy``), peak power and the temperature trajectory.

Facility energy is ESTIMATED: GPU energy plus cooling electricity from the plant model at the stated
supply and ambient temperatures, and conversion loss. It is labelled "facility_est" and never reported
as measured. Smoother power is not assumed to mean lower energy: peak power and energy are separate outputs.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from ..inference.energy_accounting import window_energy


@dataclass
class KernelCandidate:
    name: str
    fn: Callable[[], Any]
    source: str = "user"           # user | atlas | kernelsmith (pending)


def check_equivalence(cands: list[KernelCandidate], reference: Any, rtol: float, atol: float) -> dict[str, bool]:
    out = {}
    for c in cands:
        try:
            out[c.name] = bool(np.allclose(np.asarray(c.fn()), np.asarray(reference), rtol=rtol, atol=atol))
        except Exception:  # noqa: BLE001
            out[c.name] = False
    return out


def measure(cands: list[KernelCandidate], reference: Any, *, rtol: float, atol: float, repeats: int = 5,
            sample: Callable[[], dict] | None = None, sync: Callable[[], None] | None = None,
            min_window_s: float = 1.0) -> dict[str, Any]:
    """Run each equivalent candidate ``repeats`` times; each repeat loops the kernel for >= ``min_window_s``.
    ``sample()`` returns an NVML-like row (t_unix, power_W, energy_J, temp_C); None = timing only."""
    eq = check_equivalence(cands, reference, rtol, atol)
    res: dict[str, Any] = {"equivalence": eq, "tolerance": {"rtol": rtol, "atol": atol}, "kernels": {}}
    for c in cands:
        if not eq[c.name]:
            continue
        reps = []
        for _ in range(repeats):
            rows, n = [], 0
            t0 = time.time()
            if sample:
                rows.append(sample())
            while time.time() - t0 < min_window_s:
                c.fn(); n += 1
                if sync:
                    sync()
                if sample:
                    rows.append(sample())
            t1 = time.time()
            r = {"calls": n, "s_per_call": (t1 - t0) / n}
            if rows:
                w = window_energy([x["t_unix"] for x in rows], [x.get("power_W") for x in rows],
                                  [x.get("energy_J") for x in rows], rows[0]["t_unix"], rows[-1]["t_unix"])
                r.update(J_per_call=w["E_J"] / n, peak_W=max(x.get("power_W") or 0 for x in rows),
                         T_end_C=rows[-1].get("temp_C"), energy_method=w["method"])
            reps.append(r)
        res["kernels"][c.name] = {"source": c.source, "repeats": reps,
                                  "s_per_call": float(np.median([r["s_per_call"] for r in reps])),
                                  "J_per_call": float(np.median([r["J_per_call"] for r in reps])) if sample else None,
                                  "peak_W": float(np.median([r["peak_W"] for r in reps])) if sample else None}
    return res


def facility_estimate(J_gpu: float, mean_heat_W: float, cfg, T_sup: float, T_amb: float) -> dict[str, float]:
    """Estimated facility energy for a GPU energy at a mean heat rate (plant model; class F parameters)."""
    from .. import physics as ph
    pl = ph.plant(mean_heat_W, T_sup, 1.0, T_amb, cfg)
    ovh = float((pl["P_fan"] + pl["W_ch"]) / max(mean_heat_W, 1e-9))
    return {"facility_est_J": J_gpu / cfg.eta_conv + J_gpu * ovh, "cooling_overhead": ovh, "label": "estimated"}
