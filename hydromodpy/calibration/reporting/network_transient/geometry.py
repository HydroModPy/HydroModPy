"""Mesh geometry, origin resolution and cell-drain rendering helpers.

Leaf module: it reads the live runtime configuration through
``state.report_facade()`` (deferred, call-time) so it never imports the
``network_transient_html`` facade at module load.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.calibration.reporting.network_transient import io as _nt_io
from hydromodpy.calibration.reporting.network_transient import state as _state
from hydromodpy.results.run import Run

_read_csv = _nt_io.read_csv
_read_json = _nt_io.read_json
_read_toml = _nt_io.read_toml
_float = _nt_io.coerce_float


def _mesh_context_from_truth_package(truth_dir: Path) -> dict[str, Any] | None:
    metadata = _read_json(truth_dir / "metadata.json")
    bundle = _score_file_path(metadata.get("mesh_bundle", ""))
    if bundle is None or not bundle.is_dir():
        return _mesh_context_from_cell_geometry(truth_dir)
    nodes_path = bundle / "nodes.csv"
    cells_path = bundle / "cells.csv"
    if not nodes_path.is_file() or not cells_path.is_file():
        return _mesh_context_from_cell_geometry(truth_dir)
    try:
        node_rows = _read_csv(nodes_path)
        cell_rows = sorted(
            _read_csv(cells_path),
            key=lambda row: int(float(str(row.get("cell_id", "0") or "0"))),
        )
        nodes = {
            int(float(row["node_id"])): (
                float(row["x"]),
                float(row["y"]),
            )
            for row in node_rows
        }
        polygons: list[np.ndarray] = []
        topo_values: list[float] = []
        for row in cell_rows:
            node_ids = []
            for raw in _cell_node_id_values(row):
                node_ids.append(int(float(raw)))
            if len(node_ids) < 3:
                return None
            polygons.append(np.asarray([nodes[node_id] for node_id in node_ids], dtype=float))
            topo_values.append(_float(row.get("z_top_mean"), _float(row.get("z_top_centroid"))))
        geometry = np.load(truth_dir / "cell_geometry.npz")
        try:
            centroids = np.asarray(geometry["centroids"], dtype=float)
        finally:
            geometry.close()
        origin = _origin_from_config_or_centroids(centroids)
        return {
            "origin": origin,
            "polygons": _relative_polygons(polygons, origin),
            "cell_topography": np.asarray(topo_values, dtype=float),
        }
    except Exception:
        return _mesh_context_from_cell_geometry(truth_dir)


def _mesh_context_from_cell_geometry(truth_dir: Path) -> dict[str, Any] | None:
    geometry_path = truth_dir / "cell_geometry.npz"
    if not geometry_path.is_file():
        return None
    try:
        with np.load(geometry_path) as geometry:
            centroids = np.asarray(geometry["centroids"], dtype=float)
            areas = np.asarray(geometry["cell_area"], dtype=float).reshape(-1)
    except Exception:
        return None
    if centroids.ndim != 2 or centroids.shape[1] < 2 or centroids.shape[0] != areas.size:
        return None
    origin = _origin_from_config_or_centroids(centroids)
    polygons: list[np.ndarray] = []
    for (x, y), area in zip(centroids[:, :2], areas, strict=False):
        half_size = max(float(np.sqrt(area)) * 0.5, 1.0)
        polygons.append(
            np.asarray(
                [
                    [x - half_size, y - half_size],
                    [x + half_size, y - half_size],
                    [x + half_size, y + half_size],
                    [x - half_size, y + half_size],
                ],
                dtype=float,
            )
        )
    return {
        "origin": origin,
        "polygons": _relative_polygons(polygons, origin),
        "cell_topography": np.zeros(areas.size, dtype=float),
    }


def _origin_from_config_or_centroids(centroids: np.ndarray) -> tuple[float, float]:
    geographic = _read_toml(_state.report_facade().SOURCE_TRANSIENT_CONFIG).get("geographic", {})
    if isinstance(geographic, dict):
        catchment = geographic.get("catchment")
        if not isinstance(catchment, dict):
            catchment = {}
        x = _float(catchment.get("x_outlet"))
        y = _float(catchment.get("y_outlet"))
        if np.isfinite(x) and np.isfinite(y):
            return float(x), float(y)
    if centroids.size:
        return float(np.nanmean(centroids[:, 0])), float(np.nanmean(centroids[:, 1]))
    return 0.0, 0.0


def _polygon_bounds(polygons: list[np.ndarray]) -> tuple[float, float, float, float] | None:
    if not polygons:
        return None
    vertices = np.vstack([np.asarray(poly, dtype=float) for poly in polygons])
    if vertices.size == 0:
        return None
    margin = 0.06
    return (
        float(np.nanmin(vertices[:, 0])) - margin,
        float(np.nanmin(vertices[:, 1])) - margin,
        float(np.nanmax(vertices[:, 0])) + margin,
        float(np.nanmax(vertices[:, 1])) + margin,
    )


def _safe_geographic(run: Run, feature_name: str) -> Any | None:
    try:
        return run.geographic(feature_name)
    except Exception:
        return None


def _topography_context(run: Run, origin: tuple[float, float]) -> dict[str, Any] | None:
    try:
        raster = run.geographic_raster("watershed_dem")
    except Exception:
        return None
    data = np.asarray(raster.data, dtype=float)
    nodata = raster.nodata
    if nodata is not None:
        data = np.ma.masked_where(data == float(nodata), data)
    data = np.ma.masked_invalid(data)
    a, _, c, _, e, f = tuple(float(value) for value in raster.transform[:6])
    nrow, ncol = data.shape
    x0 = c
    x1 = c + a * ncol
    y0 = f
    y1 = f + e * nrow
    ox, oy = origin
    extent = [
        (min(x0, x1) - ox) / 1000.0,
        (max(x0, x1) - ox) / 1000.0,
        (min(y0, y1) - oy) / 1000.0,
        (max(y0, y1) - oy) / 1000.0,
    ]
    return {"data": data, "extent": extent}


def _plot_topography(ax: Any, topo: dict[str, Any] | None, *, clip_patch: Any = None) -> Any:
    if topo is None:
        return None
    image = ax.imshow(
        topo["data"],
        extent=topo["extent"],
        origin="upper",
        cmap="terrain",
        alpha=0.42,
        zorder=0,
    )
    if clip_patch is not None:
        image.set_clip_path(clip_patch)
    return image


def _drain_facecolors(drain: np.ndarray, *, threshold: float, cmap: Any, norm: Any) -> np.ndarray:
    values = np.asarray(drain, dtype=float).reshape(-1)
    colors = np.zeros((values.size, 4), dtype=float)
    inactive = values <= threshold
    colors[inactive] = (0.96, 0.97, 0.98, 0.16)
    active = ~inactive & np.isfinite(values)
    if np.any(active):
        colors[active] = cmap(norm(values[active]))
        colors[active, 3] = 0.88
    return colors


def _relative_gdf_bounds(
    gdf: Any | None, origin: tuple[float, float]
) -> tuple[float, float, float, float] | None:
    if gdf is None or len(gdf) == 0:
        return None
    bounds = np.asarray(gdf.total_bounds, dtype=float)
    ox, oy = origin
    margin = 0.06
    return (
        (bounds[0] - ox) / 1000.0 - margin,
        (bounds[1] - oy) / 1000.0 - margin,
        (bounds[2] - ox) / 1000.0 + margin,
        (bounds[3] - oy) / 1000.0 + margin,
    )


def _watershed_clip_patch(gdf: Any | None, origin: tuple[float, float], ax: Any) -> Any | None:
    if gdf is None or len(gdf) == 0:
        return None
    geom = gdf.geometry.iloc[0]
    if geom.geom_type == "MultiPolygon":
        geom = max(geom.geoms, key=lambda item: item.area)
    if geom.geom_type != "Polygon":
        return None
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MplPath

    coords = (np.asarray(geom.exterior.coords, dtype=float) - np.asarray(origin)) / 1000.0
    codes = np.full(coords.shape[0], MplPath.LINETO, dtype=np.uint8)
    codes[0] = MplPath.MOVETO
    codes[-1] = MplPath.CLOSEPOLY
    return PathPatch(MplPath(coords, codes), transform=ax.transData, facecolor="none")


def _plot_geographic_lines(
    ax: Any,
    gdf: Any | None,
    origin: tuple[float, float],
    *,
    color: str,
    lw: float,
    alpha: float,
) -> None:
    if gdf is None or len(gdf) == 0:
        return
    offset = np.asarray(origin, dtype=float)
    for geom in gdf.geometry:
        for coords in _iter_geometry_line_coords(geom):
            rel = (np.asarray(coords, dtype=float) - offset) / 1000.0
            ax.plot(rel[:, 0], rel[:, 1], color=color, lw=lw, alpha=alpha, zorder=5)


def _iter_geometry_line_coords(geom: Any):
    if geom is None or geom.is_empty:
        return
    geom_type = geom.geom_type
    if geom_type in {"LineString", "LinearRing"}:
        yield np.asarray(geom.coords, dtype=float)
    elif geom_type == "Polygon":
        yield np.asarray(geom.exterior.coords, dtype=float)
        for ring in geom.interiors:
            yield np.asarray(ring.coords, dtype=float)
    elif geom_type.startswith("Multi") or geom_type == "GeometryCollection":
        for item in geom.geoms:
            yield from _iter_geometry_line_coords(item)


def _first_non_truth_candidate(score_rows: list[dict[str, str]]) -> dict[str, str] | None:
    for row in score_rows:
        if not _candidate_is_truth(row) and row.get("status") == "completed":
            return row
    return None


def _mesh_polygons(run: Run) -> list[np.ndarray]:
    vertices = np.asarray(run.mesh.vertices)
    faces = np.asarray(run.mesh.face_node_connectivity)
    polygons = []
    for row in faces:
        nodes = row[row >= 0] if row.dtype.kind in "iu" else row[~np.isnan(row)]
        polygons.append(vertices[nodes.astype(int)][:, :2])
    return polygons


def _relative_origin(run: Run, centroids: np.ndarray) -> tuple[float, float]:
    try:
        x, y = run.outlet
        return float(x), float(y)
    except Exception:
        pass
    geographic = _read_toml(_state.report_facade().SOURCE_TRANSIENT_CONFIG).get("geographic", {})
    if isinstance(geographic, dict):
        catchment = geographic.get("catchment")
        if not isinstance(catchment, dict):
            catchment = {}
        x = _float(catchment.get("x_outlet"))
        y = _float(catchment.get("y_outlet"))
        if np.isfinite(x) and np.isfinite(y):
            return float(x), float(y)
    if centroids.size:
        return float(np.nanmean(centroids[:, 0])), float(np.nanmean(centroids[:, 1]))
    return 0.0, 0.0


def _relative_polygons(polygons: list[np.ndarray], origin: tuple[float, float]) -> list[np.ndarray]:
    offset = np.asarray(origin, dtype=float)
    return [(np.asarray(poly, dtype=float) - offset) / 1000.0 for poly in polygons]


def _candidate_is_truth(row: dict[str, str]) -> bool:
    candidate_id = str(row.get("candidate_id", ""))
    return candidate_id == "truth_identity" or candidate_id.startswith("truth")


def _cell_node_id_values(row: dict[str, Any]) -> list[str]:
    """Return one cell's node-id strings, variable arity, empty slots dropped.

    Honors the ``ncvert`` count when present (Voronoi/PEBI bundles) and otherwise
    scans every ``n<k>`` column so legacy fixed ``n0..n3`` files still load.
    """
    ncvert_raw = str(row.get("ncvert", "") or "").strip()
    if ncvert_raw:
        count = int(float(ncvert_raw))
        keys = [f"n{position}" for position in range(count)]
    else:
        keys = []
        position = 0
        while f"n{position}" in row:
            keys.append(f"n{position}")
            position += 1
    values: list[str] = []
    for key in keys:
        raw = str(row.get(key, "") or "").strip()
        if raw:
            values.append(raw)
    return values


def _score_file_path(raw: Any) -> Path | None:
    if raw in (None, ""):
        return None
    path = Path(str(raw))
    if path.is_absolute():
        return path
    candidate = (_state.report_facade().PATH_BASE / path).resolve()
    if candidate.exists():
        return candidate
    return (Path.cwd() / path).resolve()


def _score_catalog_path(raw: Any) -> Path | None:
    return _score_file_path(raw)
