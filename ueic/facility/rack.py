"""Racks: a group of nodes with an electrical limit and a shared network uplink."""
from __future__ import annotations

from dataclasses import dataclass, field

from .node import Node


@dataclass
class Rack:
    name: str
    nodes: list[Node] = field(default_factory=list)
    power_limit_W: float | None = None      # IT power limit enforced by the power-capping layer
    uplink_jobs: int = 4                    # cross-node jobs the uplink carries without slowdown

    def __post_init__(self):
        if self.power_limit_W is not None and self.power_limit_W <= 0:
            raise ValueError("rack power limit must be positive")
        if self.uplink_jobs < 1:
            raise ValueError("uplink_jobs must be >= 1")
