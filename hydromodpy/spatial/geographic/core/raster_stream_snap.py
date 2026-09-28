"""Snap the mapped stream network onto the talwegs of the raster routing DEM.

``[geographic.snap_streams]`` applies to every consumer of the mapped network.
The stream burn cuts its trench into the raster routing DEM before any mesh
exists, so the snap it needs runs on the raster grid: the raw DEM is
conditioned by the configured ``dem_correc_type`` and terrain engine, and the
rasterised map is snapped on the eight-neighbour graph of that raster by
:func:`hydromodpy.core.stream_snap.snap_observed_network_on_grid`, the same
algorithm and the same radius rule as the criterion.

The pass is published in the geographic directory: the indices, the mode and
the mapped file it read in ``stream_snap_raster.json``, the snapped map and the
status of every cell in ``stream_snap_raster.tif``, and the snapped map as
lines in ``stream_snap_raster_lines.gpkg``, which a mesh river constraint
reading the same mapped file takes in ``apply`` mode.

This snap and the criterion's are two independent passes over the same raw
map. This one reads the conditioned raster at its own resolution and radius;
the criterion snaps the raw map again on the mesh graph, filled from the
unburned model top, with the radius counted in mesh cells. Near a meander or
a confluence on a mesh coarser than the DEM, they can pick different talwegs
for one reach: the burn and the mesh river trace then follow one, and Eq. 4
scores the other. Nothing compares the two yet, so compare
``stream_snap_raster.tif`` with the criterion's snapped map before trusting
``apply`` on a coarse mesh.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio

from hydromodpy.core.logging import get_logger
from hydromodpy.core.stream_snap import (
    GridStreamSnap,
    SnapStreamsConfig,
    snap_observed_network_on_grid,
)
from hydromodpy.spatial.geographic.core.flow_products import build_regional_flow_products

logger = get_logger(__name__)

RASTER_SNAP_WORK_DIR = "stream_snap"
"""Directory, under the flow directory, of the conditioning pass the snap reads."""

RASTER_SNAP_MANIFEST = "stream_snap_raster.json"
RASTER_SNAP_RASTER = "stream_snap_raster.tif"
RASTER_SNAP_LINES = "stream_snap_raster_lines.gpkg"


def raster_snap_settings(config: object) -> SnapStreamsConfig | None:
    """Return the snap setting when the raster pass runs, None otherwise.

    It runs when ``[geographic.snap_streams]`` is on and
    ``[geographic.enforce_streams]`` names the mapped network, burning or not:
    the burn reads it, and so may a mesh river constraint.
    """
    snap = getattr(config, "snap_streams", None)
    enforce = getattr(config, "enforce_streams", None)
    if snap is None or not getattr(snap, "enabled", False) or enforce is None:
        return None
    if getattr(enforce, "stream_geometry_path", None) is None:
        return None
    return snap


@dataclass(frozen=True)
class RasterStreamSnap:
    """The raster snap of the mapped network, and where it was published."""

    mode: str
    raw_mask: np.ndarray
    snapped_mask: np.ndarray
    grid: GridStreamSnap
    manifest_path: Path
    raster_path: Path
    lines_path: Path | None

    @property
    def burn_mask(self) -> np.ndarray:
        """The cells the burn lowers: the snapped map in ``apply``, the raw one otherwise."""
        return self.snapped_mask if self.mode == "apply" else self.raw_mask

    @property
    def indices(self) -> dict[str, float]:
        """The indices of the snap, under the names a trial publishes them."""
        return self.grid.snap.indices


def snapped_segments(grid: GridStreamSnap) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Return the receiver links between snapped cells, centre to centre.

    The snapped map is a union of descent paths, so each snapped cell whose
    receiver is snapped too is one segment of it. A rejected cell left alone
    at its raw position draws no segment.
    """
    snapped = np.asarray(grid.snap.snapped, dtype=bool)
    receivers = np.asarray(grid.metric.graph.downstream, dtype=int)
    centres = np.asarray(grid.metric.centroids, dtype=float)
    cells = np.flatnonzero(snapped & (receivers >= 0))
    cells = cells[snapped[receivers[cells]]]
    return [
        (
            (float(centres[cell, 0]), float(centres[cell, 1])),
            (float(centres[receivers[cell], 0]), float(centres[receivers[cell], 1])),
        )
        for cell in cells.tolist()
    ]


