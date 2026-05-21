"""Public Zarr-store constants. Kept tiny on purpose."""

from __future__ import annotations

import zarr.codecs

# Default Blosc-zstd codec used by every array written by HydroModPy.
# clevel=5 with bitshuffle is the V1 sweet spot for groundwater fields.
BLOSC_ZSTD = zarr.codecs.BloscCodec(
    cname="zstd",
    clevel=5,
    shuffle=zarr.codecs.BloscShuffle.bitshuffle,
)

# CF + ACDD + UGRID conventions advertised at the root of every store.
CF_CONVENTIONS = "CF-1.11, ACDD-1.3, UGRID-1.0"

# Schema version of the Zarr layout produced by HydroModPy V1 (P6).
# Stored in the ``meta`` group attributes and validated on open.
ZARR_SCHEMA_VERSION = "2"

# Subgroups created at store init.
_SUBGROUPS = (
    "meta",
    "mesh",
    "state",
    "derived",
    "budget",
    "particles",
    "forcing",
)

# Balanced chunk target. Picks a sweet spot around ~1 MiB on disk / S3.
BALANCED_TARGET_BYTES = 1 * 1024 * 1024

# Sharding threshold. Auto-enabled when (n_timesteps * itemsize_per_layer)
# exceeds 100 MiB, with a shard cap of ~64 MiB.
SHARD_TRIGGER_BYTES = 100 * 1024 * 1024
SHARD_TARGET_BYTES = 64 * 1024 * 1024
