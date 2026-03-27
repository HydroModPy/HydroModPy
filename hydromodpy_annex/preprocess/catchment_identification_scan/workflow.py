"""Workflow implementation for catchment-identification annex case."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any, Callable

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import xy
from shapely.geometry import Point

from hydromodpy.core.backends import get_whitebox_backend
from hydromodpy.spatial.geographic.geographic_io import ensure_crs

from .config import CatchmentIdentificationConfig, DEFAULT_SECTION
from .diagnostic_plots import export_diagnostic_figures


@dataclass(slots=True)
class _ProgressTracker:
    """Emit coarse-grained progress messages with percentage."""

    total_steps: int
    printer: Callable[[str], None] = print
    current_step: int = 0

    def advance(self, label: str) -> None:
        self.current_step += 1
        ratio = (
            1.0
            if self.total_steps <= 0
            else min(1.0, float(self.current_step) / float(self.total_steps))
        )
        percent = int(round(100.0 * ratio))
        self.printer(f"[{percent:3d}%] {label}")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _remove_vector_dataset(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix == ".shp":
        for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix"):
            candidate = path.with_suffix(ext)
            if candidate.exists():
                candidate.unlink()
        return
    if path.exists():
        path.unlink()


def _compute_boundary_mask(valid_mask: np.ndarray) -> np.ndarray:
    """Return a mask of valid cells touching at least one invalid neighbor."""
    padded = np.pad(valid_mask, pad_width=1, mode="constant", constant_values=False)
    all_neighbors_valid = (
        padded[:-2, :-2]
        & padded[:-2, 1:-1]
        & padded[:-2, 2:]
        & padded[1:-1, :-2]
        & padded[1:-1, 2:]
        & padded[2:, :-2]
        & padded[2:, 1:-1]
        & padded[2:, 2:]
    )
    return valid_mask & (~all_neighbors_valid)


def _connected_components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    """Label 8-connected components on a binary mask using a simple DFS."""
    rows, cols = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components: list[list[tuple[int, int]]] = []

    starts = np.argwhere(mask)
    for row, col in starts:
        r0 = int(row)
        c0 = int(col)
        if visited[r0, c0]:
            continue

        stack = [(r0, c0)]
        visited[r0, c0] = True
        component: list[tuple[int, int]] = []

        while stack:
            r, c = stack.pop()
            component.append((r, c))
            rmin = max(0, r - 1)
            rmax = min(rows - 1, r + 1)
            cmin = max(0, c - 1)
            cmax = min(cols - 1, c + 1)
            for rn in range(rmin, rmax + 1):
                for cn in range(cmin, cmax + 1):
                    if rn == r and cn == c:
                        continue
                    if not mask[rn, cn] or visited[rn, cn]:
                        continue
                    visited[rn, cn] = True
                    stack.append((rn, cn))

        components.append(component)
    return components


def _write_vector_layer(
    gdf: gpd.GeoDataFrame,
    vector_path: Path,
    *,
    layer: str | None = None,
    mode: str = "w",
) -> None:
    vector_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = vector_path.suffix.lower()
    if suffix == ".gpkg":
        if layer is None:
            raise ValueError("layer is required when writing a GeoPackage.")
        gdf.to_file(vector_path, layer=layer, driver="GPKG", mode=mode)
        return
    gdf.to_file(vector_path, driver="ESRI Shapefile")


def _select_outlet_points(
    *,
    accumulation_cells: np.ndarray,
    candidate_mask: np.ndarray,
    transform,
    crs: Any,
    cell_area_m2: float,
) -> gpd.GeoDataFrame:
    components = _connected_components(candidate_mask)
    records: list[dict[str, Any]] = []
    for component in components:
        values = np.array([float(accumulation_cells[r, c]) for r, c in component], dtype=float)
        if values.size == 0:
            continue
        best_idx = int(np.nanargmax(values))
        row, col = component[best_idx]
        x_val, y_val = xy(transform, row, col, offset="center")
        acc_cells = float(values[best_idx])
        records.append(
            {
                "outlet_id": len(records) + 1,
                "row": int(row),
                "col": int(col),
                "x_outlet_m": float(x_val),
                "y_outlet_m": float(y_val),
                "accumulation_cells": acc_cells,
                "accumulation_area_km2": float(acc_cells * cell_area_m2 / 1_000_000.0),
                "geometry": Point(float(x_val), float(y_val)),
            }
        )

    return gpd.GeoDataFrame(records, geometry="geometry", crs=crs)


def _select_outlet_points_scan_global(
    *,
    accumulation_cells: np.ndarray,
    stream_mask: np.ndarray,
    transform,
    crs: Any,
    cell_area_m2: float,
    res_x_m: float,
    res_y_m: float,
    tile_size_km: float,
    max_outlets_per_tile: int,
    min_outlet_spacing_km: float,
    max_total_outlets: int,
    target_accumulation_cells: float | None = None,
    prioritize_target: bool = False,
) -> gpd.GeoDataFrame:
    """Select outlets across the whole DEM using tile-wise maxima and spacing."""
    rows, cols = stream_mask.shape
    tile_w = max(1, int(round(float(tile_size_km) * 1000.0 / float(res_x_m))))
    tile_h = max(1, int(round(float(tile_size_km) * 1000.0 / float(res_y_m))))
    min_spacing_m2 = float(min_outlet_spacing_km * 1000.0) ** 2

    selected: list[tuple[int, int, float]] = []
    stop = False
    for r0 in range(0, rows, tile_h):
        if stop:
            break
        r1 = min(rows, r0 + tile_h)
        for c0 in range(0, cols, tile_w):
            if len(selected) >= int(max_total_outlets):
                stop = True
                break
            c1 = min(cols, c0 + tile_w)

            tile_mask = stream_mask[r0:r1, c0:c1]
            if not bool(np.any(tile_mask)):
                continue
            tile_acc = accumulation_cells[r0:r1, c0:c1]
            rr, cc = np.nonzero(tile_mask)
            if rr.size == 0:
                continue
            vals = tile_acc[rr, cc].astype(float)
            finite = np.isfinite(vals)
            rr = rr[finite]
            cc = cc[finite]
            vals = vals[finite]
            if vals.size == 0:
                continue
            if prioritize_target and (target_accumulation_cells is not None):
                dist = np.abs(vals - float(target_accumulation_cells))
                order = np.lexsort((-vals, dist))
            else:
                order = np.argsort(vals)[::-1]

            picked_in_tile = 0
            for idx in order:
                row = int(r0 + rr[idx])
                col = int(c0 + cc[idx])
                acc_val = float(vals[idx])
                too_close = False
                if min_spacing_m2 > 0.0:
                    for row_s, col_s, _ in selected:
                        dx = (float(col) - float(col_s)) * float(res_x_m)
                        dy = (float(row) - float(row_s)) * float(res_y_m)
                        if (dx * dx + dy * dy) < min_spacing_m2:
                            too_close = True
                            break
                if too_close:
                    continue

                selected.append((row, col, acc_val))
                picked_in_tile += 1
                if picked_in_tile >= int(max_outlets_per_tile):
                    break
                if len(selected) >= int(max_total_outlets):
                    stop = True
                    break

    if not selected:
        return gpd.GeoDataFrame(columns=["outlet_id", "row", "col", "geometry"], geometry="geometry", crs=crs)

    selected = sorted(selected, key=lambda item: float(item[2]), reverse=True)
    records: list[dict[str, Any]] = []
    for row, col, acc_cells in selected:
        x_val, y_val = xy(transform, row, col, offset="center")
        records.append(
            {
                "outlet_id": len(records) + 1,
                "row": int(row),
                "col": int(col),
                "x_outlet_m": float(x_val),
                "y_outlet_m": float(y_val),
                "accumulation_cells": float(acc_cells),
                "accumulation_area_km2": float(float(acc_cells) * cell_area_m2 / 1_000_000.0),
                "geometry": Point(float(x_val), float(y_val)),
            }
        )
    return gpd.GeoDataFrame(records, geometry="geometry", crs=crs)


def _sample_accumulation_values(
    accumulation_raster_path: Path,
    outlets: gpd.GeoDataFrame,
) -> np.ndarray:
    return _sample_raster_values(accumulation_raster_path, outlets)


def _sample_raster_values(
    raster_path: Path,
    outlets: gpd.GeoDataFrame,
) -> np.ndarray:
    """Sample one raster at outlet point locations and return float values."""
    coords = [(float(geom.x), float(geom.y)) for geom in outlets.geometry]
    if not coords:
        return np.array([], dtype=float)

    with rasterio.open(raster_path) as src:
        sampled = np.array([float(val[0]) for val in src.sample(coords)], dtype=float)
        nodata = src.nodata
    if nodata is not None:
        sampled[np.isclose(sampled, float(nodata), equal_nan=False)] = np.nan
    sampled[~np.isfinite(sampled)] = np.nan
    return sampled


def _prepare_region_polygon(
    *,
    region_polygon_path: Path,
    dem_crs: Any,
    output_path: Path,
) -> Path:
    region = gpd.read_file(region_polygon_path)
    if region.empty:
        raise ValueError(f"Region polygon is empty: {region_polygon_path}")
    if region.crs is None:
        raise ValueError(f"Region polygon has no CRS: {region_polygon_path}")

    if region.crs != dem_crs:
        region = region.to_crs(dem_crs)

    _remove_vector_dataset(output_path)
    _write_vector_layer(region, output_path)
    return output_path


def _headwater_window_cells(
    *,
    target_accumulation_cells: float,
    min_target_ratio: float,
    tolerance_ratio: float,
) -> tuple[float, float, float]:
    """Return lower/upper bounds and effective lower ratio for headwater filtering."""
    lower_ratio_from_tolerance = max(0.0, 1.0 - float(tolerance_ratio))
    lower_ratio_from_floor = max(0.0, float(min_target_ratio))
    lower_ratio = max(lower_ratio_from_tolerance, lower_ratio_from_floor)
    lower_cells = float(target_accumulation_cells) * float(lower_ratio)
    upper_cells = float(target_accumulation_cells) * (1.0 + float(tolerance_ratio))
    return lower_cells, upper_cells, lower_ratio


def _build_headwater_candidate_stream_mask(
    *,
    stream_mask: np.ndarray,
    accumulation_cells: np.ndarray,
    target_basin_area_km2: float,
    target_accumulation_cells: float,
    min_target_ratio: float,
    tolerance_ratio: float,
    max_accumulation_area_km2: float,
) -> np.ndarray:
    """Restrict stream cells to the headwater target window."""
    lower_cells, upper_cells, lower_ratio = _headwater_window_cells(
        target_accumulation_cells=float(target_accumulation_cells),
        min_target_ratio=float(min_target_ratio),
        tolerance_ratio=float(tolerance_ratio),
    )
    narrow_mask = stream_mask & (accumulation_cells >= float(lower_cells))
    narrow_mask &= accumulation_cells <= float(upper_cells)
    if np.any(narrow_mask):
        return narrow_mask

    target_upper_bound = (
        float(max_accumulation_area_km2) / float(lower_ratio)
        if lower_ratio > 0.0
        else float("inf")
    )
    raise ValueError(
        "No stream cell found inside target window for headwater selection. "
        f"target_basin_area_km2={target_basin_area_km2:.3f}; "
        f"headwater_min_target_ratio={min_target_ratio:.3f}; "
        f"target_area_tolerance_ratio={tolerance_ratio:.3f}. "
        f"max_accumulation_area_km2={max_accumulation_area_km2:.3f}; "
        f"target_basin_area_upper_bound_for_current_ratios={target_upper_bound:.3f}. "
        "Increase target_area_tolerance_ratio, lower headwater_min_target_ratio, "
        "or lower target_basin_area_km2."
    )


def _compute_strahler_stream_order_raster(
    *,
    backend,
    d8_accumulation_path: Path,
    d8_pointer_path: Path,
    accumulation_threshold_cells: float,
    dem_crs,
    intermediate_dir: Path,
) -> Path:
    """Build and return Strahler stream-order raster for thresholded streams."""
    streams_raster_path = intermediate_dir / "streams_threshold.tif"
    stream_order_path = intermediate_dir / "streams_strahler_order.tif"
    backend.extract_streams(
        str(d8_accumulation_path),
        str(streams_raster_path),
        threshold=float(accumulation_threshold_cells),
        zero_background=True,
    )
    backend.strahler_stream_order(
        str(d8_pointer_path),
        str(streams_raster_path),
        str(stream_order_path),
        esri_pntr=False,
        zero_background=True,
    )
    ensure_crs(streams_raster_path, dem_crs.to_string())
    ensure_crs(stream_order_path, dem_crs.to_string())
    return stream_order_path


def _filter_outlets_by_strahler_order(
    *,
    outlets: gpd.GeoDataFrame,
    stream_order_path: Path,
    max_strahler_order: int,
    target_basin_area_km2: float,
    accumulation_area_km2: float,
) -> gpd.GeoDataFrame:
    """Keep outlets whose Strahler order is in [1, max_strahler_order]."""
    sampled_order = _sample_raster_values(stream_order_path, outlets)
    filtered = outlets.copy()
    filtered["strahler_order"] = sampled_order
    filtered = filtered[np.isfinite(filtered["strahler_order"])].copy()
    filtered["strahler_order"] = np.rint(filtered["strahler_order"]).astype(int)
    filtered = filtered[
        (filtered["strahler_order"] >= 1)
        & (filtered["strahler_order"] <= int(max_strahler_order))
    ].copy()
    if not filtered.empty:
        return filtered

    raise ValueError(
        "No outlet matches strict headwater condition (Strahler order <= max). "
        f"target_basin_area_km2={target_basin_area_km2:.3f}; "
        f"accumulation_area_km2={accumulation_area_km2:.3f}. "
        f"headwater_max_strahler_order={int(max_strahler_order):d}. "
        "Lower target_basin_area_km2 or reduce accumulation_area_km2."
    )


def _build_candidate_outlet_plot_mask(
    *,
    outlets_candidates: gpd.GeoDataFrame,
    fallback_mask: np.ndarray,
    shape: tuple[int, int],
) -> np.ndarray:
    """Create sparse point mask used in diagnostics overlays."""
    mask = np.zeros(shape, dtype=bool)
    if "row" not in outlets_candidates.columns or "col" not in outlets_candidates.columns:
        return fallback_mask.copy()
    for row_v, col_v in zip(
        np.asarray(outlets_candidates["row"], dtype=int),
        np.asarray(outlets_candidates["col"], dtype=int),
        strict=False,
    ):
        if 0 <= int(row_v) < shape[0] and 0 <= int(col_v) < shape[1]:
            mask[int(row_v), int(col_v)] = True
    return mask


def _select_headwater_non_overlapping_basins(
    basins: gpd.GeoDataFrame,
    outlets_selected: gpd.GeoDataFrame,
    *,
    target_area_km2: float,
    tolerance_ratio: float,
    min_target_ratio: float,
    max_overlap_ratio: float,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Keep headwater-like basins near target size and enforce near-disjoint polygons."""
    if basins.empty or outlets_selected.empty:
        return basins, outlets_selected

    work = basins.copy().reset_index(drop=True)
    lower_by_tolerance = float(target_area_km2) * max(0.0, 1.0 - float(tolerance_ratio))
    lower_by_min_ratio = float(target_area_km2) * max(0.0, float(min_target_ratio))
    lower = max(lower_by_tolerance, lower_by_min_ratio)
    upper = float(target_area_km2) * (1.0 + float(tolerance_ratio))
    in_window = work["area_km2"].between(lower, upper, inclusive="both")
    candidates = work[in_window].copy()
    if candidates.empty:
        return work.iloc[0:0].copy(), outlets_selected.iloc[0:0].copy()

    # Headwater proxy: basin does not contain any other selected outlet point.
    outlet_points: dict[int, Point] = {}
    for _, outlet in outlets_selected.iterrows():
        outlet_points[int(outlet["outlet_id"])] = Point(
            float(outlet["x_outlet_m"]), float(outlet["y_outlet_m"])
        )

    keep_rows: list[int] = []
    for idx, basin in candidates.iterrows():
        geom = basin.geometry
        if geom is None or geom.is_empty:
            continue
        if not geom.is_valid:
            geom = geom.buffer(0)
        if geom is None or geom.is_empty:
            continue
        outlet_id = int(basin["outlet_id"])
        has_upstream_inside = False
        for other_outlet_id, point in outlet_points.items():
            if other_outlet_id == outlet_id:
                continue
            if geom.covers(point):
                has_upstream_inside = True
                break
        if not has_upstream_inside:
            keep_rows.append(int(idx))

    headwater_candidates = candidates.loc[keep_rows].copy() if keep_rows else candidates.copy()
    headwater_candidates["_score"] = np.abs(
        np.asarray(headwater_candidates["area_km2"], dtype=float) - float(target_area_km2)
    )
    headwater_candidates = headwater_candidates.sort_values(
        by=["_score", "area_km2"], ascending=[True, False]
    )

    selected_indices: list[int] = []
    selected_geoms: list[Any] = []
    for idx, basin in headwater_candidates.iterrows():
        geom = basin.geometry
        if geom is None or geom.is_empty:
            continue
        if not geom.is_valid:
            geom = geom.buffer(0)
        if geom is None or geom.is_empty:
            continue

        overlaps = False
        for kept in selected_geoms:
            if not geom.intersects(kept):
                continue
            intersection = geom.intersection(kept)
            if intersection.is_empty:
                continue
            min_area = min(float(geom.area), float(kept.area))
            if min_area <= 0.0:
                continue
            overlap_ratio = float(intersection.area) / min_area
            if overlap_ratio > float(max_overlap_ratio):
                overlaps = True
                break
        if overlaps:
            continue

        selected_indices.append(int(idx))
        selected_geoms.append(geom)

    selected = headwater_candidates.loc[selected_indices].copy()
    if selected.empty:
        return work.iloc[0:0].copy(), outlets_selected.iloc[0:0].copy()

    selected = selected.drop(columns=["_score"], errors="ignore")
    selected = selected.sort_values("area_km2", ascending=False).reset_index(drop=True)

    selected_outlet_ids = set(int(v) for v in selected["outlet_id"].to_list())
    outlets_final = outlets_selected[outlets_selected["outlet_id"].isin(selected_outlet_ids)].copy()
    area_map = dict(zip(selected["outlet_id"], selected["area_km2"], strict=False))
    outlets_final["basin_area_km2"] = (
        outlets_final["outlet_id"].map(area_map).astype(float)
    )
    outlets_final = outlets_final.sort_values("basin_area_km2", ascending=False).reset_index(drop=True)
    return selected, outlets_final


