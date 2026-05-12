"""Zarr v2 per-simulation store (CF-1.11 + ACDD-1.3 + UGRID-1.0)."""

from hydromodpy.results.zarr_store.acdd import (
    HIGHLY_RECOMMENDED,
    compose_acdd_root_attrs,
)
from hydromodpy.results.zarr_store.adapters.fsspec_store import FsspecZarrStore
from hydromodpy.results.zarr_store.atomic import (
    STATUS_COMPLETE,
    STATUS_INCOMPLETE,
    atomic_write_array,
)
from hydromodpy.results.zarr_store.cf_aliases import CF_ALIASES, CfAlias, alias_for
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
from hydromodpy.results.zarr_store.exceptions import ZarrSchemaVersionError
from hydromodpy.results.zarr_store.simulation_zarr import (
    LOCK_FILE_NAME,
    LOCK_TIMEOUT_SECONDS,
    SimulationZarr,
    _ensure_local_zarr_node_dir,
    _is_zip_store_path,
    _local_store_path_arg,
    _windows_long_path,
)

__all__ = [
    "BALANCED_TARGET_BYTES",
    "BLOSC_ZSTD",
    "CF_ALIASES",
    "CF_CONVENTIONS",
    "CfAlias",
    "FsspecZarrStore",
    "HIGHLY_RECOMMENDED",
    "LOCK_FILE_NAME",
    "LOCK_TIMEOUT_SECONDS",
    "SHARD_TARGET_BYTES",
    "SHARD_TRIGGER_BYTES",
    "STATUS_COMPLETE",
    "STATUS_INCOMPLETE",
    "SimulationZarr",
    "ZARR_SCHEMA_VERSION",
    "ZarrSchemaVersionError",
    "alias_for",
    "atomic_write_array",
    "compose_acdd_root_attrs",
    "compute_balanced_chunks_1d",
    "compute_balanced_chunks_2d",
    "compute_shard_shape_1d",
    "compute_shard_shape_2d",
    "should_use_sharding",
    "_ensure_local_zarr_node_dir",
    "_is_zip_store_path",
    "_local_store_path_arg",
    "_windows_long_path",
]
