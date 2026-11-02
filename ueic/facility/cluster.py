"""Cluster topology: racks of nodes, accelerator types, facility limits. Built from a dict/JSON or with
``make_topology``. Topologies in ``topologies/*.json`` are hypothetical configurations for simulation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .node import AcceleratorType, Node
from .rack import Rack

TOPOLOGY_DIR = Path(__file__).with_name("topologies")


@dataclass
class Cluster:
    name: str
    types: dict[str, AcceleratorType]
    racks: list[Rack]
    facility_power_limit_W: float | None = None
    description: str = ""
    nodes: list[Node] = field(default_factory=list)

    def __post_init__(self):
        self.nodes = []
        for r in self.racks:
            for nd in r.nodes:
                nd.rack, nd.index = r.name, len(self.nodes)
                for t in nd.gpus:
                    if t not in self.types:
                        raise KeyError(f"node {nd.name}: unknown accelerator type {t}")
                self.nodes.append(nd)
        if not self.nodes:
            raise ValueError("cluster has no nodes")

    @property
    def n_gpus(self) -> int:
        return sum(n.m for n in self.nodes)


def from_dict(d: dict[str, Any]) -> Cluster:
    types = {k: AcceleratorType(k, **v) for k, v in d.get("accelerator_types", {"A": {}}).items()}
    racks = [Rack(r["name"], [Node(**n) for n in r["nodes"]], r.get("power_limit_W"), r.get("uplink_jobs", 4))
             for r in d["racks"]]
    return Cluster(d["name"], types, racks, d.get("facility_power_limit_W"), d.get("description", ""))


def load(name_or_path: str) -> Cluster:
    p = Path(name_or_path)
    if not p.exists():
        p = TOPOLOGY_DIR / f"{name_or_path}.json"
    return from_dict(json.loads(p.read_text()))


def make_topology(n_racks: int = 1, nodes_per_rack: int = 1, gpus_per_node: int = 8, chain: int = 1,
                  hydraulic_spread: float = 0.0, type_mix: list[str] | None = None,
                  types: dict[str, dict] | None = None, rack_limit_W: float | None = None,
                  facility_limit_W: float | None = None, uplink_jobs: int = 4, name: str = "generated") -> dict[str, Any]:
    """Symmetric topology as a dict. Node i of N gets hydraulic_scale 1 + spread * i/(N-1) (farther from the
    pump = more resistance). ``type_mix`` cycles accelerator types over nodes (heterogeneous clusters)."""
    types = types or {"A": {}}
    mix = type_mix or [next(iter(types))]
    N = n_racks * nodes_per_rack
    racks = []
    for r in range(n_racks):
        nodes = []
        for j in range(nodes_per_rack):
            i = r * nodes_per_rack + j
            h = 1.0 + hydraulic_spread * (i / (N - 1) if N > 1 else 0.0)
            nodes.append({"name": f"n{i}", "gpus": [mix[i % len(mix)]] * gpus_per_node, "chain": chain, "hydraulic_scale": h})
        racks.append({"name": f"r{r}", "nodes": nodes, "power_limit_W": rack_limit_W, "uplink_jobs": uplink_jobs})
    return {"name": name, "description": "generated hypothetical topology (simulation only)",
            "accelerator_types": types, "racks": racks, "facility_power_limit_W": facility_limit_W}