def run_catchment_identification_from_toml(
    config_toml: str | Path,
    *,
    section: str = DEFAULT_SECTION,
    output_json: str | Path | None = None,
    printer: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run the catchment-identification workflow and return a summary."""
    cfg = CatchmentIdentificationConfig.from_toml(config_toml, section=section)
    basin_selection_mode = str(cfg.basin_selection_mode).strip().lower()
    require_strict_headwater = basin_selection_mode == "headwater_target"
    max_strahler_order = int(cfg.headwater_max_strahler_order)

    total_steps = 9
    if require_strict_headwater:
        total_steps += 1
    if cfg.region_polygon_path is not None:
        total_steps += 1
    if bool(cfg.save_diagnostic_figures):
        total_steps += 1
    if output_json is not None:
        total_steps += 1
    if not bool(cfg.keep_intermediate):
        total_steps += 1
    progress = _ProgressTracker(total_steps=total_steps, printer=printer)

    progress.advance("Preparing output folders")
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    intermediate_dir = cfg.output_dir / "intermediate"
    intermediate_dir.mkdir(parents=True, exist_ok=True)

    backend = get_whitebox_backend()

    progress.advance("Validating DEM CRS")
    with rasterio.open(cfg.dem_path) as dem_src:
        dem_crs = dem_src.crs
    if dem_crs is None:
        raise ValueError(f"DEM has no CRS: {cfg.dem_path}")
    if dem_crs.is_geographic:
        raise ValueError(
            "DEM CRS is geographic (degrees). Use a projected metric CRS before running."
        )

    dem_for_flow = cfg.dem_path
    if cfg.region_polygon_path is not None:
        progress.advance("Clipping DEM to region polygon")
        region_projected_path = intermediate_dir / "region_projected.shp"
        _prepare_region_polygon(
            region_polygon_path=cfg.region_polygon_path,
            dem_crs=dem_crs,
            output_path=region_projected_path,
        )
        dem_clipped_path = intermediate_dir / "dem_clipped.tif"
        backend.clip_raster_to_polygon(
            str(cfg.dem_path),
            str(region_projected_path),
            str(dem_clipped_path),
            maintain_dimensions=False,
        )
        ensure_crs(dem_clipped_path, dem_crs.to_string())
        dem_for_flow = dem_clipped_path

    progress.advance(f"Applying DEM correction ({cfg.dem_correction})")
    dem_corrected_path = intermediate_dir / (
        "dem_fill.tif" if cfg.dem_correction == "fill" else "dem_breach.tif"
    )
    if cfg.dem_correction == "fill":
        backend.fill_depressions(str(dem_for_flow), str(dem_corrected_path))
    else:
        backend.breach_depressions(str(dem_for_flow), str(dem_corrected_path))

    progress.advance("Computing D8 pointer and accumulation")
    d8_pointer_path = intermediate_dir / "dem_d8_pointer.tif"
    d8_accumulation_path = intermediate_dir / "dem_d8_accumulation_cells.tif"
    backend.d8_pointer(str(dem_corrected_path), str(d8_pointer_path), esri_pntr=False)
    backend.d8_flow_accumulation(str(dem_corrected_path), str(d8_accumulation_path), log=False)

    ensure_crs(dem_corrected_path, dem_crs.to_string())
    ensure_crs(d8_pointer_path, dem_crs.to_string())
    ensure_crs(d8_accumulation_path, dem_crs.to_string())

    with rasterio.open(dem_corrected_path) as dem_src:
        dem_values = dem_src.read(1)
        dem_nodata = dem_src.nodata
        dem_transform = dem_src.transform
        cell_area_m2 = float(abs(dem_transform.a * dem_transform.e))
        res_x_m = float(abs(dem_transform.a))
        res_y_m = float(abs(dem_transform.e))

        valid_mask = np.isfinite(dem_values)
        if dem_nodata is not None:
            valid_mask &= dem_values != dem_nodata

    if cell_area_m2 <= 0.0:
        raise ValueError(f"Invalid DEM cell area: {cell_area_m2}")
    domain_valid_cell_count = int(np.count_nonzero(valid_mask))
    domain_area_km2 = float(domain_valid_cell_count * cell_area_m2 / 1_000_000.0)

    accumulation_threshold_cells = cfg.accumulation_area_km2 * 1_000_000.0 / cell_area_m2
    target_basin_area_km2 = (
        float(cfg.target_basin_area_km2)
        if cfg.target_basin_area_km2 is not None
        else float(cfg.accumulation_area_km2)
    )
    min_target_ratio = float(cfg.headwater_min_target_ratio)
    target_accumulation_cells = target_basin_area_km2 * 1_000_000.0 / cell_area_m2

    with rasterio.open(d8_accumulation_path) as acc_src:
        accumulation_cells = acc_src.read(1).astype(float)
        acc_transform = acc_src.transform
        acc_nodata = acc_src.nodata
        acc_crs = acc_src.crs

    if acc_nodata is not None:
        accumulation_cells[np.isclose(accumulation_cells, float(acc_nodata), equal_nan=False)] = np.nan
    accumulation_cells[~np.isfinite(accumulation_cells)] = np.nan

    valid_accum = accumulation_cells[valid_mask & np.isfinite(accumulation_cells)]
    if valid_accum.size == 0:
        raise ValueError("Accumulation raster has no finite value on valid DEM cells.")
    max_accumulation_cells = float(np.nanmax(valid_accum))
    max_accumulation_area_km2 = float(max_accumulation_cells * cell_area_m2 / 1_000_000.0)
    if accumulation_threshold_cells > max_accumulation_cells:
        raise ValueError(
            "No stream cell reaches the requested threshold. "
            f"requested_accumulation_area_km2={cfg.accumulation_area_km2:.3f}; "
            f"max_accumulation_area_km2={max_accumulation_area_km2:.3f}; "
            f"domain_area_km2={domain_area_km2:.3f}. "
            "Lower accumulation_area_km2 in the TOML config."
        )

    stream_mask = valid_mask & np.isfinite(accumulation_cells)
    stream_mask &= accumulation_cells >= accumulation_threshold_cells
    candidate_stream_mask = stream_mask.copy()
    if basin_selection_mode == "headwater_target":
        candidate_stream_mask = _build_headwater_candidate_stream_mask(
            stream_mask=stream_mask,
            accumulation_cells=accumulation_cells,
            target_basin_area_km2=float(target_basin_area_km2),
            target_accumulation_cells=float(target_accumulation_cells),
            min_target_ratio=float(min_target_ratio),
            tolerance_ratio=float(cfg.target_area_tolerance_ratio),
            max_accumulation_area_km2=float(max_accumulation_area_km2),
        )

    stream_order_path: Path | None = None
    if require_strict_headwater:
        progress.advance("Computing stream order (headwater filtering)")
        stream_order_path = _compute_strahler_stream_order_raster(
            backend=backend,
            d8_accumulation_path=d8_accumulation_path,
            d8_pointer_path=d8_pointer_path,
            accumulation_threshold_cells=float(accumulation_threshold_cells),
            dem_crs=dem_crs,
            intermediate_dir=intermediate_dir,
        )

    boundary_mask = _compute_boundary_mask(valid_mask)
    outlet_selection_mode = str(cfg.outlet_selection_mode).strip().lower()

    progress.advance(f"Detecting outlet candidates (mode={outlet_selection_mode})")
    if outlet_selection_mode == "border":
        candidate_outlet_mask = candidate_stream_mask & boundary_mask
        if not np.any(candidate_outlet_mask):
            boundary_accum = accumulation_cells[boundary_mask & np.isfinite(accumulation_cells)]
            max_boundary_accumulation_area_km2 = (
                float(np.nanmax(boundary_accum) * cell_area_m2 / 1_000_000.0)
                if boundary_accum.size > 0
                else float("nan")
            )
            raise ValueError(
                "No outlet candidate found on domain border for this threshold. "
                f"accumulation_area_km2={cfg.accumulation_area_km2:.3f}; "
                f"max_boundary_accumulation_area_km2={max_boundary_accumulation_area_km2:.3f}. "
                "Lower accumulation_area_km2, increase target_area_tolerance_ratio, "
                "switch outlet_selection_mode to 'scan_global', or clip the DEM to your study "
                "region so expected outlets intersect the boundary."
            )
        outlets_candidates = _select_outlet_points(
            accumulation_cells=accumulation_cells,
            candidate_mask=candidate_outlet_mask,
            transform=acc_transform,
            crs=acc_crs,
            cell_area_m2=cell_area_m2,
        )
    else:
        candidate_outlet_mask = candidate_stream_mask.copy()
        outlets_candidates = _select_outlet_points_scan_global(
            accumulation_cells=accumulation_cells,
            stream_mask=candidate_stream_mask,
            transform=acc_transform,
            crs=acc_crs,
            cell_area_m2=cell_area_m2,
            res_x_m=res_x_m,
            res_y_m=res_y_m,
            tile_size_km=float(cfg.scan_tile_size_km),
            max_outlets_per_tile=int(cfg.scan_max_outlets_per_tile),
            min_outlet_spacing_km=float(cfg.scan_min_outlet_spacing_km),
            max_total_outlets=int(cfg.scan_max_total_outlets),
            target_accumulation_cells=float(target_accumulation_cells),
            prioritize_target=(basin_selection_mode == "headwater_target"),
        )

    if outlets_candidates.empty:
        raise ValueError(
            "No outlet candidate could be extracted from the accumulation raster. "
            f"mode={outlet_selection_mode}; accumulation_area_km2={cfg.accumulation_area_km2:.3f}"
        )

    # Keep one sparse mask for diagnostics so overlays stay readable in scan mode.
    candidate_outlet_mask_plot = _build_candidate_outlet_plot_mask(
        outlets_candidates=outlets_candidates,
        fallback_mask=candidate_outlet_mask,
        shape=stream_mask.shape,
    )

    outlets_candidates_path = intermediate_dir / "outlets_candidates.shp"
    _remove_vector_dataset(outlets_candidates_path)
    _write_vector_layer(outlets_candidates[["outlet_id", "geometry"]], outlets_candidates_path)

    progress.advance("Preparing outlets for watershed delineation")
    outlets_for_watershed_path = intermediate_dir / "outlets_for_watershed.shp"
    if cfg.snap_dist > 0:
        backend.snap_pour_points(
            str(outlets_candidates_path),
            str(d8_accumulation_path),
            str(outlets_for_watershed_path),
            snap_dist=int(cfg.snap_dist),
        )
        outlets = gpd.read_file(outlets_for_watershed_path)
    else:
        _remove_vector_dataset(outlets_for_watershed_path)
        _write_vector_layer(outlets_candidates[["outlet_id", "geometry"]], outlets_for_watershed_path)
        outlets = outlets_candidates.copy()

    outlets = outlets.reset_index(drop=True)
    if outlets.empty:
        raise ValueError("No outlet retained after optional snapping.")
    if "outlet_id" not in outlets.columns:
        outlets["outlet_id"] = np.arange(1, len(outlets) + 1, dtype=int)
    else:
        outlets["outlet_id"] = outlets["outlet_id"].astype(int)

    sampled_acc = _sample_accumulation_values(d8_accumulation_path, outlets)
    outlets["accumulation_cells"] = sampled_acc
    outlets = outlets[np.isfinite(outlets["accumulation_cells"])].copy()
    outlets["accumulation_area_km2"] = outlets["accumulation_cells"] * cell_area_m2 / 1_000_000.0
    outlets = outlets[outlets["accumulation_area_km2"] >= cfg.accumulation_area_km2].copy()
    if outlets.empty:
        raise ValueError(
            "No outlet satisfies accumulation threshold after snapping. "
            "Try reducing snap_dist or lowering accumulation_area_km2."
        )

    if require_strict_headwater:
        if stream_order_path is None:
            raise RuntimeError("Missing stream-order raster for strict headwater selection.")
        outlets = _filter_outlets_by_strahler_order(
            outlets=outlets,
            stream_order_path=stream_order_path,
            max_strahler_order=int(max_strahler_order),
            target_basin_area_km2=float(target_basin_area_km2),
            accumulation_area_km2=float(cfg.accumulation_area_km2),
        )

    outlets["x_outlet_m"] = outlets.geometry.x.astype(float)
    outlets["y_outlet_m"] = outlets.geometry.y.astype(float)

    _remove_vector_dataset(outlets_for_watershed_path)
    _write_vector_layer(outlets[["outlet_id", "geometry"]], outlets_for_watershed_path)

    progress.advance("Delineating watersheds from selected outlets")
    watershed_raster_path = intermediate_dir / "watersheds_from_outlets.tif"
    watersheds_vector_raw_path = intermediate_dir / "watersheds_from_outlets_raw.shp"
    backend.watershed(
        str(d8_pointer_path),
        str(outlets_for_watershed_path),
        str(watershed_raster_path),
        esri_pntr=False,
    )
    backend.raster_to_vector_polygons(
        str(watershed_raster_path),
        str(watersheds_vector_raw_path),
    )

    progress.advance("Building final basin/outlet tables")
    basins_raw = gpd.read_file(watersheds_vector_raw_path)
    if basins_raw.empty:
        raise ValueError("Watershed delineation produced no polygon.")
    basins_raw = basins_raw[basins_raw.geometry.notnull() & (~basins_raw.geometry.is_empty)].copy()

    basin_rows: list[dict[str, Any]] = []
    for _, basin in basins_raw.iterrows():
        geom = basin.geometry
        if geom is None or geom.is_empty:
            continue
        if not geom.is_valid:
            geom = geom.buffer(0)
        if geom is None or geom.is_empty or (not geom.is_valid):
            continue
        mask = outlets.geometry.apply(geom.covers)
        if not bool(mask.any()):
            continue
        candidates = outlets.loc[mask].copy()
        candidates = candidates.sort_values("accumulation_cells", ascending=False)
        outlet = candidates.iloc[0]
        area_m2 = float(geom.area)
        basin_rows.append(
            {
                "basin_id": int(len(basin_rows) + 1),
                "outlet_id": int(outlet["outlet_id"]),
                "x_outlet_m": float(outlet["x_outlet_m"]),
                "y_outlet_m": float(outlet["y_outlet_m"]),
                "accumulation_cells": float(outlet["accumulation_cells"]),
                "accumulation_area_km2": float(outlet["accumulation_area_km2"]),
                "area_m2": area_m2,
                "area_km2": area_m2 / 1_000_000.0,
                "geometry": geom,
            }
        )

    basins = gpd.GeoDataFrame(basin_rows, geometry="geometry", crs=basins_raw.crs)
    if basins.empty:
        raise ValueError("Could not map delineated basin polygons to outlet points.")

    basins = basins[basins["area_km2"] >= cfg.accumulation_area_km2].copy()
    basins = basins.sort_values("area_km2", ascending=False)
    basins = basins.drop_duplicates(subset=["outlet_id"], keep="first").reset_index(drop=True)
    if basins.empty:
        raise ValueError(
            "No delineated basin reaches the requested minimum area. "
            f"accumulation_area_km2={cfg.accumulation_area_km2:.3f}"
        )

    selected_outlet_ids = set(int(v) for v in basins["outlet_id"].to_list())
    outlets_selected = outlets[outlets["outlet_id"].isin(selected_outlet_ids)].copy()
    outlet_area_map = dict(zip(basins["outlet_id"], basins["area_km2"], strict=False))
    outlets_selected["basin_area_km2"] = outlets_selected["outlet_id"].map(outlet_area_map).astype(float)
    outlets_selected = outlets_selected.sort_values("basin_area_km2", ascending=False).reset_index(drop=True)
    basins_count_before_selection = int(len(basins))
    outlets_count_before_selection = int(len(outlets_selected))

    if basin_selection_mode == "headwater_target":
        basins, outlets_selected = _select_headwater_non_overlapping_basins(
            basins,
            outlets_selected,
            target_area_km2=float(target_basin_area_km2),
            tolerance_ratio=float(cfg.target_area_tolerance_ratio),
            min_target_ratio=float(cfg.headwater_min_target_ratio),
            max_overlap_ratio=float(cfg.max_basin_overlap_ratio),
        )
        if basins.empty or outlets_selected.empty:
            raise ValueError(
                "No headwater basin satisfies the strict target window and overlap constraints. "
                f"target_basin_area_km2={target_basin_area_km2:.3f}; "
                f"headwater_min_target_ratio={cfg.headwater_min_target_ratio:.3f}; "
                f"target_area_tolerance_ratio={cfg.target_area_tolerance_ratio:.3f}; "
                f"max_basin_overlap_ratio={cfg.max_basin_overlap_ratio:.3f}. "
                "Increase target_area_tolerance_ratio, lower headwater_min_target_ratio, "
                "lower target_basin_area_km2, "
                "or relax max_basin_overlap_ratio."
            )

    progress.advance("Writing GeoPackage and CSV outputs")
    gpkg_path = cfg.output_dir / cfg.gpkg_name
    _remove_vector_dataset(gpkg_path)
    _write_vector_layer(basins, gpkg_path, layer=cfg.basins_layer, mode="w")
    _write_vector_layer(outlets_selected, gpkg_path, layer=cfg.outlets_layer, mode="a")

    outlets_csv_path = cfg.output_dir / cfg.outlets_csv_name
    outlets_csv_df = outlets_selected.drop(columns="geometry").copy()
    outlets_csv_df.to_csv(outlets_csv_path, index=False)

    diagnostic_figures: dict[str, str] = {}
    figures_dir: Path | None = None
    if bool(cfg.save_diagnostic_figures):
        progress.advance("Saving diagnostic figures")
        figures_dir = cfg.output_dir / cfg.figures_dir_name
        diagnostic_figures = export_diagnostic_figures(
            figures_dir=figures_dir,
            dem_corrected_path=dem_corrected_path,
            d8_accumulation_path=d8_accumulation_path,
            basins=basins,
            outlets_selected=outlets_selected,
            outlets_candidates=outlets_candidates,
            stream_mask=stream_mask,
            candidate_outlet_mask=candidate_outlet_mask_plot,
            threshold_area_km2=float(cfg.accumulation_area_km2),
        )

    summary: dict[str, Any] = {
        "config_path": str(cfg.config_path),
        "launcher_script": (str(cfg.launcher_script) if cfg.launcher_script is not None else None),
        "dem_path": str(cfg.dem_path),
        "region_polygon_path": (
            str(cfg.region_polygon_path) if cfg.region_polygon_path is not None else None
        ),
        "output_dir": str(cfg.output_dir),
        "gpkg_path": str(gpkg_path),
        "outlets_csv_path": str(outlets_csv_path),
        "basins_layer": cfg.basins_layer,
        "outlets_layer": cfg.outlets_layer,
        "basins_count": int(len(basins)),
        "outlets_count": int(len(outlets_selected)),
        "outlet_candidates_count": int(len(outlets_candidates)),
        "accumulation_area_km2": float(cfg.accumulation_area_km2),
        "accumulation_threshold_cells": float(accumulation_threshold_cells),
        "target_basin_area_km2": float(target_basin_area_km2),
        "target_accumulation_cells": float(target_accumulation_cells),
        "domain_area_km2": float(domain_area_km2),
        "max_accumulation_area_km2": float(max_accumulation_area_km2),
        "outlet_selection_mode": str(cfg.outlet_selection_mode),
        "scan_tile_size_km": float(cfg.scan_tile_size_km),
        "scan_max_outlets_per_tile": int(cfg.scan_max_outlets_per_tile),
        "scan_min_outlet_spacing_km": float(cfg.scan_min_outlet_spacing_km),
        "scan_max_total_outlets": int(cfg.scan_max_total_outlets),
        "basin_selection_mode": str(cfg.basin_selection_mode),
        "headwater_max_strahler_order": int(cfg.headwater_max_strahler_order),
        "headwater_min_target_ratio": float(cfg.headwater_min_target_ratio),
        "target_area_tolerance_ratio": float(cfg.target_area_tolerance_ratio),
        "max_basin_overlap_ratio": float(cfg.max_basin_overlap_ratio),
        "strict_headwater_order1": bool(require_strict_headwater and (max_strahler_order == 1)),
        "strict_headwater_order_max": int(max_strahler_order) if require_strict_headwater else None,
        "basins_count_before_selection": basins_count_before_selection,
        "outlets_count_before_selection": outlets_count_before_selection,
        "cell_area_m2": float(cell_area_m2),
        "dem_resolution_x_m": float(res_x_m),
        "dem_resolution_y_m": float(res_y_m),
        "dem_correction": cfg.dem_correction,
        "snap_dist": int(cfg.snap_dist),
        "save_diagnostic_figures": bool(cfg.save_diagnostic_figures),
        "figures_dir": (str(figures_dir) if figures_dir is not None else None),
        "diagnostic_figures": diagnostic_figures,
    }

    if output_json is not None:
        progress.advance("Writing summary JSON")
        _write_json(Path(output_json).expanduser().resolve(), summary)

    if not cfg.keep_intermediate:
        progress.advance("Removing intermediate folder")
        shutil.rmtree(intermediate_dir, ignore_errors=True)

    return summary
