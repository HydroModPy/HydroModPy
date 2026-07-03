"""Shared bound for in-memory field-stack slabs across MODFLOW backends.

Field arrays (head, concentration, per-component budget stacks) are written in
batched slabs so each Zarr shard is encoded once instead of read-modify-written
per timestep. The slab is capped in bytes so a long transient run on a large
grid never materializes the whole ``(nper, nlay, ncells)`` stack in RAM.
"""

from __future__ import annotations

# Upper bound on the in-memory slab used for batched field-stack writes.
_STACK_SLAB_BYTES = 256 * 1024 * 1024


def slab_steps(nlay: int, n_cells: int, *, bytes_per_value: int = 8) -> int:
    """Number of timesteps that fit in one slab for a ``(nlay, ncells)`` field."""
    per_step = max(1, int(nlay) * int(n_cells) * int(bytes_per_value))
    return max(1, _STACK_SLAB_BYTES // per_step)


__all__ = ["_STACK_SLAB_BYTES", "slab_steps"]
