"""Interface-only adapter for ATLAS (status: pending; repository not accessible, API not inspected).

UEIC needs from a kernel source only: a list of candidate kernels for one operation, each runnable on
given inputs, with a declared numerical tolerance. Once the ATLAS repository is available, implement
``candidates`` against its real API and remove the PendingIntegration. Nothing here describes ATLAS.
"""
from __future__ import annotations

from typing import Any

from . import PendingIntegration


class AtlasKernelSource:
    name = "atlas"

    def __init__(self, **config: Any):
        self.config = config

    def candidates(self, operation: str, shapes: dict[str, Any]) -> list:
        raise PendingIntegration("ATLAS integration pending: repository not accessible from this environment; "
                                 "its API has not been inspected and is not assumed")