def _write_lines(grid: GridStreamSnap, path: Path, crs: object | None) -> Path | None:
    import geopandas as gpd
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import linemerge

    segments = snapped_segments(grid)
    if not segments:
        return None
    merged = linemerge(MultiLineString([LineString(segment) for segment in segments]))
    parts = list(getattr(merged, "geoms", [merged]))
    path.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame({"part": np.arange(len(parts))}, geometry=parts, crs=crs).to_file(
        path, driver="GPKG"
    )
    return path


def _write_raster(grid: GridStreamSnap, path: Path, profile: dict[str, Any]) -> None:
    layout = dict(profile)
    for key in ("blockxsize", "blockysize", "nodata"):
        layout.pop(key, None)
    layout.update(dtype="uint8", count=2, compress="lzw", tiled=False, nodata=None)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **layout) as dst:
        dst.write(grid.as_grid(grid.snap.snapped).astype("uint8"), 1)
        dst.write(grid.as_grid(grid.snap.status).astype("uint8"), 2)
        dst.set_band_description(1, "snapped")
        dst.set_band_description(2, "status")


def _json_number(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None


def snap_streams_on_raster(
    *,
    dem_in_path: str | Path,
    raw_mask: np.ndarray,
    settings: SnapStreamsConfig,
    dem_correc_type: str,
    work_dir: Path,
    geographic_dir: Path,
    source_path: Path,
    crs_project: str | None = None,
    backend: object | None = None,
    engine_id: str | None = None,
) -> RasterStreamSnap:
    """Snap the rasterised mapped network on the conditioned raw DEM and publish it.

    ``raw_mask`` is the mapped network on the grid of ``dem_in_path``, as the
    burn rasterises it. The DEM is conditioned by ``dem_correc_type`` into
    ``work_dir/stream_snap``, then snapped on (module docstring).
    ``source_path`` is the mapped file, recorded so a consumer can tell
    whether it reads the map that was snapped.
    """
    conditioned = build_regional_flow_products(
        dem_init_path=dem_in_path,
        dem_out_dir_path=Path(work_dir) / RASTER_SNAP_WORK_DIR,
        dem_correc_type=dem_correc_type,
        crs_project=crs_project,
        backend=backend,
        engine_id=engine_id,
    )
    with rasterio.open(conditioned.correc) as src:
        surface = src.read(1).astype("float64")
        transform = src.transform
        profile = src.profile
        crs = src.crs
        if src.nodata is not None:
            surface[surface == float(src.nodata)] = np.nan
    mapped = np.asarray(raw_mask, dtype=bool)
    if mapped.shape != surface.shape:
        raise ValueError(
            f"the conditioned DEM lies on a {surface.shape} grid and the mapped network on "
            f"{mapped.shape}: the terrain engine changed the grid of the raw DEM."
        )
    grid = snap_observed_network_on_grid(
        surface=surface,
        observed=mapped,
        x_origin=float(transform.c),
        y_origin=float(transform.f),
        dx=float(transform.a),
        dy=float(transform.e),
        settings=settings,
    )
    snapped = grid.as_grid(grid.snap.snapped).astype(bool)

    geographic_dir = Path(geographic_dir)
    raster_path = geographic_dir / RASTER_SNAP_RASTER
    _write_raster(grid, raster_path, profile)
    lines_path = _write_lines(grid, geographic_dir / RASTER_SNAP_LINES, crs_project or crs)
    manifest_path = geographic_dir / RASTER_SNAP_MANIFEST
    indices = grid.snap.indices
    manifest = {
        "mode": settings.mode,
        "settings": settings.model_dump(mode="json"),
        "source_path": str(Path(source_path).expanduser().resolve()),
        "dem_correc_type": str(dem_correc_type),
        "raster_path": str(raster_path),
        "lines_path": None if lines_path is None else str(lines_path),
        "indices": {key: _json_number(value) for key, value in indices.items()},
    }
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    logger.info(
        "Stream snap on the raster (%s, %s-conditioned DEM): radius %.4g m, %d mapped cell(s), "
        "p90 displacement %.4g m, %.1f%% rejected, length ratio %.3f; the burn %s. "
        "Written to %s.",
        settings.mode,
        dem_correc_type,
        grid.snap.radius_m,
        int(grid.snap.raw.sum()),
        grid.snap.displacement_p90_m,
        100.0 * grid.snap.rejected_share,
        grid.snap.length_ratio,
        "reads the snapped map" if settings.mode == "apply" else "reads the raw map",
        manifest_path,
    )
    if settings.mode == "apply" and not grid.snap.within_bounds:
        logger.warning(
            "Stream snap on the raster: the p90 displacement (%.4g m) or the rejected share "
            "(%.1f%%) exceeds its bound (%.4g m, %.1f%%). The burn follows the snapped map "
            "anyway; check the mapped network against the DEM.",
            grid.snap.displacement_p90_m,
            100.0 * grid.snap.rejected_share,
            grid.snap.displacement_bound_m,
            100.0 * grid.snap.rejected_share_max,
        )
    return RasterStreamSnap(
        mode=settings.mode,
        raw_mask=mapped,
        snapped_mask=snapped,
        grid=grid,
        manifest_path=manifest_path,
        raster_path=raster_path,
        lines_path=lines_path,
    )


def read_raster_snap_manifest(geographic_dir: str | Path) -> dict[str, Any] | None:
    """Return the manifest of the raster snap in ``geographic_dir``, None without one."""
    path = Path(geographic_dir) / RASTER_SNAP_MANIFEST
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_raster_snapped_mask(manifest: dict[str, Any]) -> np.ndarray:
    """Return the snapped map a manifest points to, as a boolean raster."""
    with rasterio.open(str(manifest["raster_path"])) as src:
        return src.read(1).astype(bool)


def snapped_lines_for_mapped_file(
    mapped_path: str | Path, geographic_dir: str | Path | None
) -> Path | None:
    """Return the snapped lines to read in place of ``mapped_path``, or None.

    None means the raw file is read: no raster snap was published, it snapped
    another file, or it ran in ``diagnose``. In ``apply`` a snap with no line
    to draw is refused rather than silently replaced by the raw map.
    """
    if geographic_dir is None:
        return None
    manifest = read_raster_snap_manifest(geographic_dir)
    if manifest is None:
        return None
    mapped = Path(mapped_path).expanduser().resolve()
    if Path(str(manifest.get("source_path", ""))) != mapped:
        logger.info(
            "The raster stream snap read %s, not %s: the mesh river constraint reads its "
            "file as it is.",
            manifest.get("source_path"),
            mapped,
        )
        return None
    if manifest.get("mode") != "apply":
        logger.info(
            "Stream snap in %s mode: the mesh river constraint reads the raw map %s.",
            manifest.get("mode"),
            mapped,
        )
        return None
    lines = manifest.get("lines_path")
    if not lines or not Path(lines).is_file():
        raise ValueError(
            f"[geographic.snap_streams] mode = 'apply', but the raster snap of {mapped} "
            "published no snapped line for the mesh river constraint."
        )
    logger.info("The mesh river constraint follows the snapped map %s.", lines)
    return Path(lines)


__all__ = (
    "RASTER_SNAP_LINES",
    "RASTER_SNAP_MANIFEST",
    "RASTER_SNAP_RASTER",
    "RASTER_SNAP_WORK_DIR",
    "RasterStreamSnap",
    "raster_snap_settings",
    "read_raster_snap_manifest",
    "read_raster_snapped_mask",
    "snap_streams_on_raster",
    "snapped_lines_for_mapped_file",
    "snapped_segments",
)
