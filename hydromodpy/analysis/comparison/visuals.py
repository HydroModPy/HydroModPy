"""Visual comparison outputs for method-comparison runs."""

from __future__ import annotations

import csv
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

from hydromodpy.analysis.comparison.config import (
    MethodComparisonConfig,
    MethodComparisonFineRaster,
    MethodComparisonObservable,
    MethodComparisonVariant,
)
from hydromodpy.analysis.comparison.runtime import (
    VariableSeries,
    _bundle_dir_from_config,
    _resolve_recorded_output_path,
    discover_result_store,
    load_variable_series,
    mask_depth_series_from_head_nodata,
    read_json_file,
    resolve_bundle_cells,
    resolve_structured_shape_from_config,
    resolve_structured_shape_from_run_folder,
    select_time_slices,
)
from hydromodpy.core.config.toml_loader import load_toml_with_base_config

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection

try:
    from scipy.interpolate import griddata
except Exception:  # pragma: no cover - optional at runtime
    griddata = None

try:
    import rasterio
    from rasterio.transform import from_origin
except Exception:  # pragma: no cover - optional at runtime
    rasterio = None


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


@dataclass(frozen=True, slots=True)
class CaseConfigurationPayload:
    """Visual summary of the physical support used by one comparison."""

    comparison_id: str
    reference_variant: str
    variant_lines: tuple[str, ...]
    metadata_lines: tuple[str, ...]
    boundary_sides: tuple[tuple[str, str], ...]
    observable_points: tuple[tuple[float, float, str], ...]
    vertices: np.ndarray | None = None
    faces: np.ndarray | None = None
    surface_top: np.ndarray | None = None
    centroid_x: np.ndarray | None = None
    centroid_y: np.ndarray | None = None
    recharge_values: np.ndarray | None = None
    recharge_unit: str = ""


_TITLE_FONT_SIZE = 11
_PANEL_TITLE_FONT_SIZE = 9
_LABEL_FONT_SIZE = 9
_TICK_FONT_SIZE = 8
_LEGEND_FONT_SIZE = 9


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value).strip().lower())
    return text.strip("_") or "item"


def _pretty_label(value: str) -> str:
    text = re.sub(r"[_]+", " ", str(value).strip())
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1].upper() + text[1:] if text else "Value"


def _display_variant_label(*, variant_id: str, variant_label: str) -> str:
    text = variant_label.strip() or variant_id.strip()
    if len(text) <= 26:
        return text
    return variant_id.strip() or text


def _variant_panel_title(*, variant_id: str, variant_label: str, solver: str) -> str:
    label = _display_variant_label(variant_id=variant_id, variant_label=variant_label)
    solver_text = str(solver).strip().lower()
    if not solver_text:
        return label
    return f"{label}\n{solver_text}"


def _style_map_axes(ax: Any) -> None:
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlabel("")
    ax.set_ylabel("")
    for spine in ax.spines.values():
        spine.set_linewidth(0.6)
        spine.set_color("#9ca3af")


def _legend_ncols(n_items: int) -> int:
    if n_items <= 1:
        return 1
    if n_items <= 4:
        return 2
    return 3


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


def _solver_color(solver: str) -> str:
    """Return a stable color for ``solver``.

    Colors are pulled from matplotlib's ``tab10`` cycle and indexed by a
    deterministic hash of the solver name, so each name gets a consistent
    color across plots without requiring a per-solver registry.
    """
    import hashlib

    from matplotlib import colormaps

    key = str(solver).strip().lower()
    if not key:
        return "#6b7280"
    cmap = colormaps.get_cmap("tab10")
    digest = hashlib.md5(key.encode("utf-8")).digest()
    index = digest[0] % cmap.N
    return _rgba_to_hex(cmap(index))


