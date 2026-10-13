"""Read the ``[[mesh.refinement_zone]]`` layers as regions with a cell size."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import shapely
from shapely.geometry.base import BaseGeometry

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.mesh.refinement.refinement_zones import RefinementZoneConfig

__all__ = ["RefinementZone", "load_refinement_zones"]

_logger = get_logger(__name__)


@dataclass(frozen=True)
class RefinementZone:
    """A region meshed at ``cell_size_m``, the size ramping back over ``ramp_m`` outside it."""

    region: BaseGeometry
    cell_size_m: float
    ramp_m: float


def load_refinement_zones(
    cfgs: Sequence[RefinementZoneConfig],
    *,
    config_dir: Path | None,
    data_dir: Path | None,
    crs_wkt: str,
) -> tuple[RefinementZone, ...]:
    """Read each zone layer in the CRS *crs_wkt*.

    Polygons refine as they are; points and lines are dilated by ``buffer``
    (default ``2 * cell_size``) into corridors. A bare file name resolves in
    ``<data_dir>/refinement_zone/``, then ``<data_dir>``, then *config_dir*.
    An unreadable or empty layer raises, so a misconfigured zone never meshes
    coarse in silence.
    """
    import geopandas as gpd

    zones: list[RefinementZone] = []
    for cfg in cfgs:
        path = _resolve_zone_path(Path(cfg.path), data_dir=data_dir, config_dir=config_dir)
        frame = gpd.read_file(path)
        frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty]
        if frame.empty:
            raise MeshRequestError(f"refinement zone {path} has no usable geometry")
        if frame.crs is None:
            _logger.warning("refinement zone %s has no CRS; read in the project CRS", path)
        else:
            frame = frame.to_crs(crs_wkt)
        width = float(cfg.buffer if cfg.buffer is not None else 2.0 * cfg.cell_size)
        parts = [
            geometry
            if geometry.geom_type in ("Polygon", "MultiPolygon")
            else geometry.buffer(width)
            for geometry in frame.geometry
        ]
        region = shapely.union_all(parts)
        if region.is_empty:
            raise MeshRequestError(f"refinement zone {path} gives an empty region")
        zones.append(RefinementZone(region=region, cell_size_m=float(cfg.cell_size), ramp_m=width))
    return tuple(zones)


def _resolve_zone_path(raw: Path, *, data_dir: Path | None, config_dir: Path | None) -> Path:
    """The first existing candidate, or the first candidate when none exists."""
    path = raw.expanduser()
    if path.is_absolute():
        return path
    bases = []
    if data_dir is not None:
        bases.extend([Path(data_dir) / "refinement_zone", Path(data_dir)])
    if config_dir is not None:
        bases.append(Path(config_dir))
    for base in bases:
        candidate = (base / path).resolve()
        if candidate.exists():
            return candidate
    if not bases:
        return path
    return (bases[0] / path).resolve()
