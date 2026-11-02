"""Stage 13: interface-only external adapters and the equivalent-kernel energy harness."""
import numpy as np
import pytest

from ueic.integrations import PendingIntegration
from ueic.integrations.atlas_adapter import AtlasKernelSource
from ueic.integrations.kernel_energy import KernelCandidate, check_equivalence, facility_estimate, measure
from ueic.integrations.kernelsmith_adapter import KernelSmithKernelSource
from ueic.params import make_config


def test_external_adapters_are_pending_not_invented():
    for src in (AtlasKernelSource(), KernelSmithKernelSource()):
        with pytest.raises(PendingIntegration):
            src.candidates("matmul", {"M": 64})


def test_equivalence_gate_and_measurement_with_synthetic_power():
    rng = np.random.default_rng(0)
    A, B = rng.normal(size=(64, 64)), rng.normal(size=(64, 64))
    ref = A @ B
    cands = [KernelCandidate("matmul", lambda: A @ B),
             KernelCandidate("einsum", lambda: np.einsum("ik,kj->ij", A, B)),
             KernelCandidate("wrong", lambda: A @ B + 1e-3)]
    assert check_equivalence(cands, ref, 1e-9, 1e-9) == {"matmul": True, "einsum": True, "wrong": False}
    state = {"E": 0.0, "t": 0.0}
    def sample():                      # synthetic counter: 100 W, 10 ms per sample (NOT a measurement)
        state["t"] += 0.01; state["E"] += 1.0
        return {"t_unix": state["t"], "power_W": 100.0, "energy_J": state["E"], "temp_C": 50}
    r = measure(cands, ref, rtol=1e-9, atol=1e-9, repeats=2, sample=sample, min_window_s=0.05)
    assert set(r["kernels"]) == {"matmul", "einsum"} and r["kernels"]["matmul"]["J_per_call"] > 0
    f = facility_estimate(1000.0, 300.0, make_config({"plant_model": 1}), 30.0, 20.0)
    assert f["facility_est_J"] > 1000.0 and f["label"] == "estimated"
