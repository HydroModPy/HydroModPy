"""Geographic and zone-partic resolvers for the MODPATH backend."""

from __future__ import annotations

import os
from typing import Any

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


def get_geographic(model_modflow: Any) -> Any:
    """Return geographic context from MODFLOW model when available."""
    return getattr(model_modflow, "geographic", None)


def resolve_crs_proj(model_modflow: Any, domain: Any) -> Any:
    """Resolve CRS from geographic context, else from domain support."""
    geo = get_geographic(model_modflow)
    if geo is not None and hasattr(geo, "crs_proj"):
        return geo.crs_proj
    support = getattr(getattr(domain, "surface_topo", None), "support", None)
    if support is not None:
        return getattr(support, "crs", None)
    return None


def resolve_watershed_shp(model_modflow: Any) -> str | None:
    """Resolve watershed polygon path when available."""
    geo = get_geographic(model_modflow)
    return getattr(geo, "watershed_shp", None) if geo is not None else None


def resolve_domain_raster(model_modflow: Any) -> str:
    """Resolve default domain raster path for particle injection."""
    geo = get_geographic(model_modflow)
    raster_path = getattr(geo, "watershed_box_buff_dem", None) if geo is not None else None
    if raster_path is None:
        raise ValueError(
            "Cannot resolve default zone_partic='domain'. "
            "Provide transport.modpath.parameters.zone_partic as a raster path."
        )
    return raster_path


def resolve_seepage_clip_raster(*, full_path: str, model_modflow: Any) -> str:
    """Build and return clipped seepage raster path for particle injection."""
    from hydromodpy.spatial.delineation import get_whitebox_backend

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


def crs_for_write_from_proj(crs: object | None) -> tuple[object | None, int | None]:
    """Normalize a CRS proj definition into ``(crs_for_write, epsg)``."""
    if isinstance(crs, (int, float)):
        epsg: int | None = int(crs)
    elif isinstance(crs, str) and crs[:4].upper() == "EPSG":
        epsg = int(crs.split(":")[-1])
    else:
        epsg = None
    crs_for_write = crs if crs is not None else (f"EPSG:{epsg}" if epsg is not None else None)
    return crs_for_write, epsg
