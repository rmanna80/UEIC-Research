"""Optional integrations with external kernel-generation tools (Stage 13).

ATLAS and KernelSmith: repository access was checked on 2026-11-01 (GitHub listing for this account:
no repository matching "atlas" or "kernel"). Their APIs and internal architecture are therefore unknown,
and nothing here assumes them: the adapters define the interface UEIC needs and raise
``PendingIntegration`` until the real repositories can be inspected. ``kernel_energy`` measures any set
of mathematically equivalent kernels supplied as Python callables, which is what E023 needs regardless
of where the kernels come from.
"""


class PendingIntegration(NotImplementedError):
    """Raised by interface-only adapters whose upstream API has not been inspected."""
