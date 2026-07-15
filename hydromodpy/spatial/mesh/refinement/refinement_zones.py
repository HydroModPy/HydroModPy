"""User-provided zones of interest for local mesh refinement.

Each ``[[mesh_catchment.refinement_zone]]`` entry names a vector layer
(gpkg / shp / GeoJSON) and a target cell size. Polygon features refine as
zones; point and line features are dilated by ``buffer`` into corridors.
All features of one entry merge into one GMSH regional size field that
ramps back to the background size over ``buffer``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import NonEmptyStr

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["RefinementZoneConfig", "build_refinement_zone_size_fields"]


class RefinementZoneConfig(HydroModelBase):
    """One user-provided refinement zone layer."""

    path: Annotated[NonEmptyStr, Profile.USER] = Field(
        description=(
            "Vector layer (gpkg / shp / GeoJSON) of polygons (zones) and/or "
            "points or lines (corridors). A bare filename resolves against "
            "<workspace>/data/refinement_zone/; relative paths resolve against "
            "that directory, the data directory, then the config directory."
        ),
    )
    cell_size: Annotated[float, Profile.USER] = Field(
        gt=0.0,
        description="Target cell size [L] inside the zone.",
    )
    buffer: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "Corridor half-width [L] for point / line features, and transition "
            "distance back to the background size. When omitted, derives 2 * cell_size. "
            "Must be >= cell_size so the corridor holds at least one target cell."
        ),
    )

    @model_validator(mode="after")
    def _validate_buffer(self) -> RefinementZoneConfig:
        if self.buffer is not None and self.buffer < self.cell_size:
            raise ValueError(
                "buffer must be >= cell_size: a corridor thinner than one target "
                "cell slips between the size-field sampling nodes and silently "
                "meshes at the background size."
            )
        return self


def _resolve_zone_path(raw_path: str, *, data_dir: object | None, config_dir: Path | None) -> Path:
    resolved = Path(str(raw_path)).expanduser()
    if resolved.is_absolute():
        return resolved
    candidate_dirs = []
    if data_dir is not None:
        candidate_dirs.extend([Path(data_dir) / "refinement_zone", Path(data_dir)])
    if config_dir is not None:
        candidate_dirs.append(Path(config_dir))
    for base in candidate_dirs:
        candidate = (base / resolved).resolve()
        if candidate.exists():
            return candidate
    if candidate_dirs:
        return (candidate_dirs[0] / resolved).resolve()
    return resolved


def build_refinement_zone_size_fields(
    *,
    zones: Sequence[RefinementZoneConfig],
    global_size: float,
    target_crs: object | None,
    data_dir: object | None = None,
    config_dir: Path | None = None,
) -> tuple:
    """Return one GMSH regional size field per configured refinement zone.

    Each zone layer is read with geopandas, reprojected to ``target_crs`` when
    both CRS are known, and merged into one region geometry: polygons as-is,
    points and lines dilated by the zone ``buffer``. An unreadable or empty
    layer raises so a misconfigured zone never silently meshes coarse.
    """
    if not zones:
        return ()

    import geopandas as gpd
    from shapely.ops import unary_union

    from hydromodpy.core.logging import get_logger
    from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.contracts import (
        ZoneRegionalSizeField,
    )

    logger = get_logger(__name__)
    fields: list = []
    for index, zone in enumerate(zones):
        zone_path = _resolve_zone_path(zone.path, data_dir=data_dir, config_dir=config_dir)
        gdf = gpd.read_file(str(zone_path))
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
        if gdf.empty:
            raise ValueError(f"refinement zone '{zone_path}' has no usable geometry.")
        if target_crs is None:
            if gdf.crs is not None:
                logger.warning(
                    "refinement zone '%s': no project CRS available, the layer is used "
                    "in its source CRS (%s); a mismatched zone lands outside the domain "
                    "and is skipped.",
                    zone_path,
                    gdf.crs,
                )
        elif gdf.crs is None:
            logger.warning(
                "refinement zone '%s' has no CRS; assuming it is already in the project CRS.",
                zone_path,
            )
        elif gdf.crs != target_crs:
            gdf = gdf.to_crs(target_crs)

        width = float(zone.buffer if zone.buffer is not None else 2.0 * zone.cell_size)
        parts = [
            geom if geom.geom_type in ("Polygon", "MultiPolygon") else geom.buffer(width)
            for geom in gdf.geometry
        ]
        region = unary_union(parts)
        if region.is_empty:
            raise ValueError(f"refinement zone '{zone_path}' produced an empty region.")
        fields.append(
            ZoneRegionalSizeField(
                name=f"zone::{index}:{zone_path.stem}",
                region_geometry=region,
                inside_size=float(zone.cell_size),
                outside_size=float(global_size),
                transition_distance=width,
                grid_resolution=float(min(zone.cell_size, global_size)),
            )
        )
    return tuple(fields)
