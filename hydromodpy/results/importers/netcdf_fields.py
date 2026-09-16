"""Read fields from a NetCDF-UGRID file produced by ``export_netcdf``.

Inverse of :func:`hydromodpy.results.exporters.netcdf.export_netcdf`. Variable
names are validated against :mod:`hydromodpy.results.field_registry` before any
read so unknown fields fail fast with :class:`UnknownFieldError`.

The export writes a layered field as one variable per layer, which QGIS needs,
so the read puts them back together. A model that ran on one layer is the
exception: its field was written under its bare name and comes back with the
shape of a surface field, since nothing in the file tells that apart from a
field that never had a layer.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import xarray as xr

from hydromodpy.core.logging import get_logger
from hydromodpy.results import field_registry

logger = get_logger(__name__)


def import_netcdf_fields(
    input_path: str | Path,
    variables: list[str] | None = None,
    *,
    timesteps: list[int] | None = None,
) -> dict[str, np.ndarray]:
    """Read selected fields from a UGRID NetCDF file.

    Parameters
    ----------
    input_path : str or Path
        Path to a ``.nc`` file written by :func:`export_netcdf`.
    variables : list[str], optional
        Field names to read. Each name is validated against the canonical
        field registry. ``None`` reads every registered field present in the
        file.
    timesteps : list[int], optional
        Subset of timestep indices to read. ``None`` reads all timesteps.

    Returns
    -------
    dict[str, numpy.ndarray]
        Mapping ``public_name -> array``. Missing variables in the file are
        silently skipped (they are reported in the log).
    """
    if variables is None:
        names = field_registry.all_names()
    else:
        for name in variables:
            field_registry.get(name)
        names = list(variables)

    input_path = Path(input_path)
    if not input_path.is_file():
        raise FileNotFoundError(f"NetCDF file not found: {input_path}")

    out: dict[str, np.ndarray] = {}
    with xr.open_dataset(input_path) as ds:
        for name in names:
            if name in ds.variables:
                out[name] = _read(ds, name, timesteps)
                continue
            stacked = _read_layers(ds, name, timesteps)
            if stacked is None:
                logger.debug("Variable '%s' not in %s, skipping", name, input_path)
                continue
            out[name] = stacked

    logger.info("Imported NetCDF: %s (%d fields)", input_path, len(out))
    return out


def _read(ds: xr.Dataset, name: str, timesteps: list[int] | None) -> np.ndarray:
    """One variable, restricted to the requested timesteps."""
    arr = ds[name]
    if timesteps is not None and "time" in arr.dims:
        arr = arr.isel(time=timesteps)
    return np.asarray(arr.values)


def _read_layers(ds: xr.Dataset, name: str, timesteps: list[int] | None) -> np.ndarray | None:
    """Stack ``<name>_layer<N>`` back into one (time, layer, face) array, or None."""
    pattern = re.compile(rf"^{re.escape(name)}_layer(\d+)$")
    found: list[tuple[int, str]] = []
    for variable in ds.variables:
        match = pattern.fullmatch(str(variable))
        if match is not None:
            found.append((int(match.group(1)), str(variable)))
    if not found:
        return None
    found.sort()
    return np.stack([_read(ds, variable, timesteps) for _, variable in found], axis=1)
