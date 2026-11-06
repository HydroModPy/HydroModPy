"""Zarr v3 per-simulation store (CF-1.11 + ACDD-1.3 + UGRID-1.0)."""

from hydromodpy.results.zarr_store.acdd import (
    compose_acdd_root_attrs,
)
from hydromodpy.results.zarr_store.cf_validation import (
    is_cf_standard_name,
)
from hydromodpy.results.zarr_store.chunks import (
    compute_balanced_chunks_1d,
    compute_balanced_chunks_2d,
    compute_shard_shape_1d,
    compute_shard_shape_2d,
    should_use_sharding,
)
from hydromodpy.results.zarr_store.constants import (
    BALANCED_TARGET_BYTES,
    BLOSC_ZSTD,
    CF_CONVENTIONS,
    SHARD_TARGET_BYTES,
    SHARD_TRIGGER_BYTES,
    ZARR_SCHEMA_VERSION,
)
from hydromodpy.results.zarr_store.simulation_zarr import (
    LOCK_TIMEOUT_SECONDS,
    SimulationZarr,
)

__all__ = [
    "BALANCED_TARGET_BYTES",
    "BLOSC_ZSTD",
    "CF_CONVENTIONS",
    "LOCK_TIMEOUT_SECONDS",
    "SHARD_TARGET_BYTES",
    "SHARD_TRIGGER_BYTES",
    "SimulationZarr",
    "ZARR_SCHEMA_VERSION",
    "compose_acdd_root_attrs",
    "compute_balanced_chunks_1d",
    "compute_balanced_chunks_2d",
    "compute_shard_shape_1d",
    "compute_shard_shape_2d",
    "is_cf_standard_name",
    "should_use_sharding",
]