def _rgba_to_hex(rgba: tuple[float, float, float, float]) -> str:
    r, g, b = (int(round(c * 255)) for c in rgba[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


def _is_flux_like_name(name: str) -> bool:
    key = str(name).strip().lower()
    return any(
        token in key
        for token in (
            "flux",
            "drain",
            "accumulation",
            "runoff",
            "surface_excess",
            "saturation_excess",
        )
    )


def _safe_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        number = float(value)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return number


def _rows_have_elapsed_seconds(rows: Iterable[Mapping[str, Any]]) -> bool:
    return all(_safe_float(row.get("elapsed_seconds")) is not None for row in rows)


def _row_time_value(row: Mapping[str, Any], *, use_elapsed_seconds: bool) -> float | None:
    return (
        _safe_float(row.get("elapsed_seconds"))
        if use_elapsed_seconds
        else _safe_float(row.get("time_index"))
    )


def _time_axis_label(*, use_elapsed_seconds: bool) -> str:
    return "Elapsed time [s]" if use_elapsed_seconds else "Time step"


def _mask_nodata(values: np.ndarray) -> np.ndarray:
    masked = np.asarray(values, dtype=float).copy()
    if masked.size == 0:
        return masked
    for sentinel in (-9999.0, -99999.0, -999999.0):
        masked[np.isclose(masked, sentinel, rtol=0.0, atol=1.0e-6)] = np.nan
    return masked


def _finite_limits(values: Iterable[np.ndarray]) -> tuple[float, float] | None:
    arrays = [
        _mask_nodata(np.asarray(item, dtype=float)).ravel()
        for item in values
        if np.asarray(item, dtype=float).size > 0
    ]
    if not arrays:
        return None
    stacked = np.concatenate(arrays)
    finite = stacked[np.isfinite(stacked)]
    if finite.size == 0:
        return None
    return float(np.nanmin(finite)), float(np.nanmax(finite))


def _robust_limits(
    values: Iterable[np.ndarray],
    *,
    lower_percentile: float = 2.0,
    upper_percentile: float = 98.0,
) -> tuple[float, float] | None:
    arrays = [
        _mask_nodata(np.asarray(item, dtype=float)).ravel()
        for item in values
        if np.asarray(item, dtype=float).size > 0
    ]
    if not arrays:
        return None
    stacked = np.concatenate(arrays)
    finite = stacked[np.isfinite(stacked)]
    if finite.size == 0:
        return None
    if finite.size < 24:
        return float(np.nanmin(finite)), float(np.nanmax(finite))
    lower = float(np.nanpercentile(finite, lower_percentile))
    upper = float(np.nanpercentile(finite, upper_percentile))
    if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
        return float(np.nanmin(finite)), float(np.nanmax(finite))
    return lower, upper


def _robust_symmetric_limit(
    values: Iterable[np.ndarray],
    *,
    percentile: float = 98.0,
) -> float | None:
    arrays = [
        _mask_nodata(np.asarray(item, dtype=float)).ravel()
        for item in values
        if np.asarray(item, dtype=float).size > 0
    ]
    if not arrays:
        return None
    stacked = np.concatenate(arrays)
    finite = stacked[np.isfinite(stacked)]
    if finite.size == 0:
        return None
    if finite.size < 24:
        vmax = float(np.nanmax(np.abs(finite)))
    else:
        vmax = float(np.nanpercentile(np.abs(finite), percentile))
    if not math.isfinite(vmax) or math.isclose(vmax, 0.0):
        vmax = float(np.nanmax(np.abs(finite)))
    if not math.isfinite(vmax) or math.isclose(vmax, 0.0):
        return None
    return vmax


def _format_time_tick_label(label: str) -> str:
    text = str(label).strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        if re.fullmatch(r"\d+", text):
            return text
        return text[:7] if len(text) >= 7 and text[4:5] == "-" else text
    return parsed.strftime("%b")


def _apply_time_ticks(
    ax: Any,
    *,
    tick_positions: list[float],
    tick_labels: list[str] | None = None,
) -> None:
    if not tick_positions:
        return
    unique_positions = sorted({float(value) for value in tick_positions})
    if len(unique_positions) <= 8:
        step = 1
    elif len(unique_positions) <= 16:
        step = 2
    else:
        step = max(1, int(math.ceil(len(unique_positions) / 6.0)))
    shown_positions = unique_positions[::step]
    if unique_positions[-1] not in shown_positions:
        shown_positions.append(unique_positions[-1])
    shown_labels: list[str] = []
    if tick_labels is None:
        shown_labels = [
            str(int(value)) if float(value).is_integer() else f"{value:g}"
            for value in shown_positions
        ]
    else:
        label_lookup = {
            float(position): _format_time_tick_label(label)
            for position, label in zip(tick_positions, tick_labels, strict=False)
        }
        shown_labels = [
            label_lookup.get(float(value), str(int(value))) for value in shown_positions
        ]
    ax.set_xticks(shown_positions)
    ax.set_xticklabels(shown_labels, fontsize=_TICK_FONT_SIZE)


def _series_style(observable_name: str) -> dict[str, Any]:
    if _is_flux_like_name(observable_name):
        return {"drawstyle": "steps-post", "linewidth": 1.8, "markersize": 0.0}
    return {"linewidth": 1.8, "markersize": 3.0, "marker": "o"}


def _surface_reference_lines(
    rows: Iterable[Mapping[str, Any]],
) -> list[tuple[str, str, float]]:
    """Return stable surface-elevation reference lines for point plots."""
    grouped: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        top = _safe_float(row.get("surface_top_m"))
        if top is None:
            continue
        key = (
            str(row.get("variant_id", "")),
            str(row.get("variant_label", row.get("variant_id", ""))),
        )
        grouped.setdefault(key, []).append(top)
    lines: list[tuple[str, str, float]] = []
    for (variant_id, variant_label), values in sorted(grouped.items()):
        finite = [value for value in values if math.isfinite(value)]
        if not finite:
            continue
        lines.append((variant_id, variant_label, float(np.nanmedian(finite))))
    if len(lines) <= 1:
        return lines
    top_values = np.asarray([line[2] for line in lines], dtype=float)
    if np.nanmax(top_values) - np.nanmin(top_values) <= 0.05:
        return [("surface", "Surface", float(np.nanmean(top_values)))]
    return lines


def _plot_surface_reference_lines(ax: Any, rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    for variant_id, variant_label, top in _surface_reference_lines(rows):
        if variant_id == "surface":
            color = "#111827"
            label = "Surface"
        else:
            color = _solver_color(variant_id)
            label = (
                "Surface "
                + _display_variant_label(variant_id=variant_id, variant_label=variant_label)
            )
        ax.axhline(
            top,
            color=color,
            linestyle=(0, (5, 3)),
            linewidth=1.15,
            alpha=0.72,
            label=label,
            zorder=1,
        )
        count += 1
    return count


def _safe_config_payload(config_path: Path | None) -> Mapping[str, Any]:
    if config_path is None:
        return {}
    try:
        payload = load_toml_with_base_config(config_path)
    except Exception:
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _read_zarr_array(group: Any, name: str) -> np.ndarray | None:
    try:
        if group is None or name not in group:
            return None
        return np.asarray(group[name][:])
    except Exception:
        return None


def _mesh_payload_from_store(store: Any, sim_id: str) -> tuple[np.ndarray | None, ...]:
    try:
        grp = store.open_zarr_group(sim_id)
    except Exception:
        return None, None, None
    try:
        mesh = grp.get("mesh") if grp is not None else None
    except Exception:
        return None, None, None
    vertices = _read_zarr_array(mesh, "vertices")
    faces = _read_zarr_array(mesh, "face_node_connectivity")
    surface_top = _read_zarr_array(mesh, "surface_top")
    if vertices is not None:
        vertices = np.asarray(vertices, dtype=float)
    if faces is not None:
        faces = np.asarray(faces, dtype=int)
    if surface_top is not None:
        surface_top = np.asarray(surface_top, dtype=float).reshape(-1)
    return vertices, faces, surface_top


def _bundle_dir_for_case(run_folder: Path, config_path: Path | None) -> Path | None:
    metrics = read_json_file(run_folder / "_metrics.json")
    boussinesq_summary = read_json_file(run_folder / "_boussinesq_summary.json")
    bundle_dir_raw = metrics.get("mesh_output_exchange_bundle_dir") or boussinesq_summary.get(
        "bundle_dir"
    )
    if bundle_dir_raw:
        bundle_dir = _resolve_recorded_output_path(bundle_dir_raw, base_dir=run_folder)
        if bundle_dir is not None and bundle_dir.exists():
            return bundle_dir
    if config_path is None:
        return None
    bundle_dir = _bundle_dir_from_config(config_path)
    if bundle_dir is not None and bundle_dir.exists():
        return bundle_dir
    return None


def _mesh_payload_from_bundle(bundle_dir: Path | None) -> tuple[np.ndarray | None, ...]:
    if bundle_dir is None:
        return None, None, None
    nodes_path = bundle_dir / "nodes.csv"
    cells_path = bundle_dir / "cells.csv"
    if not nodes_path.exists() or not cells_path.exists():
        return None, None, None

    node_ids: list[int] = []
    vertices: list[tuple[float, float, float]] = []
    with nodes_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                node_ids.append(int(row["node_id"]))
                z_raw = row.get("z_top")
                z_value = float(z_raw) if z_raw not in (None, "") else math.nan
                vertices.append((float(row["x"]), float(row["y"]), z_value))
            except Exception:
                continue
    if not vertices:
        return None, None, None

    node_index = {node_id: index for index, node_id in enumerate(node_ids)}
    faces: list[list[int]] = []
    surface_top: list[float] = []
    with cells_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            face: list[int] = []
            for key in ("n0", "n1", "n2", "n3"):
                raw = row.get(key)
                if raw in (None, ""):
                    continue
                try:
                    face.append(node_index[int(raw)])
                except Exception:
                    continue
            if len(face) < 3:
                continue
            faces.append(face)
            top_raw = row.get("z_top_mean") or row.get("z_top_centroid")
            try:
                surface_top.append(float(top_raw))
            except Exception:
                surface_top.append(math.nan)
    if not faces:
        return None, None, None

    max_face_size = max(len(face) for face in faces)
    face_array = np.full((len(faces), max_face_size), -1, dtype=int)
    for index, face in enumerate(faces):
        face_array[index, : len(face)] = np.asarray(face, dtype=int)
    return (
        np.asarray(vertices, dtype=float),
        face_array,
        np.asarray(surface_top, dtype=float),
    )


def _recharge_payload_from_store(store: Any, sim_id: str) -> tuple[np.ndarray | None, str]:
    try:
        grp = store.open_zarr_group(sim_id)
    except Exception:
        return None, ""
    try:
        forcing = grp.get("forcing") if grp is not None else None
        recharge = forcing.get("recharge") if forcing is not None and "recharge" in forcing else None
    except Exception:
        return None, ""
    if recharge is None:
        return None, ""

    candidate_groups = [recharge]
    try:
        candidate_groups.extend(
            recharge[key] for key in recharge.keys() if not hasattr(recharge[key], "shape")
        )
    except Exception:
        pass
    for candidate in candidate_groups:
        values = _read_zarr_array(candidate, "values")
        if values is None:
            continue
        arr = np.asarray(values, dtype=float).reshape(-1)
        if arr.size == 0:
            continue
        unit = ""
        try:
            unit = str(candidate.attrs.get("unit", ""))
        except Exception:
            unit = ""
        return arr, unit
    return None, ""


def _recharge_payload_from_config(config_payload: Mapping[str, Any]) -> tuple[np.ndarray | None, str]:
    data = config_payload.get("data")
    if not isinstance(data, Mapping):
        return None, ""
    recharge = data.get("recharge")
    if not isinstance(recharge, Mapping):
        return None, ""
    sources = recharge.get("sources")
    if not isinstance(sources, list):
        return None, ""
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        values = source.get("values")
        if values is None:
            continue
        try:
            arr = np.asarray(values, dtype=float).reshape(-1)
        except Exception:
            continue
        if arr.size:
            return arr, str(source.get("source_unit") or "mm/day")
    return None, ""


def _side_from_text(value: str) -> str | None:
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    for side in ("west", "east", "north", "south"):
        if side in text:
            return side
    return None


def _boundary_sides_from_config(config_payload: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    flow = config_payload.get("flow")
    if not isinstance(flow, Mapping):
        return ()
    active = {
        str(item).strip()
        for item in (flow.get("active_bc") or ())
        if str(item).strip()
    }
    bc = flow.get("bc")
    dirichlet = bc.get("dirichlet") if isinstance(bc, Mapping) else None
    if not isinstance(dirichlet, Mapping):
        return ()
    resolved: list[tuple[str, str]] = []
    for bc_id, payload in dirichlet.items():
        bc_name = str(bc_id).strip()
        if active and bc_name not in active:
            continue
        text_parts = [bc_name]
        if isinstance(payload, Mapping):
            text_parts.extend(str(payload.get(key, "")) for key in ("application_domain", "type"))
            value = payload.get("value", "")
        else:
            value = ""
        side = _side_from_text(" ".join(text_parts))
        if side is not None:
            label = f"{bc_name}={value}" if str(value).strip() else bc_name
            resolved.append((side, label))
    return tuple(resolved)


def _flow_param_summary_lines(config_payload: Mapping[str, Any]) -> tuple[str, ...]:
    flow = config_payload.get("flow")
    if not isinstance(flow, Mapping):
        return ()
    params = flow.get("param")
    if not isinstance(params, Mapping):
        return ()
    lines: list[str] = []
    for name in ("K", "Sy", "Ss"):
        payload = params.get(name)
        if not isinstance(payload, Mapping):
            continue
        value = ""
        section = payload.get("field_homogeneous")
        if isinstance(section, Mapping):
            value = str(section.get("value", ""))
        elif "value" in payload:
            value = str(payload.get("value", ""))
        unit = ""
        field = payload.get("field")
        if isinstance(field, Mapping):
            unit = str(field.get("unit", ""))
        if value:
            lines.append(f"{name}: {value}{(' ' + unit) if unit and unit not in value else ''}")
    return tuple(lines)


def _simulation_time_summary_lines(config_payload: Mapping[str, Any]) -> tuple[str, ...]:
    simulation = config_payload.get("simulation")
    if not isinstance(simulation, Mapping):
        return ()
    time_cfg = simulation.get("time")
    if not isinstance(time_cfg, Mapping):
        return ()
    lines = []
    start = str(time_cfg.get("start_datetime", "")).strip()
    end = str(time_cfg.get("end_datetime", "")).strip()
    step = str(time_cfg.get("step_value", "")).strip()
    unit = str(time_cfg.get("step_unit", "")).strip()
    if start or end:
        lines.append(f"time: {start or '?'} -> {end or '?'}")
    if step:
        lines.append(f"step: {step}{(' ' + unit) if unit and unit not in step else ''}")
    return tuple(lines)


def _face_centroids(vertices: np.ndarray | None, faces: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
    if vertices is None or faces is None or vertices.ndim != 2 or faces.ndim != 2:
        return np.asarray([], dtype=float), np.asarray([], dtype=float)
    valid_faces = []
    for face in np.asarray(faces, dtype=int):
        face = face[(face >= 0) & (face < vertices.shape[0])]
        if face.size >= 3:
            valid_faces.append(face)
    if not valid_faces:
        return np.asarray([], dtype=float), np.asarray([], dtype=float)
    centroids = np.asarray([vertices[face, :2].mean(axis=0) for face in valid_faces], dtype=float)
    return centroids[:, 0], centroids[:, 1]


def _observable_points_for_case(
    cfg: MethodComparisonConfig,
    *,
    centroid_x: np.ndarray | None,
    centroid_y: np.ndarray | None,
) -> tuple[tuple[float, float, str], ...]:
    points: list[tuple[float, float, str]] = []
    for observable in cfg.method_comparison.observable:
        if observable.support not in {"point", "outlet"}:
            continue
        x = observable.x
        y = observable.y
        if x is None or y is None:
            if (
                observable.cell_index is not None
                and centroid_x is not None
                and centroid_y is not None
                and 0 <= int(observable.cell_index) < int(centroid_x.size)
            ):
                x = float(centroid_x[int(observable.cell_index)])
                y = float(centroid_y[int(observable.cell_index)])
        if x is None or y is None:
            continue
        points.append((float(x), float(y), observable.name))
    return tuple(points[:12])


def _build_case_configuration_payload(
    *,
    cfg: MethodComparisonConfig,
    variant_summaries: list[dict[str, Any]],
    reference_variant: str | None,
) -> CaseConfigurationPayload | None:
    completed = [
        summary
        for summary in variant_summaries
        if str(summary.get("status", "")) in {"completed", "reused"}
    ]
    if not completed:
        return None
    selected = next(
        (summary for summary in completed if str(summary.get("id", "")) == str(reference_variant)),
        completed[0],
    )
    config_path_raw = selected.get("config_path")
    config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
    config_payload = _safe_config_payload(config_path)

    vertices = faces = surface_top = None
    recharge_values = None
    recharge_unit = ""
    store = None
    sim_id = None
    try:
        store, sim_id = discover_result_store(
            config_path,
            preferred_sim_id=(
                None if selected.get("sim_id") in (None, "") else str(selected.get("sim_id"))
            ),
            preferred_name=(
                None if selected.get("run_name") in (None, "") else str(selected.get("run_name"))
            ),
        )
        if store is not None and sim_id is not None:
            vertices, faces, surface_top = _mesh_payload_from_store(store, sim_id)
            recharge_values, recharge_unit = _recharge_payload_from_store(store, sim_id)
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass

    run_folder = Path(str(selected.get("run_folder", "")))
    if vertices is None or faces is None:
        vertices, faces, surface_top = _mesh_payload_from_bundle(
            _bundle_dir_for_case(run_folder, config_path)
        )
    cells = resolve_bundle_cells(run_folder, config_path=config_path)
    centroid_x = centroid_y = None
    if vertices is not None and faces is not None:
        centroid_x, centroid_y = _face_centroids(vertices, faces)
    if (centroid_x is None or centroid_x.size == 0) and cells is not None:
        centroid_x = np.asarray(cells.x, dtype=float)
        centroid_y = np.asarray(cells.y, dtype=float)
    if recharge_values is None:
        recharge_values, recharge_unit = _recharge_payload_from_config(config_payload)

    n_cells = (
        int(surface_top.size)
        if surface_top is not None and surface_top.size
        else int(centroid_x.size)
        if centroid_x is not None
        else 0
    )
    variant_lines = tuple(
        f"{summary.get('id', '')}: {summary.get('solver', '') or 'n/a'} / {summary.get('mesh_mode', '')}"
        for summary in completed
    )
    metadata_lines = (
        f"comparison: {cfg.method_comparison.comparison_id}",
        f"reference: {reference_variant or selected.get('id', '')}",
        f"n_cells: {n_cells}" if n_cells else "n_cells: n/a",
        *_simulation_time_summary_lines(config_payload),
        *_flow_param_summary_lines(config_payload),
    )
    return CaseConfigurationPayload(
        comparison_id=str(cfg.method_comparison.comparison_id),
        reference_variant=str(reference_variant or selected.get("id", "")),
        variant_lines=variant_lines,
        metadata_lines=tuple(metadata_lines),
        boundary_sides=_boundary_sides_from_config(config_payload),
        observable_points=_observable_points_for_case(
            cfg,
            centroid_x=centroid_x,
            centroid_y=centroid_y,
        ),
        vertices=vertices,
        faces=faces,
        surface_top=surface_top,
        centroid_x=centroid_x,
        centroid_y=centroid_y,
        recharge_values=recharge_values,
        recharge_unit=recharge_unit,
    )


def _boundary_edges_by_side(
    vertices: np.ndarray,
    faces: np.ndarray,
) -> dict[str, list[np.ndarray]]:
    edges: dict[tuple[int, int], int] = {}
    for face in np.asarray(faces, dtype=int):
        face = face[(face >= 0) & (face < vertices.shape[0])]
        if face.size < 3:
            continue
        for left, right in zip(face, np.roll(face, -1), strict=False):
            key = tuple(sorted((int(left), int(right))))
            edges[key] = edges.get(key, 0) + 1
    boundary = [edge for edge, count in edges.items() if count == 1]
    if not boundary:
        return {}
    xy = np.asarray(vertices[:, :2], dtype=float)
    xmin, ymin = np.nanmin(xy, axis=0)
    xmax, ymax = np.nanmax(xy, axis=0)
    span_x = max(float(xmax - xmin), 1.0)
    span_y = max(float(ymax - ymin), 1.0)
    tol_x = span_x * 0.03
    tol_y = span_y * 0.03
    result: dict[str, list[np.ndarray]] = {"west": [], "east": [], "south": [], "north": []}
    for edge in boundary:
        segment = xy[np.asarray(edge, dtype=int)]
        midpoint = segment.mean(axis=0)
        if abs(float(midpoint[0]) - float(xmin)) <= tol_x:
            result["west"].append(segment)
        elif abs(float(midpoint[0]) - float(xmax)) <= tol_x:
            result["east"].append(segment)
        elif abs(float(midpoint[1]) - float(ymin)) <= tol_y:
            result["south"].append(segment)
        elif abs(float(midpoint[1]) - float(ymax)) <= tol_y:
            result["north"].append(segment)
    return result


def _write_case_configuration_figure(
    *,
    path: Path,
    payload: CaseConfigurationPayload,
) -> bool:
    has_mesh = (
        payload.vertices is not None
        and payload.faces is not None
        and payload.vertices.size > 0
        and payload.faces.size > 0
    ) or (
        payload.centroid_x is not None
        and payload.centroid_y is not None
        and payload.centroid_x.size > 0
    )
    if not has_mesh and payload.recharge_values is None:
        return False

    figure, axes = plt.subplots(2, 2, figsize=(12.6, 8.4), squeeze=False)
    mesh_ax, recharge_ax, meta_ax, semantics_ax = np.asarray(axes, dtype=object).ravel()

    if payload.vertices is not None and payload.faces is not None and payload.vertices.size:
        polygons: list[np.ndarray] = []
        colors: list[float] = []
        surface = payload.surface_top
        for index, face in enumerate(np.asarray(payload.faces, dtype=int)):
            face = face[(face >= 0) & (face < payload.vertices.shape[0])]
            if face.size < 3:
                continue
            polygons.append(np.asarray(payload.vertices[face, :2], dtype=float))
            if surface is not None and index < surface.size and math.isfinite(float(surface[index])):
                colors.append(float(surface[index]))
            else:
                colors.append(float(index))
        if polygons:
            collection = PolyCollection(
                polygons,
                array=np.asarray(colors, dtype=float),
                cmap="terrain",
                edgecolors=(0.12, 0.16, 0.20, 0.22),
                linewidths=0.25,
            )
            mesh_ax.add_collection(collection)
            mesh_ax.autoscale_view()
            colorbar = figure.colorbar(collection, ax=mesh_ax, fraction=0.046, pad=0.02)
            colorbar.set_label(
                "surface top [m]" if payload.surface_top is not None else "cell",
                fontsize=_LABEL_FONT_SIZE,
            )
            colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
            boundary_edges = _boundary_edges_by_side(payload.vertices, payload.faces)
            side_colors = {
                "west": "#2563eb",
                "east": "#dc2626",
                "south": "#059669",
                "north": "#7c3aed",
            }
            for side, label in payload.boundary_sides:
                for segment in boundary_edges.get(side, []):
                    mesh_ax.plot(
                        segment[:, 0],
                        segment[:, 1],
                        color=side_colors.get(side, "#111827"),
                        linewidth=2.1,
                        solid_capstyle="round",
                    )
                mesh_ax.plot([], [], color=side_colors.get(side, "#111827"), linewidth=2.1, label=label)
    elif payload.centroid_x is not None and payload.centroid_y is not None:
        values = np.arange(payload.centroid_x.size, dtype=float)
        mesh_ax.scatter(payload.centroid_x, payload.centroid_y, c=values, s=22, cmap="viridis")

    for x, y, label in payload.observable_points:
        mesh_ax.scatter([x], [y], s=34, c="#111827", marker="o", edgecolors="white", linewidths=0.8)
        mesh_ax.text(x, y, f" {label}", fontsize=7, color="#111827", va="center")
    mesh_ax.set_title("Spatial support, topography, boundaries", fontsize=_TITLE_FONT_SIZE)
    mesh_ax.set_aspect("equal", adjustable="box")
    mesh_ax.tick_params(labelsize=_TICK_FONT_SIZE)
    if payload.boundary_sides:
        mesh_ax.legend(loc="upper right", fontsize=7, frameon=True)

    if payload.recharge_values is not None and payload.recharge_values.size > 0:
        values = np.asarray(payload.recharge_values, dtype=float).reshape(-1)
        recharge_ax.step(np.arange(values.size), values, where="post", color="#0f766e", linewidth=1.8)
        recharge_ax.fill_between(np.arange(values.size), values, step="post", color="#99f6e4", alpha=0.45)
        recharge_ax.set_ylabel(payload.recharge_unit or "recharge", fontsize=_LABEL_FONT_SIZE)
        recharge_ax.set_xlabel("forcing record", fontsize=_LABEL_FONT_SIZE)
    else:
        recharge_ax.text(0.5, 0.5, "No recharge forcing found", ha="center", va="center")
    recharge_ax.set_title("Recharge forcing", fontsize=_TITLE_FONT_SIZE)
    recharge_ax.grid(True, alpha=0.18, linewidth=0.6)
    recharge_ax.tick_params(labelsize=_TICK_FONT_SIZE)

    meta_ax.axis("off")
    meta_text = "\n".join([*payload.metadata_lines, "", "variants:", *payload.variant_lines])
    meta_ax.text(
        0.02,
        0.98,
        meta_text,
        ha="left",
        va="top",
        fontsize=9,
        family="monospace",
        linespacing=1.35,
    )
    meta_ax.set_title("Case metadata", fontsize=_TITLE_FONT_SIZE, loc="left")

    semantics_ax.axis("off")
    boundary_text = "\n".join(f"- {label} ({side})" for side, label in payload.boundary_sides)
    if not boundary_text:
        boundary_text = "- no side Dirichlet boundary detected"
    semantics = (
        "Interpretation notes\n\n"
        "Boundary conditions:\n"
        f"{boundary_text}\n\n"
        "For MF6/Boussinesq comparisons, inspect budgets before judging head differences:\n"
        "- fixed-head support can change effective recharge support,\n"
        "- Boussinesq reports prescribed-head outflow explicitly,\n"
        "- metrics are aligned on physical elapsed time."
    )
    semantics_ax.text(
        0.02,
        0.98,
        semantics,
        ha="left",
        va="top",
        fontsize=9,
        linespacing=1.35,
    )
    semantics_ax.set_title("Comparison semantics", fontsize=_TITLE_FONT_SIZE, loc="left")

    figure.suptitle(f"Comparison case configuration: {payload.comparison_id}", fontsize=13, y=0.985)
    figure.subplots_adjust(left=0.06, right=0.98, top=0.92, bottom=0.07, hspace=0.32, wspace=0.2)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


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

    config_path_raw = summary.get("config_path")
    config_path = None if config_path_raw in ("", None) else Path(str(config_path_raw))
    if config_path is None:
        config_path = cfg.resolve_variant_config_path(variant)

    store = None
    sim_id = None
    try:
        preferred_sim_id = summary.get("sim_id")
        preferred_name = summary.get("run_name")
        store, sim_id = discover_result_store(
            config_path,
            preferred_sim_id=None if preferred_sim_id in ("", None) else str(preferred_sim_id),
            preferred_name=None if preferred_name in ("", None) else str(preferred_name),
        )
        series = load_variable_series(
            run_folder=run_folder_path,
            variable=observable.variable,
            store=store,
            sim_id=sim_id,
        )
        series = mask_depth_series_from_head_nodata(
            run_folder=run_folder_path,
            series=series,
            store=store,
            sim_id=sim_id,
        )
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass

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


def _render_map_subplot(
    ax: Any,
    payload: MapPayload,
    *,
    cmap: str,
    vmin: float,
    vmax: float,
) -> Any:
    if payload.geometry_kind == "scatter":
        plot_values = _mask_nodata(payload.values)
        marker_size = max(8.0, min(48.0, 24000.0 / max(1, payload.values.size)))
        artist = ax.scatter(
            payload.x,
            payload.y,
            c=plot_values,
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
            s=marker_size,
            marker="s",
            linewidths=0.0,
        )
        ax.set_aspect("equal", adjustable="box")
        _style_map_axes(ax)
        return artist

    image = _mask_nodata(np.asarray(payload.values, dtype=float)).reshape(payload.structured_shape)
    imshow_kwargs: dict[str, Any] = {
        "origin": "lower",
        "cmap": cmap,
        "vmin": vmin,
        "vmax": vmax,
        "aspect": "auto",
    }
    if payload.extent is not None:
        imshow_kwargs["extent"] = payload.extent
        imshow_kwargs["aspect"] = "equal"
    artist = ax.imshow(
        image,
        **imshow_kwargs,
    )
    _style_map_axes(ax)
    return artist


def _render_difference_subplot(
    ax: Any,
    payload: DifferencePayload,
    *,
    cmap: str,
    vmax: float,
) -> Any:
    if payload.geometry_kind == "scatter":
        plot_values = _mask_nodata(payload.values)
        marker_size = max(8.0, min(48.0, 24000.0 / max(1, payload.values.size)))
        artist = ax.scatter(
            payload.x,
            payload.y,
            c=plot_values,
            cmap=cmap,
            vmin=-vmax,
            vmax=vmax,
            s=marker_size,
            marker="s",
            linewidths=0.0,
        )
        ax.set_aspect("equal", adjustable="box")
        _style_map_axes(ax)
        return artist

    image = _mask_nodata(np.asarray(payload.values, dtype=float)).reshape(payload.structured_shape)
    imshow_kwargs: dict[str, Any] = {
        "origin": "lower",
        "cmap": cmap,
        "vmin": -vmax,
        "vmax": vmax,
        "aspect": "auto",
    }
    if payload.extent is not None:
        imshow_kwargs["extent"] = payload.extent
        imshow_kwargs["aspect"] = "equal"
    artist = ax.imshow(
        image,
        **imshow_kwargs,
    )
    _style_map_axes(ax)
    return artist


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


def _write_map_comparison_figure(
    *,
    path: Path,
    observable_name: str,
    payloads: list[MapPayload],
) -> None:
    limits = _robust_limits(payload.values for payload in payloads)
    if limits is None:
        limits = _finite_limits(payload.values for payload in payloads)
    if limits is None:
        return
    vmin, vmax = limits
    if math.isclose(vmin, vmax):
        delta = abs(vmin) * 0.05 or 1.0
        vmin -= delta
        vmax += delta

    ncols = min(2, len(payloads))
    nrows = int(math.ceil(len(payloads) / float(ncols)))
    figure, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(4.6 * ncols, 4.1 * nrows + 0.7),
        squeeze=False,
    )
    axes_array = np.asarray(axes, dtype=object).ravel()
    artist = None
    used_axes = axes_array[: len(payloads)].tolist()
    for ax, payload in zip(used_axes, payloads, strict=False):
        artist = _render_map_subplot(ax, payload, cmap="viridis", vmin=vmin, vmax=vmax)
        ax.set_title(
            _variant_panel_title(
                variant_id=payload.variant_id,
                variant_label=payload.variant_label,
                solver=payload.solver or payload.mesh_mode,
            ),
            fontsize=_PANEL_TITLE_FONT_SIZE,
            pad=6,
        )
    for ax in axes_array[len(payloads) :]:
        ax.set_visible(False)
    if artist is not None:
        colorbar = figure.colorbar(
            artist,
            ax=used_axes,
            orientation="horizontal",
            pad=0.06,
            fraction=0.05,
            aspect=40,
        )
        colorbar.set_label(
            payloads[0].unit or "value",
            fontsize=_LABEL_FONT_SIZE,
            labelpad=4,
        )
        colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
    figure.suptitle(
        f"{_pretty_label(observable_name)} [{payloads[0].unit or 'native'}]  {payloads[0].time_label}",
        fontsize=_TITLE_FONT_SIZE,
        y=0.97,
    )
    figure.subplots_adjust(
        left=0.03,
        right=0.98,
        top=0.84,
        bottom=0.14,
        wspace=0.05,
        hspace=0.12,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def _write_difference_figure(
    *,
    path: Path,
    payload: DifferencePayload,
) -> None:
    vmax = _robust_symmetric_limit([payload.values])
    if vmax is None:
        limits = _finite_limits([payload.values])
        if limits is None:
            return
        vmax = max(abs(limits[0]), abs(limits[1]))
    if not math.isfinite(vmax) or math.isclose(vmax, 0.0):
        vmax = 1.0

    figure, ax = plt.subplots(1, 1, figsize=(5.3, 4.8))
    artist = _render_difference_subplot(ax, payload, cmap="coolwarm", vmax=vmax)
    ax.set_title(
        f"{payload.candidate_variant} minus {payload.reference_variant}",
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=6,
    )
    colorbar = figure.colorbar(
        artist,
        ax=ax,
        orientation="horizontal",
        pad=0.08,
        fraction=0.06,
        aspect=40,
    )
    colorbar.set_label(payload.unit or "difference", fontsize=_LABEL_FONT_SIZE, labelpad=4)
    colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
    figure.suptitle(
        f"{_pretty_label(payload.observable_name)} difference",
        fontsize=_TITLE_FONT_SIZE,
        y=0.96,
    )
    figure.subplots_adjust(left=0.04, right=0.98, top=0.84, bottom=0.16)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def _write_map_triptych_figure(
    *,
    path: Path,
    reference: MapPayload,
    candidate: MapPayload,
    difference: DifferencePayload,
) -> bool:
    limits = _robust_limits([reference.values, candidate.values])
    if limits is None:
        limits = _finite_limits([reference.values, candidate.values])
    if limits is None:
        return False
    vmin, vmax = limits
    if math.isclose(vmin, vmax):
        delta = abs(vmin) * 0.05 or 1.0
        vmin -= delta
        vmax += delta

    diff_vmax = _robust_symmetric_limit([difference.values])
    if diff_vmax is None:
        diff_limits = _finite_limits([difference.values])
        if diff_limits is None:
            return False
        diff_vmax = max(abs(diff_limits[0]), abs(diff_limits[1]))
    if not math.isfinite(diff_vmax) or math.isclose(diff_vmax, 0.0):
        diff_vmax = 1.0

    figure, axes = plt.subplots(1, 3, figsize=(13.8, 4.9), squeeze=False)
    ref_ax, cand_ax, diff_ax = np.asarray(axes, dtype=object).ravel().tolist()
    ref_artist = _render_map_subplot(ref_ax, reference, cmap="viridis", vmin=vmin, vmax=vmax)
    _render_map_subplot(cand_ax, candidate, cmap="viridis", vmin=vmin, vmax=vmax)
    diff_artist = _render_difference_subplot(
        diff_ax,
        difference,
        cmap="coolwarm",
        vmax=diff_vmax,
    )
    ref_ax.set_title(
        _variant_panel_title(
            variant_id=reference.variant_id,
            variant_label=reference.variant_label,
            solver=reference.solver or reference.mesh_mode,
        ),
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=6,
    )
    cand_ax.set_title(
        _variant_panel_title(
            variant_id=candidate.variant_id,
            variant_label=candidate.variant_label,
            solver=candidate.solver or candidate.mesh_mode,
        ),
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=6,
    )
    diff_ax.set_title(
        f"{candidate.variant_id} minus {reference.variant_id}",
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=6,
    )
    value_colorbar = figure.colorbar(
        ref_artist,
        ax=[ref_ax, cand_ax],
        orientation="horizontal",
        pad=0.08,
        fraction=0.055,
        aspect=38,
    )
    value_colorbar.set_label(reference.unit or "value", fontsize=_LABEL_FONT_SIZE, labelpad=4)
    value_colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
    diff_colorbar = figure.colorbar(
        diff_artist,
        ax=diff_ax,
        orientation="horizontal",
        pad=0.08,
        fraction=0.055,
        aspect=28,
    )
    diff_colorbar.set_label(reference.unit or "difference", fontsize=_LABEL_FONT_SIZE, labelpad=4)
    diff_colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
    figure.suptitle(
        f"{_pretty_label(reference.observable_name)} [{reference.unit or 'native'}]  "
        f"{reference.time_label}",
        fontsize=_TITLE_FONT_SIZE,
        y=0.97,
    )
    figure.subplots_adjust(left=0.03, right=0.98, top=0.84, bottom=0.18, wspace=0.08)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_timeseries_figure(
    *,
    path: Path,
    observable_name: str,
    unit: str,
    grouped_rows: list[dict[str, Any]],
) -> bool:
    use_elapsed_seconds = all(
        _safe_float(row.get("elapsed_seconds")) is not None for row in grouped_rows
    )
    x_label = "Elapsed time [s]" if use_elapsed_seconds else "Time index"

    series_payloads: dict[tuple[str, str, int], list[tuple[float, float]]] = {}
    for row in grouped_rows:
        value = _safe_float(row.get("value"))
        if value is None:
            continue
        x_value = (
            _safe_float(row.get("elapsed_seconds"))
            if use_elapsed_seconds
            else _safe_float(row.get("time_index"))
        )
        if x_value is None:
            continue
        key = (
            str(row.get("variant_id", "")),
            str(row.get("variant_label", row.get("variant_id", ""))),
            int(row.get("value_index", 0)),
        )
        series_payloads.setdefault(key, []).append((x_value, value))

    if not any(len(points) >= 2 for points in series_payloads.values()):
        return False

    figure, ax = plt.subplots(1, 1, figsize=(7.0, 4.1))
    tick_positions: list[float] = []
    for (variant_id, variant_label, value_index), points in sorted(series_payloads.items()):
        ordered = sorted(points, key=lambda item: item[0])
        if len(ordered) < 2:
            continue
        x_values = [item[0] for item in ordered]
        y_values = [item[1] for item in ordered]
        tick_positions.extend(x_values)
        label = _display_variant_label(
            variant_id=variant_id,
            variant_label=variant_label or variant_id,
        )
        if any(
            other_value_index != value_index and other_variant_id == variant_id
            for (other_variant_id, _, other_value_index) in series_payloads
        ):
            label = f"{label} [{value_index}]"
        style = _series_style(observable_name)
        ax.plot(x_values, y_values, label=label, **style)

    if not ax.lines:
        plt.close(figure)
        return False
    _plot_surface_reference_lines(ax, grouped_rows)
    ax.set_xlabel(x_label, fontsize=_LABEL_FONT_SIZE)
    ax.set_ylabel(unit or "value", fontsize=_LABEL_FONT_SIZE)
    ax.set_title(_pretty_label(observable_name), fontsize=_TITLE_FONT_SIZE, pad=8)
    ax.tick_params(labelsize=_TICK_FONT_SIZE)
    ax.grid(True, alpha=0.18, linewidth=0.6)
    ax.margins(x=0.03, y=0.08)
    if not use_elapsed_seconds:
        _apply_time_ticks(ax, tick_positions=tick_positions)
    legend = ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.21),
        ncol=_legend_ncols(len(ax.lines)),
        frameon=False,
        fontsize=_LEGEND_FONT_SIZE,
        handlelength=1.8,
        columnspacing=1.1,
        borderaxespad=0.0,
    )
    for line in legend.get_lines():
        line.set_linewidth(1.8)
    figure.subplots_adjust(left=0.11, right=0.98, top=0.86, bottom=0.29)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_runtime_bar_figure(
    *,
    path: Path,
    execution_rows: list[Mapping[str, Any]],
    reference_variant: str | None,
) -> bool:
    rows = [row for row in execution_rows if _safe_float(row.get("runtime_seconds")) is not None]
    if len(rows) < 2:
        return False
    ordered = sorted(rows, key=lambda item: float(item["runtime_seconds"]), reverse=True)
    labels = [
        _display_variant_label(
            variant_id=str(row.get("variant_id", "")),
            variant_label=str(row.get("variant_label", row.get("variant_id", ""))),
        )
        for row in ordered
    ]
    runtimes = [float(row["runtime_seconds"]) for row in ordered]
    colors = [_solver_color(str(row.get("solver", ""))) for row in ordered]

    figure_height = max(2.8, 0.72 * len(ordered) + 1.1)
    figure, ax = plt.subplots(1, 1, figsize=(7.4, figure_height))
    positions = np.arange(len(ordered))
    bars = ax.barh(positions, runtimes, color=colors, edgecolor="none", height=0.58)
    ax.set_yticks(positions, labels=labels, fontsize=_LABEL_FONT_SIZE)
    ax.set_xlabel("Runtime [s]", fontsize=_LABEL_FONT_SIZE)
    ax.tick_params(axis="x", labelsize=_TICK_FONT_SIZE)
    ax.grid(axis="x", alpha=0.22, linewidth=0.6)
    ax.set_title("Execution time comparison", fontsize=_TITLE_FONT_SIZE, pad=8)

    reference_runtime = None
    if reference_variant is not None:
        for row in ordered:
            if str(row.get("variant_id", "")) == reference_variant:
                reference_runtime = float(row["runtime_seconds"])
                break
    max_runtime = max(runtimes)
    for bar, row in zip(bars, ordered, strict=False):
        runtime = float(row["runtime_seconds"])
        speedup = (
            reference_runtime / runtime
            if reference_runtime is not None and runtime > 0.0
            else math.nan
        )
        annotation = f"{runtime:.2f} s"
        if math.isfinite(speedup):
            annotation += f"  ({speedup:.2f}x ref)"
        ax.text(
            runtime + max_runtime * 0.02,
            bar.get_y() + bar.get_height() / 2.0,
            annotation,
            va="center",
            ha="left",
            fontsize=_LEGEND_FONT_SIZE,
        )
    ax.set_xlim(0.0, max_runtime * 1.34)
    figure.subplots_adjust(left=0.28, right=0.97, top=0.87, bottom=0.16)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_point_dashboard(
    *,
    path: Path,
    rows: list[dict[str, Any]],
) -> bool:
    point_rows = [row for row in rows if str(row.get("support", "")) == "point"]
    observables = sorted(
        {str(row.get("observable", "")) for row in point_rows if row.get("observable")}
    )
    if len(observables) < 2:
        return False

    use_elapsed_seconds = _rows_have_elapsed_seconds(point_rows)
    grouped: dict[str, dict[tuple[str, str], list[tuple[float, float]]]] = {}
    for row in point_rows:
        observable_name = str(row.get("observable", ""))
        value = _safe_float(row.get("value"))
        x_value = _row_time_value(row, use_elapsed_seconds=use_elapsed_seconds)
        if not observable_name or value is None or x_value is None:
            continue
        key = (
            str(row.get("variant_id", "")),
            str(row.get("variant_label", row.get("variant_id", ""))),
        )
        grouped.setdefault(observable_name, {}).setdefault(key, []).append((x_value, value))

    plotted_observables = [
        name
        for name in observables
        if any(len(points) >= 2 for points in grouped.get(name, {}).values())
    ]
    if len(plotted_observables) < 2:
        return False

    figure, axes = plt.subplots(
        len(plotted_observables),
        1,
        figsize=(7.6, max(5.0, 2.25 * len(plotted_observables) + 0.7)),
        sharex=True,
        squeeze=False,
    )
    axes_flat = np.asarray(axes, dtype=object).ravel()
    tick_positions: list[float] = []
    for index, observable_name in enumerate(plotted_observables):
        ax = axes_flat[index]
        observable_rows = [
            row for row in point_rows if str(row.get("observable", "")) == observable_name
        ]
        for (variant_id, variant_label), points in sorted(grouped.get(observable_name, {}).items()):
            ordered = sorted(points, key=lambda item: item[0])
            if len(ordered) < 2:
                continue
            x_values = [item[0] for item in ordered]
            y_values = [item[1] for item in ordered]
            tick_positions.extend(x_values)
            style = _series_style(observable_name)
            ax.plot(
                x_values,
                y_values,
                color=_solver_color(variant_id),
                label=_display_variant_label(variant_id=variant_id, variant_label=variant_label),
                **style,
            )
        _plot_surface_reference_lines(ax, observable_rows)
        ax.set_title(
            _pretty_label(observable_name), fontsize=_PANEL_TITLE_FONT_SIZE, pad=5, loc="left"
        )
        unit = next(
            (
                str(row.get("unit", ""))
                for row in point_rows
                if str(row.get("observable", "")) == observable_name
                and str(row.get("unit", "")) != ""
            ),
            "m",
        )
        ax.set_ylabel(unit, fontsize=_LABEL_FONT_SIZE)
        ax.tick_params(labelsize=_TICK_FONT_SIZE)
        ax.grid(True, alpha=0.18, linewidth=0.6)
        ax.margins(x=0.02, y=0.08)
        if index == 0 and ax.lines:
            legend = ax.legend(
                loc="upper center",
                bbox_to_anchor=(0.5, 1.34),
                ncol=_legend_ncols(len(ax.lines)),
                frameon=False,
                fontsize=_LEGEND_FONT_SIZE,
                handlelength=2.0,
                columnspacing=1.2,
            )
            for line in legend.get_lines():
                line.set_linewidth(1.8)

    axes_flat[-1].set_xlabel(
        _time_axis_label(use_elapsed_seconds=use_elapsed_seconds),
        fontsize=_LABEL_FONT_SIZE,
    )
    if not use_elapsed_seconds:
        _apply_time_ticks(axes_flat[-1], tick_positions=tick_positions)
    figure.suptitle("Head chronicle comparison", fontsize=_TITLE_FONT_SIZE, y=0.985)
    figure.subplots_adjust(left=0.11, right=0.98, top=0.86, bottom=0.13, hspace=0.34)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_native_flux_panel(
    *,
    path: Path,
    variable: str,
    long_rows: list[Mapping[str, Any]],
    delta_rows: list[Mapping[str, Any]],
) -> bool:
    flux_rows = [row for row in long_rows if str(row.get("variable", "")) == variable]
    variant_keys = {
        str(row.get("variant_id", "")) for row in flux_rows if str(row.get("variant_id", "")) != ""
    }
    if len(variant_keys) < 2:
        return False

    series_payloads: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for row in flux_rows:
        value = _safe_float(row.get("value"))
        x_value = _safe_float(row.get("time_index"))
        if value is None or x_value is None:
            continue
        key = (
            str(row.get("variant_id", "")),
            str(row.get("variant_label", row.get("variant_id", ""))),
        )
        series_payloads.setdefault(key, []).append((int(x_value), value))
    if not any(len(points) >= 2 for points in series_payloads.values()):
        return False

    relevant_delta = [
        row
        for row in delta_rows
        if str(row.get("variable", "")) == variable
        and _safe_float(row.get("signed_error")) is not None
        and _safe_float(row.get("time_index")) is not None
    ]

    figure, axes = plt.subplots(2, 1, figsize=(7.5, 6.2), sharex=True)
    main_ax, delta_ax = axes
    tick_positions: list[float] = []
    tick_labels: list[str] = []
    for (variant_id, variant_label), points in sorted(series_payloads.items()):
        ordered = sorted(points, key=lambda item: item[0])
        label = _display_variant_label(
            variant_id=variant_id,
            variant_label=variant_label,
        )
        color = _solver_color(variant_id)
        tick_positions.extend(float(item[0]) for item in ordered)
        main_ax.step(
            [item[0] for item in ordered],
            [item[1] for item in ordered],
            where="post",
            linewidth=1.8,
            label=label,
            color=color,
        )
    main_ax.set_ylabel(_pretty_label(variable), fontsize=_LABEL_FONT_SIZE)
    main_ax.tick_params(labelsize=_TICK_FONT_SIZE)
    main_ax.grid(True, alpha=0.22, linewidth=0.6)
    legend = main_ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.14),
        ncol=_legend_ncols(len(series_payloads)),
        frameon=False,
        fontsize=_LEGEND_FONT_SIZE,
    )
    for line in legend.get_lines():
        line.set_linewidth(1.8)

    if relevant_delta:
        delta_groups: dict[str, list[tuple[int, float]]] = {}
        time_label_lookup: dict[int, str] = {}
        for row in relevant_delta:
            key = str(row.get("variant_id", ""))
            time_index = int(float(row["time_index"]))
            delta_groups.setdefault(key, []).append((time_index, float(row["signed_error"])))
            label = str(row.get("time_label", "")).strip()
            if label:
                time_label_lookup[time_index] = label
        for variant_id, points in sorted(delta_groups.items()):
            ordered = sorted(points, key=lambda item: item[0])
            delta_ax.step(
                [item[0] for item in ordered],
                [item[1] for item in ordered],
                where="post",
                linewidth=1.6,
                color=_solver_color(variant_id),
                label=_display_variant_label(variant_id=variant_id, variant_label=variant_id),
            )
        tick_labels = [
            time_label_lookup.get(int(value), str(int(value)))
            for value in sorted(time_label_lookup)
        ]
        delta_ax.axhline(0.0, color="#111827", linewidth=0.8, alpha=0.65)
    delta_ax.set_xlabel("Time step", fontsize=_LABEL_FONT_SIZE)
    delta_ax.set_ylabel("Delta vs ref", fontsize=_LABEL_FONT_SIZE)
    delta_ax.tick_params(labelsize=_TICK_FONT_SIZE)
    delta_ax.grid(True, alpha=0.22, linewidth=0.6)
    _apply_time_ticks(
        delta_ax,
        tick_positions=tick_positions,
        tick_labels=(tick_labels if tick_labels else None),
    )

    figure.suptitle(f"{_pretty_label(variable)} hydrograph", fontsize=_TITLE_FONT_SIZE, y=0.97)
    figure.subplots_adjust(left=0.12, right=0.98, top=0.9, bottom=0.18, hspace=0.25)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_flux_dashboard(
    *,
    path: Path,
    rows: list[dict[str, Any]],
    native_long_rows: list[Mapping[str, Any]],
) -> bool:
    panels: list[
        tuple[str, dict[tuple[str, str], list[tuple[float, float]]], list[str] | None]
    ] = []
    candidate_axis_rows = list(rows) + [dict(row) for row in native_long_rows]
    use_elapsed_seconds = _rows_have_elapsed_seconds(candidate_axis_rows)

    outlet_rows = [row for row in rows if str(row.get("observable", "")) == "outlet_flux_series"]
    if outlet_rows:
        grouped: dict[tuple[str, str], list[tuple[float, float]]] = {}
        for row in outlet_rows:
            value = _safe_float(row.get("value"))
            x_value = _row_time_value(row, use_elapsed_seconds=use_elapsed_seconds)
            if value is None or x_value is None:
                continue
            key = (
                str(row.get("variant_id", "")),
                str(row.get("variant_label", row.get("variant_id", ""))),
            )
            grouped.setdefault(key, []).append((x_value, value))
        if any(len(points) >= 2 for points in grouped.values()):
            panels.append(("Outlet flux [m3/s]", grouped, None))

    for variable in ("accumulation_flux", "outflow_drain"):
        grouped_native: dict[tuple[str, str], list[tuple[float, float]]] = {}
        time_labels: dict[int, str] = {}
        for row in native_long_rows:
            if str(row.get("variable", "")) != variable:
                continue
            value = _safe_float(row.get("value"))
            x_value = _row_time_value(row, use_elapsed_seconds=use_elapsed_seconds)
            if value is None or x_value is None:
                continue
            key = (
                str(row.get("variant_id", "")),
                str(row.get("variant_label", row.get("variant_id", ""))),
            )
            grouped_native.setdefault(key, []).append((x_value, value))
            label = str(row.get("time_label", "")).strip()
            if label:
                time_labels[int(round(float(x_value)))] = label
        if any(len(points) >= 2 for points in grouped_native.values()):
            labels = [time_labels[index] for index in sorted(time_labels)] if time_labels else None
            panels.append((_pretty_label(variable), grouped_native, labels))

    if len(panels) < 2:
        return False

    figure, axes = plt.subplots(
        len(panels),
        1,
        figsize=(7.6, max(5.6, 2.15 * len(panels) + 0.7)),
        sharex=True,
        squeeze=False,
    )
    axes_flat = np.asarray(axes, dtype=object).ravel()
    tick_positions: list[float] = []
    tick_labels: list[str] | None = None
    for index, (panel_title, grouped, labels) in enumerate(panels):
        ax = axes_flat[index]
        for (variant_id, variant_label), points in sorted(grouped.items()):
            ordered = sorted(points, key=lambda item: item[0])
            if len(ordered) < 2:
                continue
            x_values = [item[0] for item in ordered]
            y_values = [item[1] for item in ordered]
            tick_positions.extend(x_values)
            if labels:
                tick_labels = labels
            ax.step(
                x_values,
                y_values,
                where="post",
                linewidth=1.8,
                color=_solver_color(variant_id),
                label=_display_variant_label(variant_id=variant_id, variant_label=variant_label),
            )
        ax.set_title(panel_title, fontsize=_PANEL_TITLE_FONT_SIZE, pad=5, loc="left")
        ax.tick_params(labelsize=_TICK_FONT_SIZE)
        ax.grid(True, alpha=0.18, linewidth=0.6)
        ax.margins(x=0.02, y=0.08)
        if index == 0 and ax.lines:
            legend = ax.legend(
                loc="upper center",
                bbox_to_anchor=(0.5, 1.34),
                ncol=_legend_ncols(len(ax.lines)),
                frameon=False,
                fontsize=_LEGEND_FONT_SIZE,
                handlelength=2.0,
                columnspacing=1.2,
            )
            for line in legend.get_lines():
                line.set_linewidth(1.8)

    axes_flat[-1].set_xlabel(
        _time_axis_label(use_elapsed_seconds=use_elapsed_seconds),
        fontsize=_LABEL_FONT_SIZE,
    )
    if not use_elapsed_seconds:
        _apply_time_ticks(axes_flat[-1], tick_positions=tick_positions, tick_labels=tick_labels)
    figure.suptitle("Flux overview", fontsize=_TITLE_FONT_SIZE, y=0.985)
    figure.subplots_adjust(left=0.11, right=0.98, top=0.86, bottom=0.13, hspace=0.34)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _budget_component_label(component: str) -> str:
    labels = {
        "recharge_total_m3_s": "Recharge",
        "well_total_m3_s": "Wells",
        "drainage_total_m3_s": "Drainage",
        "prescribed_head_out_total_m3_s": "Fixed-head outflow",
        "evapotranspiration_total_m3_s": "Evapotranspiration",
        "surface_excess_total_m3_s": "Surface excess",
        "dry_deficit_total_m3_s": "Dry deficit",
        "storage_change_total_m3_s": "Storage change",
        "closure_residual_m3_s": "Closure residual",
    }
    return labels.get(component, _pretty_label(component))


def _budget_component_color(component: str) -> str:
    palette = {
        "recharge_total_m3_s": "#1f77b4",
        "well_total_m3_s": "#8c564b",
        "drainage_total_m3_s": "#ff7f0e",
        "prescribed_head_out_total_m3_s": "#9467bd",
        "evapotranspiration_total_m3_s": "#17becf",
        "surface_excess_total_m3_s": "#d62728",
        "dry_deficit_total_m3_s": "#b45309",
        "storage_change_total_m3_s": "#2ca02c",
        "closure_residual_m3_s": "#6b7280",
        "outlet_flux_series": "#111827",
    }
    return palette.get(component, "#6b7280")


def _write_budget_diagnostic_figure(
    *,
    path: Path,
    variant_id: str,
    variant_label: str,
    budget_rows: list[Mapping[str, Any]],
    rows: list[dict[str, Any]],
) -> bool:
    variant_budget_rows = [
        row for row in budget_rows if str(row.get("variant_id", "")) == variant_id
    ]
    if not variant_budget_rows:
        return False

    use_elapsed_seconds = all(
        _safe_float(row.get("elapsed_seconds")) is not None for row in variant_budget_rows
    )
    x_field = "elapsed_seconds" if use_elapsed_seconds else "time_index"
    x_label = "Elapsed time [s]" if use_elapsed_seconds else "Time step"

    component_groups: dict[str, list[tuple[float, float]]] = {}
    time_labels: dict[float, str] = {}
    for row in variant_budget_rows:
        component = str(row.get("component", "")).strip()
        x_value = _safe_float(row.get(x_field))
        value = _safe_float(row.get("value"))
        if not component or x_value is None or value is None:
            continue
        component_groups.setdefault(component, []).append((x_value, value))
        label = str(row.get("time_label", "")).strip()
        if label:
            time_labels[float(x_value)] = label

    if not component_groups:
        return False

    outlet_points: list[tuple[float, float]] = []
    for row in rows:
        if str(row.get("variant_id", "")) != variant_id:
            continue
        if str(row.get("observable", "")) != "outlet_flux_series":
            continue
        if str(row.get("unit", "")) != "m3/s":
            continue
        x_value = _safe_float(row.get(x_field))
        value = _safe_float(row.get("value"))
        if x_value is None or value is None:
            continue
        outlet_points.append((x_value, value))

    release_components = [
        component
        for component in (
            "drainage_total_m3_s",
            "prescribed_head_out_total_m3_s",
            "surface_excess_total_m3_s",
        )
        if component in component_groups
    ]
    balance_components = [
        component
        for component in (
            "recharge_total_m3_s",
            "well_total_m3_s",
            "dry_deficit_total_m3_s",
            "evapotranspiration_total_m3_s",
            "storage_change_total_m3_s",
            "closure_residual_m3_s",
        )
        if component in component_groups
    ]
    if not release_components and not balance_components and not outlet_points:
        return False

    figure, axes = plt.subplots(2, 1, figsize=(7.8, 6.8), sharex=True, squeeze=False)
    release_ax, balance_ax = np.asarray(axes, dtype=object).ravel()
    tick_positions: list[float] = []

    for component in release_components:
        ordered = sorted(component_groups[component], key=lambda item: item[0])
        x_values = [item[0] for item in ordered]
        y_values = [item[1] for item in ordered]
        tick_positions.extend(x_values)
        release_ax.step(
            x_values,
            y_values,
            where="post",
            linewidth=1.9,
            color=_budget_component_color(component),
            label=_budget_component_label(component),
        )
    if outlet_points:
        ordered = sorted(outlet_points, key=lambda item: item[0])
        x_values = [item[0] for item in ordered]
        y_values = [item[1] for item in ordered]
        tick_positions.extend(x_values)
        release_ax.step(
            x_values,
            y_values,
            where="post",
            linewidth=1.7,
            linestyle="--",
            color=_budget_component_color("outlet_flux_series"),
            label="Compared outlet flux",
        )
    release_ax.set_title("Release terms", fontsize=_PANEL_TITLE_FONT_SIZE, pad=5, loc="left")
    release_ax.set_ylabel("m3/s", fontsize=_LABEL_FONT_SIZE)
    release_ax.tick_params(labelsize=_TICK_FONT_SIZE)
    release_ax.grid(True, alpha=0.18, linewidth=0.6)
    release_ax.axhline(0.0, color="#9ca3af", linewidth=0.8, alpha=0.8)
    if release_ax.lines:
        legend = release_ax.legend(
            loc="upper center",
            bbox_to_anchor=(0.5, 1.32),
            ncol=_legend_ncols(len(release_ax.lines)),
            frameon=False,
            fontsize=_LEGEND_FONT_SIZE,
        )
        for line in legend.get_lines():
            line.set_linewidth(1.9)

    for component in balance_components:
        ordered = sorted(component_groups[component], key=lambda item: item[0])
        x_values = [item[0] for item in ordered]
        y_values = [item[1] for item in ordered]
        tick_positions.extend(x_values)
        linestyle = "--" if component == "closure_residual_m3_s" else "-"
        balance_ax.step(
            x_values,
            y_values,
            where="post",
            linewidth=1.8,
            linestyle=linestyle,
            color=_budget_component_color(component),
            label=_budget_component_label(component),
        )
    balance_ax.set_title("Inputs and storage", fontsize=_PANEL_TITLE_FONT_SIZE, pad=5, loc="left")
    balance_ax.set_ylabel("m3/s", fontsize=_LABEL_FONT_SIZE)
    balance_ax.set_xlabel(x_label, fontsize=_LABEL_FONT_SIZE)
    balance_ax.tick_params(labelsize=_TICK_FONT_SIZE)
    balance_ax.grid(True, alpha=0.18, linewidth=0.6)
    balance_ax.axhline(0.0, color="#9ca3af", linewidth=0.8, alpha=0.8)
    if balance_ax.lines:
        legend = balance_ax.legend(
            loc="upper center",
            bbox_to_anchor=(0.5, -0.2),
            ncol=_legend_ncols(len(balance_ax.lines)),
            frameon=False,
            fontsize=_LEGEND_FONT_SIZE,
        )
        for line in legend.get_lines():
            line.set_linewidth(1.8)
    if use_elapsed_seconds:
        label_positions = sorted(time_labels)
        _apply_time_ticks(
            balance_ax,
            tick_positions=label_positions if time_labels else tick_positions,
            tick_labels=[time_labels[position] for position in label_positions]
            if time_labels
            else None,
        )
    else:
        label_positions = sorted(time_labels)
        _apply_time_ticks(
            balance_ax,
            tick_positions=label_positions if time_labels else tick_positions,
            tick_labels=[time_labels[position] for position in label_positions]
            if time_labels
            else None,
        )
    figure.suptitle(
        f"Budget diagnostics: {_display_variant_label(variant_id=variant_id, variant_label=variant_label)}",
        fontsize=_TITLE_FONT_SIZE,
        y=0.98,
    )
    figure.subplots_adjust(left=0.11, right=0.98, top=0.85, bottom=0.18, hspace=0.36)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


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


def _write_regridded_map_figure(
    *,
    path: Path,
    observable_name: str,
    arrays: list[tuple[MapPayload, np.ndarray]],
    extent: tuple[float, float, float, float],
) -> bool:
    limits = _robust_limits(array for _, array in arrays)
    if limits is None:
        limits = _finite_limits(array for _, array in arrays)
    if limits is None:
        return False
    vmin, vmax = limits
    if math.isclose(vmin, vmax):
        delta = abs(vmin) * 0.05 or 1.0
        vmin -= delta
        vmax += delta
    ncols = min(2, len(arrays))
    nrows = int(math.ceil(len(arrays) / float(ncols)))
    figure, axes = plt.subplots(
        nrows, ncols, figsize=(4.8 * ncols, 4.1 * nrows + 0.7), squeeze=False
    )
    axes_array = np.asarray(axes, dtype=object).ravel()
    artist = None
    for ax, (payload, array) in zip(axes_array, arrays, strict=False):
        artist = ax.imshow(
            array,
            origin="lower",
            extent=extent,
            cmap="viridis",
            vmin=vmin,
            vmax=vmax,
            aspect="equal",
        )
        _style_map_axes(ax)
        ax.set_title(
            _variant_panel_title(
                variant_id=payload.variant_id,
                variant_label=payload.variant_label,
                solver=payload.solver or payload.mesh_mode,
            ),
            fontsize=_PANEL_TITLE_FONT_SIZE,
            pad=6,
        )
    for ax in axes_array[len(arrays) :]:
        ax.set_visible(False)
    if artist is not None:
        colorbar = figure.colorbar(
            artist,
            ax=axes_array[: len(arrays)].tolist(),
            orientation="horizontal",
            pad=0.06,
            fraction=0.05,
            aspect=40,
        )
        colorbar.set_label(arrays[0][0].unit or "value", fontsize=_LABEL_FONT_SIZE, labelpad=4)
        colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
    figure.suptitle(
        f"{_pretty_label(observable_name)} on fine raster",
        fontsize=_TITLE_FONT_SIZE,
        y=0.97,
    )
    figure.subplots_adjust(left=0.03, right=0.98, top=0.84, bottom=0.14, wspace=0.05, hspace=0.12)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_regridded_difference_figure(
    *,
    path: Path,
    observable_name: str,
    candidate_variant: str,
    reference_variant: str,
    array: np.ndarray,
    unit: str,
    extent: tuple[float, float, float, float],
) -> bool:
    vmax = _robust_symmetric_limit([array])
    if vmax is None:
        limits = _finite_limits([array])
        if limits is None:
            return False
        vmax = max(abs(limits[0]), abs(limits[1]))
    if not math.isfinite(vmax) or math.isclose(vmax, 0.0):
        vmax = 1.0
    figure, ax = plt.subplots(1, 1, figsize=(5.4, 4.8))
    artist = ax.imshow(
        array,
        origin="lower",
        extent=extent,
        cmap="coolwarm",
        vmin=-vmax,
        vmax=vmax,
        aspect="equal",
    )
    _style_map_axes(ax)
    ax.set_title(
        f"{candidate_variant} minus {reference_variant}",
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=6,
    )
    colorbar = figure.colorbar(
        artist,
        ax=ax,
        orientation="horizontal",
        pad=0.08,
        fraction=0.06,
        aspect=40,
    )
    colorbar.set_label(unit or "difference", fontsize=_LABEL_FONT_SIZE, labelpad=4)
    colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
    figure.suptitle(
        f"{_pretty_label(observable_name)} fine-raster difference",
        fontsize=_TITLE_FONT_SIZE,
        y=0.96,
    )
    figure.subplots_adjust(left=0.04, right=0.98, top=0.84, bottom=0.16)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_regridded_triptych_figure(
    *,
    path: Path,
    observable_name: str,
    reference_payload: MapPayload,
    candidate_payload: MapPayload,
    reference_array: np.ndarray,
    candidate_array: np.ndarray,
    extent: tuple[float, float, float, float],
) -> bool:
    limits = _robust_limits([reference_array, candidate_array])
    if limits is None:
        limits = _finite_limits([reference_array, candidate_array])
    if limits is None:
        return False
    vmin, vmax = limits
    if math.isclose(vmin, vmax):
        delta = abs(vmin) * 0.05 or 1.0
        vmin -= delta
        vmax += delta

    difference_array = np.asarray(candidate_array - reference_array, dtype=float)
    diff_vmax = _robust_symmetric_limit([difference_array])
    if diff_vmax is None:
        diff_limits = _finite_limits([difference_array])
        if diff_limits is None:
            return False
        diff_vmax = max(abs(diff_limits[0]), abs(diff_limits[1]))
    if not math.isfinite(diff_vmax) or math.isclose(diff_vmax, 0.0):
        diff_vmax = 1.0

    figure, axes = plt.subplots(1, 3, figsize=(13.8, 4.9), squeeze=False)
    ref_ax, cand_ax, diff_ax = np.asarray(axes, dtype=object).ravel().tolist()
    ref_artist = ref_ax.imshow(
        reference_array,
        origin="lower",
        extent=extent,
        cmap="viridis",
        vmin=vmin,
        vmax=vmax,
        aspect="equal",
    )
    cand_ax.imshow(
        candidate_array,
        origin="lower",
        extent=extent,
        cmap="viridis",
        vmin=vmin,
        vmax=vmax,
        aspect="equal",
    )
    diff_artist = diff_ax.imshow(
        difference_array,
        origin="lower",
        extent=extent,
        cmap="coolwarm",
        vmin=-diff_vmax,
        vmax=diff_vmax,
        aspect="equal",
    )
    for ax in (ref_ax, cand_ax, diff_ax):
        _style_map_axes(ax)
    ref_ax.set_title(
        _variant_panel_title(
            variant_id=reference_payload.variant_id,
            variant_label=reference_payload.variant_label,
            solver=reference_payload.solver or reference_payload.mesh_mode,
        ),
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=6,
    )
    cand_ax.set_title(
        _variant_panel_title(
            variant_id=candidate_payload.variant_id,
            variant_label=candidate_payload.variant_label,
            solver=candidate_payload.solver or candidate_payload.mesh_mode,
        ),
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=6,
    )
    diff_ax.set_title(
        f"{candidate_payload.variant_id} minus {reference_payload.variant_id}",
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=6,
    )
    value_colorbar = figure.colorbar(
        ref_artist,
        ax=[ref_ax, cand_ax],
        orientation="horizontal",
        pad=0.08,
        fraction=0.055,
        aspect=38,
    )
    value_colorbar.set_label(
        reference_payload.unit or "value",
        fontsize=_LABEL_FONT_SIZE,
        labelpad=4,
    )
    value_colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
    diff_colorbar = figure.colorbar(
        diff_artist,
        ax=diff_ax,
        orientation="horizontal",
        pad=0.08,
        fraction=0.055,
        aspect=28,
    )
    diff_colorbar.set_label(
        reference_payload.unit or "difference",
        fontsize=_LABEL_FONT_SIZE,
        labelpad=4,
    )
    diff_colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
    figure.suptitle(
        f"{_pretty_label(observable_name)} on fine raster [{reference_payload.unit or 'native'}]",
        fontsize=_TITLE_FONT_SIZE,
        y=0.97,
    )
    figure.subplots_adjust(left=0.03, right=0.98, top=0.84, bottom=0.18, wspace=0.08)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_geotiff(
    *,
    path: Path,
    array: np.ndarray,
    extent: tuple[float, float, float, float],
) -> bool:
    if rasterio is None:
        return False
    xmin, xmax, ymin, ymax = extent
    height, width = array.shape
    if height <= 0 or width <= 0:
        return False
    resolution_x = (xmax - xmin) / float(width)
    resolution_y = (ymax - ymin) / float(height)
    if resolution_x <= 0.0 or resolution_y <= 0.0:
        return False
    data = np.asarray(array, dtype="float32")
    nodata_value = np.float32(-9999.0)
    data_to_write = np.where(np.isfinite(data), data, nodata_value)
    transform = from_origin(xmin, ymax, resolution_x, resolution_y)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        transform=transform,
        crs="EPSG:2154",
        nodata=float(nodata_value),
    ) as dataset:
        dataset.write(data_to_write, 1)
    return True


