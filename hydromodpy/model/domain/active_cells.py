"""The cells a domain is defined on, read from the terrain or from a mask layer.

A cell is active when the terrain has a value there and, with a mask, when the
mask polygons burned onto the terrain grid cover it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
from rasterio.features import rasterize

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.core.fields.nodata import valid_cells
from hydromodpy.schema.job.refusal import refuse_request

ACTIVE = 1
INACTIVE = 0
"""The two values of ``active_cells.tif``, as the declaration publishes them."""

POLYGONAL_TYPES = frozenset({"Polygon", "MultiPolygon"})
"""The geometry types a mask may be made of."""


def active_cell_mask(
    top: np.ndarray,
    *,
    nodata: float | None,
    mask: tuple[Path, str] | None,
    transform: Any,
    crs: Any,
) -> np.ndarray:
    """Return the boolean grid of cells the domain is defined on."""
    # Exact equality on the sentinel: ``Surface.shifted_down_by`` leaves it in
    # place rather than shifting it, precisely so this comparison holds.
    active = valid_cells(top, nodata)
    if mask is not None:
        mask_path, mask_layer = mask
        active &= _burned_mask(
            mask_path, layer=mask_layer, shape=top.shape, transform=transform, crs=crs
        )
    if not bool(active.any()):
        raise DataContractViolation(
            "no cell of the terrain is active: the declared mask selects none of it, "
            "or the raster carries nothing but its nodata value"
        )
    return active


def resolve_mask_layer(mask_path: Path, *, declared: str | None) -> str:
    """Return the layer the mask will be read from, refusing an unusable choice.

    Resolved by the worker, before a byte is written, for two reasons. A
    layer nobody can read is a request fault and the caller should learn it with
    the directory still as they staged it. And the *resolved* name is what the
    ``job_id`` is taken over: a file holding one layer is read the same way
    whether the request named it or left the choice to the file, so the two
    submissions are one job.
    """
    try:
        layers = [str(name) for name in gpd.list_layers(mask_path)["name"]]
    except Exception as exc:
        # Broad on purpose: pyogrio, fiona and GDAL each raise their own type
        # for "this is not a vector dataset", and the answer is the same one.
        raise DataContractViolation(
            f"mask {mask_path.name} cannot be opened as a vector dataset: {exc}"
        ) from exc
    if not layers:
        raise DataContractViolation(f"mask {mask_path.name} holds no layer at all")
    if declared is None:
        if len(layers) > 1:
            raise refuse_request(
                f"mask {mask_path.name} holds {len(layers)} layers "
                f"({', '.join(sorted(layers))}) and the request names none",
                loc=("inputs", "mask_layer"),
                msg="name the layer to read",
            )
        return layers[0]
    if declared not in layers:
        raise refuse_request(
            f"mask {mask_path.name} holds no layer named {declared!r}; "
            f"it holds {', '.join(sorted(layers))}",
            loc=("inputs", "mask_layer"),
            msg=f"unknown layer {declared!r}",
        )
    return declared


def _burned_mask(
    mask_path: Path,
    *,
    layer: str,
    shape: tuple[int, ...],
    transform: Any,
    crs: Any,
) -> np.ndarray:
    """Burn the resolved polygon layer onto the terrain grid."""
    frame = gpd.read_file(mask_path, layer=layer)
    if frame.crs is None:
        raise DataContractViolation(
            f"mask {mask_path.name} carries no CRS, so it cannot be placed on the terrain"
        )
    if crs is not None and frame.crs != crs:
        frame = frame.to_crs(crs)
    geometries = [geometry for geometry in frame.geometry if geometry is not None]
    if not geometries:
        raise DataContractViolation(
            f"layer {layer!r} of mask {mask_path.name} holds no geometry to bound the domain"
        )
    # A mask bounds an area, so it is made of areas. Without this, a line layer
    # burns a one-cell-wide diagonal and a point layer burns a single cell, and
    # both come back as a successful job with a domain that is a sliver --
    # which is what pointing ``mask`` at a hydrographic network instead of a
    # catchment produces, and the two live side by side in the same project.
    not_areas = sorted({geometry.geom_type for geometry in geometries} - POLYGONAL_TYPES)
    if not_areas:
        raise DataContractViolation(
            f"layer {layer!r} of mask {mask_path.name} holds {', '.join(not_areas)} geometries; "
            "the mask bounds an area and is read as polygons"
        )
    burned = rasterize(
        geometries,
        out_shape=shape,
        transform=transform,
        fill=INACTIVE,
        default_value=ACTIVE,
        all_touched=False,
        dtype="uint8",
    )
    return burned.astype(bool)
