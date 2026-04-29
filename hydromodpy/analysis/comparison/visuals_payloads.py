"""Payload dataclasses and builders for comparison visuals."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.analysis.comparison.config import (
    MethodComparisonConfig,
    MethodComparisonFineRaster,
    MethodComparisonObservable,
    MethodComparisonVariant,
)
from hydromodpy.analysis.comparison.runtime import (
    VariableSeries,
    load_variable_series,
    mask_depth_series_from_head_nodata,
    resolve_bundle_cells,
    resolve_structured_shape_from_config,
    resolve_structured_shape_from_run_folder,
    select_time_slices,
)
from hydromodpy.analysis.comparison.visuals_style import _mask_nodata

try:
    from scipy.interpolate import griddata
except Exception:  # pragma: no cover - optional at runtime
    griddata = None


@dataclass(frozen=True, slots=True)
class MapPayload:
    """One rendered map payload for one observable and one variant."""

    variant_id: str
    variant_label: str
    solver: str
    mesh_mode: str
    observable_name: str
    resolved_variable: str
    unit: str
    time_label: str
    values: np.ndarray
    geometry_kind: str
    structured_shape: tuple[int, int] | None = None
    cell_ids: np.ndarray | None = None
    x: np.ndarray | None = None
    y: np.ndarray | None = None
    extent: tuple[float, float, float, float] | None = None


@dataclass(frozen=True, slots=True)
class DifferencePayload:
    """One difference map aligned on a reference geometry."""

    reference_variant: str
    candidate_variant: str
    observable_name: str
    unit: str
    values: np.ndarray
    geometry_kind: str
    structured_shape: tuple[int, int] | None = None
    cell_ids: np.ndarray | None = None
    x: np.ndarray | None = None
    y: np.ndarray | None = None
    extent: tuple[float, float, float, float] | None = None


def _estimate_extent_from_centroids(
    *,
    x_values: np.ndarray | None,
    y_values: np.ndarray | None,
) -> tuple[float, float, float, float] | None:
    if x_values is None or y_values is None:
        return None
    x = np.asarray(x_values, dtype=float).ravel()
    y = np.asarray(y_values, dtype=float).ravel()
    finite = np.isfinite(x) & np.isfinite(y)
    if not np.any(finite):
        return None
    x = x[finite]
    y = y[finite]

    def _spacing(values: np.ndarray) -> float:
        unique = np.unique(np.round(values, decimals=9))
        if unique.size < 2:
            return 1.0
        diffs = np.diff(np.sort(unique))
        finite_diffs = diffs[np.isfinite(diffs) & (diffs > 0.0)]
        if finite_diffs.size == 0:
            return 1.0
        return float(np.median(finite_diffs))

    dx = _spacing(x)
    dy = _spacing(y)
    return (
        float(np.min(x) - dx / 2.0),
        float(np.max(x) + dx / 2.0),
        float(np.min(y) - dy / 2.0),
        float(np.max(y) + dy / 2.0),
    )


def _payload_extent(payload: MapPayload) -> tuple[float, float, float, float] | None:
    if payload.extent is not None:
        return payload.extent
    return _estimate_extent_from_centroids(x_values=payload.x, y_values=payload.y)


def _payload_samples(payload: MapPayload) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    if payload.x is None or payload.y is None:
        return None
    x = np.asarray(payload.x, dtype=float).ravel()
    y = np.asarray(payload.y, dtype=float).ravel()
    values = _mask_nodata(np.asarray(payload.values, dtype=float).ravel())
    if not (x.size == y.size == values.size):
        return None
    finite = np.isfinite(x) & np.isfinite(y) & np.isfinite(values)
    if not np.any(finite):
        return None
    return x[finite], y[finite], values[finite]


def _choose_map_slice(
    *,
    series: VariableSeries,
    observable: MethodComparisonObservable,
) -> tuple[np.ndarray, str] | None:
    slices = select_time_slices(series, observable)
    if not slices:
        return None
    if len(slices) == 1:
        chosen = slices[0]
    elif observable.time_reducer is not None:
        reducer_key = str(observable.time_reducer).strip().lower()
        if reducer_key == "first":
            chosen = slices[0]
        elif reducer_key == "last":
            chosen = slices[-1]
        else:
            return None
    else:
        return None
    return np.asarray(chosen.values, dtype=float).ravel(), str(chosen.time_key)


def _build_map_payload(
    *,
    cfg: MethodComparisonConfig,
    variant: MethodComparisonVariant,
    summary: dict[str, Any],
    observable: MethodComparisonObservable,
    rows: list[dict[str, Any]],
) -> MapPayload | None:
    reducer_key = str(observable.reducer or "identity").strip().lower()
    if reducer_key not in {"", "identity"}:
        return None
    run_folder = summary.get("run_folder")
    if not run_folder:
        return None
    run_folder_path = Path(str(run_folder))
    series = load_variable_series(run_folder=run_folder_path, variable=observable.variable)
    series = mask_depth_series_from_head_nodata(run_folder=run_folder_path, series=series)
    selected = _choose_map_slice(series=series, observable=observable)
    if selected is None:
        return None
    values, time_label = selected
    if values.size == 0:
        return None

    unit = next(
        (
            str(row.get("unit", ""))
            for row in rows
            if str(row.get("variant_id", "")) == variant.id
            and str(row.get("observable", "")) == observable.name
            and str(row.get("unit", "")) != ""
        ),
        observable.unit or "",
    )

    config_path_raw = summary.get("config_path")
    config_path = None if config_path_raw in ("", None) else Path(str(config_path_raw))
    if config_path is None:
        config_path = cfg.resolve_variant_config_path(variant)
    cells = resolve_bundle_cells(
        run_folder_path,
        config_path=config_path,
        expected_size=values.size,
        solver_name=variant.solver,
    )
    structured_shape = (
        None
        if config_path is None or not config_path.exists()
        else resolve_structured_shape_from_config(
            config_path,
            solver_name=variant.solver,
        )
    )
    if structured_shape is None:
        structured_shape = resolve_structured_shape_from_run_folder(run_folder_path)
    if structured_shape is None:
        if cells is None or cells.cell_ids.size != values.size:
            return None
        return MapPayload(
            variant_id=variant.id,
            variant_label=variant.label or variant.id,
            solver=variant.solver or "",
            mesh_mode=variant.mesh_mode,
            observable_name=observable.name,
            resolved_variable=series.variable_name,
            unit=unit,
            time_label=time_label,
            values=values,
            geometry_kind="scatter",
            cell_ids=np.asarray(cells.cell_ids, dtype=int),
            x=np.asarray(cells.x, dtype=float),
            y=np.asarray(cells.y, dtype=float),
            extent=_estimate_extent_from_centroids(x_values=cells.x, y_values=cells.y),
        )
    if values.size != structured_shape[0] * structured_shape[1]:
        return None
    structured_extent = _estimate_extent_from_centroids(
        x_values=None if cells is None else cells.x,
        y_values=None if cells is None else cells.y,
    )
    return MapPayload(
        variant_id=variant.id,
        variant_label=variant.label or variant.id,
        solver=variant.solver or "",
        mesh_mode=variant.mesh_mode,
        observable_name=observable.name,
        resolved_variable=series.variable_name,
        unit=unit,
        time_label=time_label,
        values=values,
        geometry_kind="structured",
        structured_shape=structured_shape,
        x=None if cells is None else np.asarray(cells.x, dtype=float),
        y=None if cells is None else np.asarray(cells.y, dtype=float),
        extent=structured_extent,
    )


def _build_difference_payload(
    *,
    reference: MapPayload,
    candidate: MapPayload,
) -> DifferencePayload | None:
    if reference.unit != candidate.unit:
        return None

    if (
        reference.geometry_kind == "scatter"
        and candidate.geometry_kind == "scatter"
        and reference.cell_ids is not None
        and candidate.cell_ids is not None
    ):
        if reference.cell_ids.size != candidate.cell_ids.size:
            return None
        candidate_positions = {
            int(cell_id): index for index, cell_id in enumerate(candidate.cell_ids.tolist())
        }
        if any(int(cell_id) not in candidate_positions for cell_id in reference.cell_ids.tolist()):
            return None
        ordered = np.asarray(
            [candidate.values[candidate_positions[int(cell_id)]] for cell_id in reference.cell_ids],
            dtype=float,
        )
        reference_values = _mask_nodata(reference.values)
        candidate_values = _mask_nodata(ordered)
        return DifferencePayload(
            reference_variant=reference.variant_id,
            candidate_variant=candidate.variant_id,
            observable_name=reference.observable_name,
            unit=reference.unit,
            values=candidate_values - reference_values,
            geometry_kind="scatter",
            cell_ids=np.asarray(reference.cell_ids, dtype=int),
            x=np.asarray(reference.x, dtype=float),
            y=np.asarray(reference.y, dtype=float),
            extent=reference.extent,
        )

    if (
        reference.geometry_kind == "structured"
        and candidate.geometry_kind == "structured"
        and reference.structured_shape == candidate.structured_shape
    ):
        reference_values = _mask_nodata(reference.values)
        candidate_values = _mask_nodata(candidate.values)
        return DifferencePayload(
            reference_variant=reference.variant_id,
            candidate_variant=candidate.variant_id,
            observable_name=reference.observable_name,
            unit=reference.unit,
            values=np.asarray(candidate_values - reference_values, dtype=float),
            geometry_kind="structured",
            structured_shape=reference.structured_shape,
            extent=reference.extent,
        )
    return None


def _resolve_fine_grid_bounds(
    *,
    payloads: list[MapPayload],
    fine_raster: MethodComparisonFineRaster,
    reference_variant: str | None,
) -> tuple[float, float, float, float] | None:
    extents = [
        extent
        for payload in payloads
        for extent in [_payload_extent(payload)]
        if extent is not None
    ]
    if len(extents) < 2:
        return None
    if fine_raster.extent_mode == "reference" and reference_variant is not None:
        reference_payload = next(
            (payload for payload in payloads if payload.variant_id == reference_variant),
            None,
        )
        if reference_payload is not None:
            return _payload_extent(reference_payload)
    if fine_raster.extent_mode == "union":
        xmin = min(item[0] for item in extents)
        xmax = max(item[1] for item in extents)
        ymin = min(item[2] for item in extents)
        ymax = max(item[3] for item in extents)
        return (xmin, xmax, ymin, ymax)
    xmin = max(item[0] for item in extents)
    xmax = min(item[1] for item in extents)
    ymin = max(item[2] for item in extents)
    ymax = min(item[3] for item in extents)
    if xmin >= xmax or ymin >= ymax:
        return None
    return (xmin, xmax, ymin, ymax)


def _build_fine_grid(
    *,
    bounds: tuple[float, float, float, float],
    resolution: float,
) -> tuple[np.ndarray, np.ndarray, tuple[float, float, float, float]] | None:
    xmin, xmax, ymin, ymax = bounds
    x_values = np.arange(xmin + resolution / 2.0, xmax, resolution, dtype=float)
    y_values = np.arange(ymin + resolution / 2.0, ymax, resolution, dtype=float)
    if x_values.size < 2 or y_values.size < 2:
        return None
    grid_x, grid_y = np.meshgrid(x_values, y_values)
    return grid_x, grid_y, (xmin, xmax, ymin, ymax)


def _regrid_payload(
    *,
    payload: MapPayload,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    interpolation: str,
) -> np.ndarray | None:
    if griddata is None:
        return None
    samples = _payload_samples(payload)
    if samples is None:
        return None
    sample_x, sample_y, sample_values = samples
    try:
        array = griddata(
            np.column_stack((sample_x, sample_y)),
            sample_values,
            (grid_x, grid_y),
            method=interpolation,
        )
    except Exception:
        return None
    if array is None:
        return None
    result = np.asarray(array, dtype=float)
    if interpolation == "linear" and not np.any(np.isfinite(result)):
        try:
            result = np.asarray(
                griddata(
                    np.column_stack((sample_x, sample_y)),
                    sample_values,
                    (grid_x, grid_y),
                    method="nearest",
                ),
                dtype=float,
            )
        except Exception:
            return None
    return result
