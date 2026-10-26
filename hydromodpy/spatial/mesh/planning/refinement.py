"""Read the ``[[mesh.refinement_zone]]`` tables as regions with a cell size.

A table with ``path`` reads a vector layer. A table with ``where`` draws its
region on the pixels of the DEM grid where a field passes a threshold: the
height above the stream (``height_above_stream.py``), or a field of an
earlier run (``run_fields.py``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.mesh.refinement.height_above_stream import (
    height_above_stream,
    stream_pixels,
)
from hydromodpy.spatial.mesh.refinement.refinement_zones import RefinementZoneConfig
from hydromodpy.spatial.mesh.refinement.run_fields import RunFieldEnvelope, cells_on_grid
from hydromodpy.spatial.mesh.request import RasterGridSpec
from hydromodpy.spatial.mesh.sizing.size_field import PixelRegion

__all__ = ["CriterionInputs", "RefinementZone", "load_refinement_zones"]

_logger = get_logger(__name__)


@dataclass(frozen=True)
class RefinementZone:
    """A region meshed at ``cell_size_m``, the size ramping back over ``ramp_m`` outside it.

    ``label`` says in a few words what drew the region. ``source_run`` is the
    ``sim_id`` of the earlier run whose field drew it, None otherwise. A
    region drawn by a threshold may be empty: nothing passed it.
    """

    region: BaseGeometry | PixelRegion
    cell_size_m: float
    ramp_m: float
    label: str = ""
    source_run: str | None = None


@dataclass(frozen=True, eq=False)
class CriterionInputs:
    """What a zone drawn by a threshold reads.

    ``elevation`` is the DEM on ``grid`` [m]. ``stream_lines`` is the river
    network traced from the DEM, None when none was traced. ``run_fields``
    holds the field of each earlier run a zone names, by ``(run, field)`` as
    the zone writes them.
    """

    grid: RasterGridSpec
    elevation: np.ndarray
    stream_lines: tuple[LineString, ...] | None
    run_fields: Mapping[tuple[str, str], RunFieldEnvelope] = field(default_factory=dict)


def load_refinement_zones(
    cfgs: Sequence[RefinementZoneConfig],
    *,
    config_dir: Path | None,
    data_dir: Path | None,
    crs_wkt: str,
    criteria: CriterionInputs | None = None,
) -> tuple[RefinementZone, ...]:
    """Read each zone in the CRS *crs_wkt*, in the order of *cfgs*.

    A layer zone: polygons refine as they are; points and lines are dilated
    by ``buffer`` (default ``2 * cell_size``) into corridors. A bare file
    name resolves in ``<data_dir>/refinement_zone/``, then ``<data_dir>``,
    then *config_dir*. An unreadable or empty layer raises, so a
    misconfigured zone never meshes coarse in silence. A zone drawn by a
    threshold reads *criteria*; without it, for an engine that does not grade
    its cells, it is left out.
    """
    import geopandas as gpd

    zones: list[RefinementZone] = []
    height: np.ndarray | None = None
    for cfg in cfgs:
        width = float(cfg.buffer if cfg.buffer is not None else 2.0 * cfg.cell_size)
        if cfg.where is not None:
            if criteria is None:
                continue
            if cfg.where == "height_above_stream" and height is None:
                height = _height_above_stream(criteria)
            zones.append(_criterion_zone(cfg, criteria, height, ramp=width))
            continue
        path = _resolve_zone_path(Path(cfg.path), data_dir=data_dir, config_dir=config_dir)
        frame = gpd.read_file(path)
        frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty]
        if frame.empty:
            raise MeshRequestError(f"refinement zone {path} has no usable geometry")
        if frame.crs is None:
            _logger.warning("refinement zone %s has no CRS; read in the project CRS", path)
        else:
            frame = frame.to_crs(crs_wkt)
        parts = [
            geometry
            if geometry.geom_type in ("Polygon", "MultiPolygon")
            else geometry.buffer(width)
            for geometry in frame.geometry
        ]
        region = shapely.union_all(parts)
        if region.is_empty:
            raise MeshRequestError(f"refinement zone {path} gives an empty region")
        zones.append(
            RefinementZone(
                region=region,
                cell_size_m=float(cfg.cell_size),
                ramp_m=width,
                label=cfg.describe(),
            )
        )
    return tuple(zones)


def _height_above_stream(criteria: CriterionInputs) -> np.ndarray:
    """The height above the stream of every pixel of the grid, from the traced network."""
    if not criteria.stream_lines:
        raise MeshRequestError(
            "[[mesh.refinement_zone]] where = 'height_above_stream' measures the ground "
            "against the river network traced from the DEM, and none was traced. Enable "
            "[geographic.river_network] with a threshold."
        )
    grid = criteria.grid
    streams = stream_pixels(criteria.stream_lines, grid)
    return height_above_stream(criteria.elevation, streams, dx=grid.dx, dy=grid.dy)


def _criterion_zone(
    cfg: RefinementZoneConfig,
    criteria: CriterionInputs,
    height: np.ndarray | None,
    *,
    ramp: float,
) -> RefinementZone:
    """The pixels where the field of *cfg* passes its threshold."""
    grid = criteria.grid
    source_run = None
    if cfg.where == "height_above_stream":
        assert height is not None and cfg.below is not None
        with np.errstate(invalid="ignore"):
            mask = np.isfinite(height) & (height < cfg.below)
    else:
        assert cfg.run is not None and cfg.where is not None
        envelope = criteria.run_fields.get((cfg.run, cfg.where))
        if envelope is None:
            raise MeshRequestError(
                f"[[mesh.refinement_zone]] where = {cfg.where!r} names run {cfg.run!r}, "
                "and the mesh step read no such field"
            )
        selected = envelope.passing(below=cfg.below, above=cfg.above)
        mask = cells_on_grid(envelope.vertices, envelope.connectivity, selected, grid)
        source_run = envelope.sim_id
    label = cfg.describe()
    if not mask.any():
        _logger.warning("refinement zone %s selects no pixel: it refines nothing", label)
    return RefinementZone(
        region=PixelRegion(mask=mask, grid=grid),
        cell_size_m=float(cfg.cell_size),
        ramp_m=ramp,
        label=label,
        source_run=source_run,
    )


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
