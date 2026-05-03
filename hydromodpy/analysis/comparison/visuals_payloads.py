"""Payload dataclasses and builders for comparison visuals."""

from __future__ import annotations

import csv
import math
from collections.abc import Mapping
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
from hydromodpy.analysis.comparison.runtime_mesh import (
    resolve_bundle_cells,
    resolve_structured_shape_from_config,
    resolve_structured_shape_from_run_folder,
)
from hydromodpy.analysis.comparison.runtime_metadata import (
    _resolve_recorded_output_path,
    discover_result_store,
    read_json_file,
)
from hydromodpy.analysis.comparison.runtime_observables import select_time_slices
from hydromodpy.analysis.comparison.runtime_series import (
    VariableSeries,
    load_variable_series,
    mask_depth_series_from_head_nodata,
)
from hydromodpy.analysis.comparison.visuals_style import _mask_nodata
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

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
        values = group[name]
        return np.asarray(values[:] if hasattr(values, "__getitem__") else values)
    except Exception:
        return None


def _open_store_root(store: Any, sim_id: str) -> tuple[Any, Any]:
    if hasattr(store, "open_zarr_group"):
        return store.open_zarr_group(sim_id), None
    handle = store.open_zarr(sim_id)
    return getattr(handle, "root", None), handle


def _mesh_payload_from_store(store: Any, sim_id: str) -> tuple[np.ndarray | None, ...]:
    handle = None
    try:
        grp, handle = _open_store_root(store, sim_id)
        mesh = grp.get("mesh") if grp is not None else None
        vertices = _read_zarr_array(mesh, "vertices")
        faces = _read_zarr_array(mesh, "face_node_connectivity")
        surface_top = _read_zarr_array(mesh, "surface_top")
    except Exception:
        return None, None, None
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
    if vertices is not None:
        vertices = np.asarray(vertices, dtype=float)
    if faces is not None:
        faces = np.asarray(faces, dtype=int)
    if surface_top is not None:
        surface_top = np.asarray(surface_top, dtype=float).reshape(-1)
    return vertices, faces, surface_top


def _bundle_dir_from_config(config_path: Path) -> Path | None:
    payload = _safe_config_payload(config_path)
    mesh_input = payload.get("mesh_input")
    if not isinstance(mesh_input, Mapping):
        return None
    bundle_dir_raw = mesh_input.get("bundle_dir")
    if bundle_dir_raw in (None, ""):
        return None
    return _resolve_recorded_output_path(bundle_dir_raw, base_dir=config_path.parent)


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
    handle = None
    try:
        grp, handle = _open_store_root(store, sim_id)
        forcing = grp.get("forcing") if grp is not None else None
        recharge = (
            forcing.get("recharge") if forcing is not None and "recharge" in forcing else None
        )
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
    except Exception:
        return None, ""
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass


def _recharge_payload_from_config(
    config_payload: Mapping[str, Any],
) -> tuple[np.ndarray | None, str]:
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
    active = {str(item).strip() for item in (flow.get("active_bc") or ()) if str(item).strip()}
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
    lines: list[str] = []
    start = str(time_cfg.get("start_datetime", "")).strip()
    end = str(time_cfg.get("end_datetime", "")).strip()
    step = str(time_cfg.get("step_value", "")).strip()
    unit = str(time_cfg.get("step_unit", "")).strip()
    if start or end:
        lines.append(f"time: {start or '?'} -> {end or '?'}")
    if step:
        lines.append(f"step: {step}{(' ' + unit) if unit and unit not in step else ''}")
    return tuple(lines)


def _face_centroids(
    vertices: np.ndarray | None, faces: np.ndarray | None
) -> tuple[np.ndarray, np.ndarray]:
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
        store, sim_id = discover_result_store(config_path)
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
            store.close()
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
