"""Resolvers of the delineation members and the zone-partic aliases for the MODPATH backend.

The raster and shapefile lookups of the MODPATH inputs are public because the annex
reads them. They read the DEM grid and the catchment from ``Model.geometry`` through the
``inputs`` of the solver.
"""

from __future__ import annotations

import os
from typing import Any

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


def _the_model(solver: Any) -> Any:
    """Return the ``Model`` from a solver object, or the object itself.

    A solver object (a ``ModflowNwt``) keeps the frozen ``Model`` of the run
    on ``inputs``. The transport adapters receive the ``Model`` itself, so the
    resolvers accept both shapes and read ``Model.geometry`` either way.
    """
    return getattr(solver, "inputs", None) or solver


def get_raster(model: Any) -> Any:
    """Return the DEM grid the run was built on, or None.

    It is ``Model.geometry.raster`` of the ``Model`` the transport follows.
    The DEM raster paths and the CRS of the delineation are its attributes.
    """
    geometry = getattr(_the_model(model), "geometry", None)
    return getattr(geometry, "raster", None)


def get_catchment(model: Any) -> Any:
    """Return where the catchment of the run closes, or None.

    It is ``Model.geometry.catchment``, which holds the watershed polygon path.
    """
    geometry = getattr(_the_model(model), "geometry", None)
    return getattr(geometry, "catchment", None)


def resolve_crs_proj(model: Any, domain: Any) -> Any:
    """Resolve CRS from the DEM grid of the model, else from domain support."""
    raster = get_raster(model)
    if raster is not None:
        return raster.crs_proj
    support = getattr(getattr(domain, "surface_topo", None), "support", None)
    if support is not None:
        return getattr(support, "crs", None)
    return None


def resolve_watershed_shp(model: Any) -> str | None:
    """Resolve watershed polygon path when available."""
    catchment = get_catchment(model)
    return getattr(catchment, "watershed_shp", None) if catchment is not None else None


def resolve_domain_raster(model_modflow: Any) -> str:
    """Resolve default domain raster path for particle injection.

    The solver grid when the model wrote its template, because the injection mask
    is read by MODFLOW row and column: a raster on the DEM grid fits a model only
    when ``cell_size`` is the DEM resolution.
    """
    raster = get_raster(model_modflow)
    raster_path = getattr(model_modflow, "dem_watershed_path", None) or (
        getattr(raster, "watershed_box_buff_dem", None) if raster is not None else None
    )
    if raster_path is None:
        raise ValueError(
            "Cannot resolve default zone_partic='domain'. "
            "Write [transport.modpath] zone_partic with the path of a raster "
            "aligned on the solver grid."
        )
    return raster_path


def resolve_seepage_clip_raster(*, full_path: str, model_modflow: Any) -> str:
    """Build and return clipped seepage raster path for particle injection."""
    from hydromodpy.catchment.delineation import get_whitebox_backend

    seepage_tif = os.path.join(
        full_path,
        "_postprocess",
        "_rasters",
        "seepage_areas_t(0).tif",
    )
    if not os.path.isfile(seepage_tif):
        raise FileNotFoundError(
            f"zone_partic='seepage_clip' requested but missing seepage raster at {seepage_tif}."
        )

    watershed_shp = resolve_watershed_shp(model_modflow)
    if watershed_shp is None:
        logger.warning(
            "zone_partic='seepage_clip' requested but watershed polygon is unavailable; "
            "using raw seepage raster %s.",
            seepage_tif,
        )
        return seepage_tif

    seepage_clip_tif = os.path.join(
        full_path,
        "_postprocess",
        "_rasters",
        "seepage_areas_t(0)_clip.tif",
    )
    try:
        get_whitebox_backend().raster.clip_raster_to_polygon(
            str(seepage_tif),
            str(watershed_shp),
            str(seepage_clip_tif),
            maintain_dimensions=True,
        )
    except Exception as exc:
        logger.warning(
            "Failed to build clipped seepage raster for zone_partic='seepage_clip'; "
            "using raw seepage raster %s instead. Error: %s",
            seepage_tif,
            exc,
        )
        return seepage_tif
    return seepage_clip_tif


def resolve_zone_partic(
    zone_partic_val: str | None,
    *,
    full_path: str,
    model_modflow: Any,
) -> str | None:
    """Resolve ``zone_partic`` aliases to concrete raster paths."""
    if zone_partic_val == "domain":
        return resolve_domain_raster(model_modflow)
    if zone_partic_val == "seepage_clip":
        return resolve_seepage_clip_raster(full_path=full_path, model_modflow=model_modflow)
    return zone_partic_val


def ensure_modflow_name_file(
    *,
    full_path: str,
    model_name: str,
    model_modflow: Any,
) -> str:
    """Ensure the paired MODFLOW-NWT name file exists before loading it."""
    mf = getattr(model_modflow, "mf", None)
    namefile = getattr(mf, "namefile", f"{model_name}.nam")
    nam_file = os.path.join(full_path, namefile)
    if os.path.exists(nam_file):
        return nam_file

    if mf is None:
        raise FileNotFoundError(f"cannot find name file: {nam_file}")

    mf.model_ws = full_path
    mf.write_name_file()
    if os.path.exists(nam_file):
        return nam_file

    raise FileNotFoundError(f"cannot find name file: {nam_file}")
