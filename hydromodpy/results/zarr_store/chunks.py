"""Balanced chunk and sharding heuristics for Zarr v3 stores."""

from __future__ import annotations

from hydromodpy.results.zarr_store.constants import (
    BALANCED_TARGET_BYTES,
    SHARD_TARGET_BYTES,
    SHARD_TRIGGER_BYTES,
)


def compute_balanced_chunks_1d(
    n_timesteps: int,
    n_cells: int,
    itemsize: int,
    target_chunk_bytes: int = BALANCED_TARGET_BYTES,
) -> tuple[int, int]:
    """Return a ``(time_chunk, cell_chunk)`` pair near the target chunk size."""
    target = target_chunk_bytes // max(itemsize, 1)
    if n_timesteps <= 0 or n_cells <= 0:
        return (1, max(n_cells, 1))
    if n_cells <= target:
        time_chunk = max(1, min(n_timesteps, target // max(n_cells, 1)))
        return (time_chunk, n_cells)
    cell_chunk = min(n_cells, max(1, target))
    return (1, cell_chunk)


def compute_balanced_chunks_2d(
    n_timesteps: int,
    n_layers: int,
    n_cells: int,
    itemsize: int,
    target_chunk_bytes: int = BALANCED_TARGET_BYTES,
) -> tuple[int, int, int]:
    """Return ``(time_chunk, layer_chunk, cell_chunk)`` near the target size."""
    per_step = n_layers * n_cells * max(itemsize, 1)
    if per_step <= target_chunk_bytes and n_timesteps > 0:
        time_chunk = max(1, min(n_timesteps, target_chunk_bytes // max(per_step, 1)))
        return (time_chunk, n_layers, n_cells)
    cell_chunk = max(1, target_chunk_bytes // (n_layers * max(itemsize, 1)))
    cell_chunk = min(n_cells, cell_chunk)
    return (1, n_layers, cell_chunk)


def should_use_sharding(
    n_timesteps: int,
    layer_bytes_per_step: int,
    threshold: int = SHARD_TRIGGER_BYTES,
) -> bool:
    """Return True when the variable footprint warrants a ShardingCodec."""
    if n_timesteps <= 0 or layer_bytes_per_step <= 0:
        return False
    return n_timesteps * layer_bytes_per_step > threshold


def compute_shard_shape_1d(
    n_timesteps: int,
    chunk_shape: tuple[int, int],
    target_shard_bytes: int = SHARD_TARGET_BYTES,
    itemsize: int = 8,
) -> tuple[int, int] | None:
    """Return the shard shape for a 1D-per-step variable, or None if unfit.

    Shards are sized to span several time chunks while staying under the
    target shard size (~64 MiB by default). The cell dimension is kept full.
    """
    time_chunk, cell_chunk = chunk_shape
    if time_chunk <= 0 or cell_chunk <= 0:
        return None
    chunk_bytes = time_chunk * cell_chunk * max(itemsize, 1)
    if chunk_bytes <= 0:
        return None
    chunks_per_shard = max(1, target_shard_bytes // chunk_bytes)
    shard_time = min(n_timesteps, chunks_per_shard * time_chunk)
    shard_time = max(shard_time, time_chunk)
    if shard_time % time_chunk != 0:
        shard_time -= shard_time % time_chunk
    shard_time = max(shard_time, time_chunk)
    if shard_time >= n_timesteps:
        shard_time = (n_timesteps // time_chunk) * time_chunk
        if shard_time == 0:
            return None
    return (int(shard_time), int(cell_chunk))


def compute_shard_shape_2d(
    n_timesteps: int,
    chunk_shape: tuple[int, int, int],
    target_shard_bytes: int = SHARD_TARGET_BYTES,
    itemsize: int = 8,
) -> tuple[int, int, int] | None:
    """Return the shard shape for a 2D-per-step variable, or None if unfit."""
    time_chunk, layer_chunk, cell_chunk = chunk_shape
    if time_chunk <= 0 or layer_chunk <= 0 or cell_chunk <= 0:
        return None
    chunk_bytes = time_chunk * layer_chunk * cell_chunk * max(itemsize, 1)
    if chunk_bytes <= 0:
        return None
    chunks_per_shard = max(1, target_shard_bytes // chunk_bytes)
    shard_time = min(n_timesteps, chunks_per_shard * time_chunk)
    shard_time = max(shard_time, time_chunk)
    if shard_time % time_chunk != 0:
        shard_time -= shard_time % time_chunk
    shard_time = max(shard_time, time_chunk)
    if shard_time >= n_timesteps:
        shard_time = (n_timesteps // time_chunk) * time_chunk
        if shard_time == 0:
            return None
    return (int(shard_time), int(layer_chunk), int(cell_chunk))


__all__ = [
    "compute_balanced_chunks_1d",
    "compute_balanced_chunks_2d",
    "should_use_sharding",
    "compute_shard_shape_1d",
    "compute_shard_shape_2d",
]
