"""Accelerator types and nodes for the facility simulator.

Accelerator types are *illustrative* parameter sets expressed as scale factors on the registry's simulated
accelerator (``params.py``). They are not models of commercial products and must not be described as such.

A node holds m accelerators on one coolant manifold, arranged as m/k parallel branches of k cold plates in
series (k = ``chain``; k = 1 is all-parallel). Each plate receives the design flow per accelerator at full
valve opening, so a series branch carries the same per-plate flow as a parallel one, and its downstream
plates see water warmed by the plates upstream (inlet rise = upstream heat / (m_dot c_p)).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AcceleratorType:
    name: str
    p_dyn_scale: float = 1.0      # x p_dyn_max
    static_scale: float = 1.0     # x p_static_other and p_leak_ref
    speed: float = 1.0            # throughput at s = 1 relative to the registry accelerator
    mem_GB: float = 80.0
    c_th_scale: float = 1.0       # x c_th
    r_cond_scale: float = 1.0     # x r_cond
    note: str = "illustrative; not a commercial product model"


@dataclass
class Node:
    name: str
    gpus: list[str]               # accelerator type names, in plate order (branch-major)
    chain: int = 1                # plates in series per branch
    hydraulic_scale: float = 1.0  # branch resistance relative to a node at the reference position
    rack: str = ""
    index: int = 0
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.chain < 1 or len(self.gpus) % self.chain:
            raise ValueError(f"node {self.name}: {len(self.gpus)} GPUs cannot form branches of {self.chain}")
        if self.hydraulic_scale <= 0:
            raise ValueError("hydraulic_scale must be positive")

    @property
    def m(self) -> int:
        return len(self.gpus)

    @property
    def n_branches(self) -> int:
        return self.m // self.chain