def generate_comparison_figures(
    *,
    cfg: MethodComparisonConfig,
    variant_summaries: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    detail_metrics: list[dict[str, Any]],
    reference_variant: str | None,
    comparison_root: Path,
    native_timeseries_rows: list[dict[str, Any]] | None = None,
    native_timeseries_delta_rows: list[dict[str, Any]] | None = None,
    budget_rows: list[dict[str, Any]] | None = None,
    execution_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Generate best-effort PNG comparisons from extracted observables."""
    figure_root = comparison_root / "comparison_figures"
    figure_root.mkdir(parents=True, exist_ok=True)
    for existing_path in figure_root.glob("*"):
        if existing_path.is_file():
            try:
                existing_path.unlink()
            except OSError:
                pass

    completed_summaries = {
        str(summary.get("id", "")): summary
        for summary in variant_summaries
        if summary.get("status") in {"completed", "reused"}
    }
    variants = {variant.id: variant for variant in cfg.method_comparison.variant if variant.enabled}

    artifacts: list[dict[str, Any]] = []
    fine_raster = cfg.method_comparison.fine_raster
    try:
        case_payload = _build_case_configuration_payload(
            cfg=cfg,
            variant_summaries=variant_summaries,
            reference_variant=reference_variant,
        )
    except Exception:
        case_payload = None
    if case_payload is not None:
        case_path = figure_root / "case_configuration.png"
        if _write_case_configuration_figure(path=case_path, payload=case_payload):
            artifacts.append(
                {
                    "kind": "case_configuration",
                    "observable": "case_configuration",
                    "path": str(case_path),
                }
            )

    for observable in cfg.method_comparison.observable:
        if observable.support != "map":
            continue
        payloads: list[MapPayload] = []
        for variant_id, variant in variants.items():
            summary = completed_summaries.get(variant_id)
            if summary is None:
                continue
            try:
                payload = _build_map_payload(
                    cfg=cfg,
                    variant=variant,
                    summary=summary,
                    observable=observable,
                    rows=rows,
                )
            except Exception:
                payload = None
            if payload is not None:
                payloads.append(payload)

        if len(payloads) >= 1:
            map_path = figure_root / f"{_slug(observable.name)}__map_comparison.png"
            _write_map_comparison_figure(
                path=map_path,
                observable_name=observable.name,
                payloads=payloads,
            )
            if map_path.exists():
                artifacts.append(
                    {
                        "kind": "map_comparison",
                        "observable": observable.name,
                        "path": str(map_path),
                    }
                )

        if reference_variant is None:
            continue
        reference_payload = next(
            (payload for payload in payloads if payload.variant_id == reference_variant),
            None,
        )
        if reference_payload is None:
            continue
        for candidate in payloads:
            if candidate.variant_id == reference_variant:
                continue
            difference = _build_difference_payload(
                reference=reference_payload,
                candidate=candidate,
            )
            if difference is None:
                continue
            diff_path = figure_root / (
                f"{_slug(observable.name)}__difference__"
                f"{_slug(reference_variant)}__vs__{_slug(candidate.variant_id)}.png"
            )
            _write_difference_figure(path=diff_path, payload=difference)
            if diff_path.exists():
                artifacts.append(
                    {
                        "kind": "difference_map",
                        "observable": observable.name,
                        "reference_variant": reference_variant,
                        "candidate_variant": candidate.variant_id,
                        "path": str(diff_path),
                    }
                )
            triptych_path = figure_root / (
                f"{_slug(observable.name)}__triptych__"
                f"{_slug(reference_variant)}__vs__{_slug(candidate.variant_id)}.png"
            )
            if _write_map_triptych_figure(
                path=triptych_path,
                reference=reference_payload,
                candidate=candidate,
                difference=difference,
            ):
                artifacts.append(
                    {
                        "kind": "map_triptych",
                        "observable": observable.name,
                        "reference_variant": reference_variant,
                        "candidate_variant": candidate.variant_id,
                        "path": str(triptych_path),
                    }
                )

        if fine_raster is not None and fine_raster.enabled and griddata is not None:
            bounds = _resolve_fine_grid_bounds(
                payloads=payloads,
                fine_raster=fine_raster,
                reference_variant=reference_variant,
            )
            if bounds is not None:
                fine_grid = _build_fine_grid(
                    bounds=bounds,
                    resolution=float(fine_raster.resolution or 0.0),
                )
                if fine_grid is not None:
                    grid_x, grid_y, grid_extent = fine_grid
                    regridded: list[tuple[MapPayload, np.ndarray]] = []
                    for payload in payloads:
                        array = _regrid_payload(
                            payload=payload,
                            grid_x=grid_x,
                            grid_y=grid_y,
                            interpolation=fine_raster.interpolation,
                        )
                        if array is None:
                            continue
                        regridded.append((payload, array))
                        if fine_raster.write_geotiff:
                            raster_path = figure_root / (
                                f"{_slug(observable.name)}__fine_raster__"
                                f"{_slug(payload.variant_id)}.tif"
                            )
                            if _write_geotiff(path=raster_path, array=array, extent=grid_extent):
                                artifacts.append(
                                    {
                                        "kind": "fine_raster_geotiff",
                                        "observable": observable.name,
                                        "variant_id": payload.variant_id,
                                        "path": str(raster_path),
                                    }
                                )
                    if len(regridded) >= 1:
                        fine_map_path = figure_root / (
                            f"{_slug(observable.name)}__fine_raster_map_comparison.png"
                        )
                        if _write_regridded_map_figure(
                            path=fine_map_path,
                            observable_name=observable.name,
                            arrays=regridded,
                            extent=grid_extent,
                        ):
                            artifacts.append(
                                {
                                    "kind": "fine_raster_map_comparison",
                                    "observable": observable.name,
                                    "path": str(fine_map_path),
                                }
                            )
                    if reference_variant is not None:
                        reference_array = next(
                            (
                                array
                                for payload, array in regridded
                                if payload.variant_id == reference_variant
                            ),
                            None,
                        )
                        reference_payload = next(
                            (
                                payload
                                for payload, _array in regridded
                                if payload.variant_id == reference_variant
                            ),
                            None,
                        )
                        if reference_array is not None and reference_payload is not None:
                            for payload, array in regridded:
                                if payload.variant_id == reference_variant:
                                    continue
                                difference_array = np.asarray(array - reference_array, dtype=float)
                                triptych_path = figure_root / (
                                    f"{_slug(observable.name)}__fine_raster_triptych__"
                                    f"{_slug(reference_variant)}__vs__{_slug(payload.variant_id)}.png"
                                )
                                if _write_regridded_triptych_figure(
                                    path=triptych_path,
                                    observable_name=observable.name,
                                    reference_payload=reference_payload,
                                    candidate_payload=payload,
                                    reference_array=reference_array,
                                    candidate_array=array,
                                    extent=grid_extent,
                                ):
                                    artifacts.append(
                                        {
                                            "kind": "fine_raster_triptych",
                                            "observable": observable.name,
                                            "reference_variant": reference_variant,
                                            "candidate_variant": payload.variant_id,
                                            "path": str(triptych_path),
                                        }
                                    )
                                diff_path = figure_root / (
                                    f"{_slug(observable.name)}__fine_raster_difference__"
                                    f"{_slug(reference_variant)}__vs__{_slug(payload.variant_id)}.png"
                                )
                                if _write_regridded_difference_figure(
                                    path=diff_path,
                                    observable_name=observable.name,
                                    candidate_variant=payload.variant_id,
                                    reference_variant=reference_variant,
                                    array=difference_array,
                                    unit=payload.unit,
                                    extent=grid_extent,
                                ):
                                    artifacts.append(
                                        {
                                            "kind": "fine_raster_difference_map",
                                            "observable": observable.name,
                                            "reference_variant": reference_variant,
                                            "candidate_variant": payload.variant_id,
                                            "path": str(diff_path),
                                        }
                                    )
                                if fine_raster.write_geotiff:
                                    raster_path = figure_root / (
                                        f"{_slug(observable.name)}__fine_raster_difference__"
                                        f"{_slug(reference_variant)}__vs__{_slug(payload.variant_id)}.tif"
                                    )
                                    if _write_geotiff(
                                        path=raster_path,
                                        array=difference_array,
                                        extent=grid_extent,
                                    ):
                                        artifacts.append(
                                            {
                                                "kind": "fine_raster_difference_geotiff",
                                                "observable": observable.name,
                                                "reference_variant": reference_variant,
                                                "candidate_variant": payload.variant_id,
                                                "path": str(raster_path),
                                            }
                                        )

    grouped_rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
    {observable.name: observable.support for observable in cfg.method_comparison.observable}
    {observable.name: observable.variable for observable in cfg.method_comparison.observable}
    for row in rows:
        if str(row.get("support", "")) == "map":
            continue
        if str(row.get("comparison_time_key", "")) == "reduced":
            continue
        key = (str(row.get("observable", "")), str(row.get("unit", "")))
        grouped_rows.setdefault(key, []).append(row)

    for (observable_name, unit), grouped in sorted(grouped_rows.items()):
        series_path = figure_root / f"{_slug(observable_name)}__timeseries.png"
        if _write_timeseries_figure(
            path=series_path,
            observable_name=observable_name,
            unit=unit,
            grouped_rows=grouped,
        ):
            artifacts.append(
                {
                    "kind": "timeseries",
                    "observable": observable_name,
                    "unit": unit,
                    "path": str(series_path),
                }
            )

    native_long = list(native_timeseries_rows or [])
    native_delta = list(native_timeseries_delta_rows or [])

    point_dashboard_path = figure_root / "head_points_dashboard.png"
    if _write_point_dashboard(path=point_dashboard_path, rows=rows):
        artifacts.append(
            {
                "kind": "point_dashboard",
                "observable": "head_points",
                "path": str(point_dashboard_path),
            }
        )

    native_variables = sorted(
        {
            str(row.get("variable", ""))
            for row in native_long
            if _is_flux_like_name(str(row.get("variable", "")))
        }
    )
    for variable in native_variables:
        flux_path = figure_root / f"native_{_slug(variable)}__hydrograph.png"
        if _write_native_flux_panel(
            path=flux_path,
            variable=variable,
            long_rows=native_long,
            delta_rows=native_delta,
        ):
            artifacts.append(
                {
                    "kind": "native_flux_panel",
                    "observable": variable,
                    "path": str(flux_path),
                }
            )

    flux_dashboard_path = figure_root / "flux_overview.png"
    if _write_flux_dashboard(
        path=flux_dashboard_path,
        rows=rows,
        native_long_rows=native_long,
    ):
        artifacts.append(
            {
                "kind": "flux_dashboard",
                "observable": "flux_overview",
                "path": str(flux_dashboard_path),
            }
        )

    budget_long = list(budget_rows or [])
    budget_variants = sorted(
        {
            (
                str(row.get("variant_id", "")),
                str(row.get("variant_label", row.get("variant_id", ""))),
            )
            for row in budget_long
            if str(row.get("variant_id", "")) != ""
        }
    )
    for variant_id, variant_label in budget_variants:
        budget_path = figure_root / f"{_slug(variant_id)}__budget_diagnostics.png"
        if _write_budget_diagnostic_figure(
            path=budget_path,
            variant_id=variant_id,
            variant_label=variant_label,
            budget_rows=budget_long,
            rows=rows,
        ):
            artifacts.append(
                {
                    "kind": "budget_diagnostics",
                    "observable": "budget",
                    "variant_id": variant_id,
                    "path": str(budget_path),
                }
            )

    if execution_rows:
        runtime_path = figure_root / "execution_time_comparison.png"
        if _write_runtime_bar_figure(
            path=runtime_path,
            execution_rows=execution_rows,
            reference_variant=reference_variant,
        ):
            artifacts.append(
                {
                    "kind": "execution_time_bars",
                    "observable": "execution_time",
                    "path": str(runtime_path),
                }
            )

    return artifacts


__all__ = ("generate_comparison_figures",)
