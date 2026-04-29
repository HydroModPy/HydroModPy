"""Read a single field array from a simulation Zarr store.

Resolves a registered field through :mod:`hydromodpy.results.field_registry`
and reads the underlying array from a directory- or zip-backed Zarr store.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import zarr

from hydromodpy.results import field_registry

logger = logging.getLogger(__name__)


def import_zarr_field(
    zarr_path: str | Path,
    variable: str,
    *,
    timesteps: list[int] | None = None,
) -> np.ndarray:
    """Read one canonical field from a simulation Zarr store.

    Parameters
    ----------
    zarr_path : str or Path
        Path to the simulation store (directory or ``.zarr.zip`` file).
    variable : str
        Public field name. Validated against the canonical field registry.
    timesteps : list[int], optional
        Subset of timestep indices to read for time-aware fields. ``None``
        reads the whole array.

    Returns
    -------
    numpy.ndarray
        The field values. Shape matches the registered field signature
        (``time_layer_face``, ``time_face``, ``layer_face`` or ``face``).
    """
    descriptor = field_registry.get(variable)

    zarr_path = Path(zarr_path)
    if not zarr_path.exists():
        raise FileNotFoundError(f"Zarr store not found: {zarr_path}")

    if zarr_path.suffix == ".zip" or str(zarr_path).endswith(".zarr.zip"):
        store = zarr.storage.ZipStore(str(zarr_path), mode="r")
    else:
        store = zarr.storage.LocalStore(str(zarr_path))

    try:
        root = zarr.open_group(store, mode="r")
        arr = _resolve_zarr_path(root, descriptor.zarr_path)
        if arr is None:
            raise KeyError(
                f"Field '{variable}' (zarr_path={descriptor.zarr_path!r}) "
                f"not present in store {zarr_path}"
            )
        if timesteps is not None and arr.ndim >= 1:
            data = np.asarray(arr[:])[timesteps]
        else:
            data = np.asarray(arr[:])
    finally:
        if hasattr(store, "close"):
            store.close()

    logger.info("Imported Zarr field '%s' from %s (shape=%s)", variable, zarr_path, data.shape)
    return data


def _resolve_zarr_path(group: zarr.Group, zarr_path: str):
    """Walk a ``a/b/c`` zarr_path inside ``group`` and return the leaf array."""
    parts = zarr_path.split("/")
    cursor = group
    for part in parts[:-1]:
        sub = cursor.get(part)
        if sub is None:
            return None
        cursor = sub
    leaf = parts[-1]
    if leaf in cursor:
        return cursor[leaf]
    return None
