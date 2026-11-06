"""Read a single field array from a simulation Zarr store.

Resolves a registered field through :mod:`hydromodpy.results.field_registry`
and reads the underlying array from a directory- or zip-backed Zarr store. The
store is opened like every other reader opens it, so a schema version outside
the read window is refused here too.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import zarr

from hydromodpy.core.logging import get_logger
from hydromodpy.results import field_registry
from hydromodpy.results.exporters.fields import resolve_zarr_path
from hydromodpy.results.zarr_store.zarr_schema import open_root_strict

logger = get_logger(__name__)


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
        Path to the run store directory, or a zipped package member.
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

    if zarr_path.suffix == ".zip":
        store = zarr.storage.ZipStore(str(zarr_path), mode="r")
    else:
        store = zarr.storage.LocalStore(str(zarr_path))

    try:
        root = open_root_strict(store, read_only=True)
        arr = resolve_zarr_path(root, descriptor.zarr_path)
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
