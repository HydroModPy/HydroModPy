"""Runtime helpers for the method-comparison launcher."""

from __future__ import annotations

import csv
import json
import math
import numbers
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from hydromodpy.core.config.toml_loader import (
    load_toml_with_base_config,
    merge_toml_payloads,
)

from launchers.method_comparison.config import (
    MethodComparisonConfig,
    MethodComparisonObservableSchema,
    MethodComparisonVariantSchema,
)


@dataclass(frozen=True, slots=True)
class TimeSlice:
    """One variable payload at one simulation time index."""

    time_key: Any
    time_index: int
    values: np.ndarray
    elapsed_seconds: float | None = None
    is_initial_state: bool = False


@dataclass(frozen=True, slots=True)
class VariableSeries:
    """Loaded postprocess variable series."""

    variable_name: str
    source_path: Path
    slices: tuple[TimeSlice, ...]
    cell_ids: np.ndarray | None = None


@dataclass(frozen=True, slots=True)
class CellCentroidTable:
    """Minimal cell-centroid lookup loaded from a mesh exchange bundle."""

    cell_ids: np.ndarray
    x: np.ndarray
    y: np.ndarray

    def nearest_cell_id(self, *, x: float, y: float) -> int:
        """Return the cell id whose centroid is closest to ``(x, y)``."""
        distances = np.hypot(self.x - float(x), self.y - float(y))
        if distances.size == 0 or not np.any(np.isfinite(distances)):
            raise ValueError("Mesh bundle cells.csv contains no finite centroids")
        return int(self.cell_ids[int(np.nanargmin(distances))])


def _toml_scalar(value: Any) -> str:
    """Render one scalar or scalar list as TOML."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, numbers.Integral) and not isinstance(value, bool):
        return str(int(value))
    if isinstance(value, numbers.Real):
        number = float(value)
        if math.isfinite(number):
            return repr(number)
        raise ValueError("Cannot render non-finite numeric TOML value")
    if isinstance(value, Path):
        return json.dumps(value.as_posix())
    if isinstance(value, str):
        return json.dumps(value.replace("\\", "/"))
    if isinstance(value, list):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    if isinstance(value, tuple):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    raise TypeError(f"Unsupported TOML scalar type: {type(value).__name__}")


def _is_mapping_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, Mapping) for item in value)


def _render_toml_mapping(
    mapping: Mapping[str, Any],
    *,
    prefix: tuple[str, ...] = (),
) -> list[str]:
    """Render one nested TOML mapping with array-of-table support."""
    lines: list[str] = []
    scalar_items: list[tuple[str, Any]] = []
    nested_items: list[tuple[str, Mapping[str, Any]]] = []
    array_items: list[tuple[str, list[Mapping[str, Any]]]] = []

    for raw_key, value in mapping.items():
        key = str(raw_key)
        if isinstance(value, Mapping):
            nested_items.append((key, value))
        elif _is_mapping_list(value):
            array_items.append((key, value))
        else:
            scalar_items.append((key, value))

    for key, value in scalar_items:
        lines.append(f"{key} = {_toml_scalar(value)}")

    for key, value in nested_items:
        if lines and lines[-1] != "":
            lines.append("")
        section = ".".join((*prefix, key))
        lines.append(f"[{section}]")
        lines.extend(_render_toml_mapping(value, prefix=(*prefix, key)))

    for key, items in array_items:
        section = ".".join((*prefix, key))
        for item in items:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"[[{section}]]")
            lines.extend(_render_toml_mapping(item, prefix=(*prefix, key)))
    return lines


def write_toml_payload(path: Path, payload: Mapping[str, Any]) -> None:
    """Write a small generated TOML payload."""
    lines = _render_toml_mapping(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _deepcopy_jsonlike(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a TOML-like payload without retaining Pydantic internals."""
    return json.loads(json.dumps(payload))


def _overlay_defines_process(overlay: Mapping[str, Any]) -> bool:
    simulation = overlay.get("simulation")
    return isinstance(simulation, Mapping) and "process" in simulation


def _build_solver_process_overlay(
    *,
    base_config_path: Path,
    solver: str,
) -> list[dict[str, Any]] | None:
    """Build a process-list overlay changing the unique flow solver."""
    base_payload = load_toml_with_base_config(base_config_path)
    simulation = base_payload.get("simulation")
    if not isinstance(simulation, Mapping):
        return None
    processes = simulation.get("process")
    if not isinstance(processes, list) or not processes:
        return None

    flow_indices = [
        index
        for index, process in enumerate(processes)
        if isinstance(process, Mapping)
        and str(process.get("type", "")).strip().lower() == "flow"
    ]
    if len(flow_indices) != 1:
        return None

    overlays = [{} for _ in processes]
    overlays[flow_indices[0]] = {"solvers": [solver]}
    return overlays


def materialize_variant_config(
    *,
    cfg: MethodComparisonConfig,
    variant: MethodComparisonVariantSchema,
) -> Path | None:
    """Return the config path used by one variant, generating it if needed."""
    direct_config = cfg.resolve_variant_config_path(variant)
    if direct_config is not None:
        return direct_config

    base_config_path = cfg.base_simulation_config_path
    if base_config_path is None:
        return None

    overlay = _deepcopy_jsonlike(variant.overlay)
    simulation_overlay = overlay.setdefault("simulation", {})
    if isinstance(simulation_overlay, dict):
        simulation_overlay.setdefault("run_id", variant.id)
        if variant.solver is not None and not _overlay_defines_process(overlay):
            process_overlay = _build_solver_process_overlay(
                base_config_path=base_config_path,
                solver=variant.solver,
            )
            if process_overlay is not None:
                simulation_overlay["process"] = process_overlay

    payload = merge_toml_payloads(
        {"base_config": base_config_path.as_posix()},
        overlay,
    )
    generated_path = cfg.comparison_root / "_generated_configs" / f"{variant.id}.toml"
    write_toml_payload(generated_path, payload)
    return generated_path


def read_json_file(path: Path) -> dict[str, Any]:
    """Read one JSON object, returning an empty mapping when absent/invalid."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def compact_run_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only comparison-relevant scalar/list metrics in manifests."""
    keys = (
        "wall_time_seconds",
        "solvers",
        "success",
        "mesh_constraints_mode",
        "mesh_output_mesh",
        "mesh_output_summary_json",
        "mesh_output_exchange_bundle_dir",
    )
    return {key: metrics.get(key) for key in keys if key in metrics}


def read_variant_run_metadata(run_folder: Path) -> dict[str, Any]:
    """Collect lightweight run metadata useful in comparison manifests."""
    metrics = read_json_file(run_folder / "_metrics.json")
    boussinesq_summary = read_json_file(run_folder / "_boussinesq_summary.json")
    payload: dict[str, Any] = {}

    if metrics:
        payload["metrics"] = compact_run_metrics(metrics)
        if "wall_time_seconds" in metrics:
            payload["wall_time_seconds"] = metrics.get("wall_time_seconds")
        if "solvers" in metrics:
            payload["solvers"] = metrics.get("solvers")

    if boussinesq_summary:
        payload["boussinesq_summary"] = {
            key: boussinesq_summary.get(key)
            for key in (
                "n_cells",
                "n_edges",
                "n_nodes",
                "runtime_backend",
                "runtime_solver_kind",
                "solve_stage",
                "last_termination_reason",
            )
            if key in boussinesq_summary
        }
        for key in ("n_cells", "n_edges", "n_nodes"):
            if key in boussinesq_summary:
                payload[key] = boussinesq_summary.get(key)

    bundle_dir_raw = (
        metrics.get("mesh_output_exchange_bundle_dir")
        or boussinesq_summary.get("bundle_dir")
    )
    if bundle_dir_raw:
        bundle_dir = Path(str(bundle_dir_raw)).expanduser()
        if not bundle_dir.is_absolute():
            bundle_dir = (run_folder / bundle_dir).resolve()
        bundle_metadata = read_json_file(bundle_dir / "metadata.json")
        if bundle_metadata:
            payload["mesh_bundle_metadata"] = {
                key: bundle_metadata.get(key)
                for key in (
                    "bundle_schema_version",
                    "mesh_kind",
                    "cell_type",
                    "crs",
                    "n_nodes",
                    "n_cells",
                    "n_edges",
                    "constraints_mode",
                )
                if key in bundle_metadata
            }
            for key in ("n_cells", "n_edges", "n_nodes"):
                if key in bundle_metadata:
                    payload[key] = bundle_metadata.get(key)

    return payload


def resolve_bundle_cells(run_folder: Path) -> CellCentroidTable | None:
    """Load mesh cell centroids from the run metrics exchange bundle, if available."""
    metrics = read_json_file(run_folder / "_metrics.json")
    bundle_dir_raw = metrics.get("mesh_output_exchange_bundle_dir")
    if not bundle_dir_raw:
        boussinesq_summary = read_json_file(run_folder / "_boussinesq_summary.json")
        bundle_dir_raw = boussinesq_summary.get("bundle_dir")
    if not bundle_dir_raw:
        return None

    bundle_dir = Path(str(bundle_dir_raw)).expanduser()
    if not bundle_dir.is_absolute():
        bundle_dir = (run_folder / bundle_dir).resolve()
    cells_path = bundle_dir / "cells.csv"
    if not cells_path.exists():
        return None

    cell_ids: list[int] = []
    xs: list[float] = []
    ys: list[float] = []
    with cells_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                cell_ids.append(int(row["cell_id"]))
                xs.append(float(row["centroid_x"]))
                ys.append(float(row["centroid_y"]))
            except Exception:
                continue

    if not cell_ids:
        return None
    return CellCentroidTable(
        cell_ids=np.asarray(cell_ids, dtype=int),
        x=np.asarray(xs, dtype=float),
        y=np.asarray(ys, dtype=float),
    )


def _variable_candidates(variable: str) -> tuple[str, ...]:
    """Return postprocess file aliases for one observable variable."""
    key = variable.strip()
    lowered = key.lower()
    candidates = [key]
    alias_map = {
        "accumulation_flux": [
            "accumulation_flux",
            "drainage_flux_history_m3_s",
            "drainage_flux_m3_s",
        ],
        "outlet_discharge": ["outlet_discharge_east_side_m3_s"],
        "outlet_accumulation": [
            "accumulation_flux",
            "drainage_flux_history_m3_s",
            "drainage_flux_m3_s",
        ],
        "accumulation_outlet": [
            "accumulation_flux",
            "drainage_flux_history_m3_s",
            "drainage_flux_m3_s",
        ],
        "head": ["watertable_elevation"],
        "depth": ["watertable_depth"],
        "drainage_flux": ["drainage_flux_history_m3_s", "drainage_flux_m3_s"],
    }
    candidates.extend(alias_map.get(lowered, []))
    return tuple(dict.fromkeys(candidates))


def _native_unit_for_variable(variable_name: str) -> str:
    """Return a best-effort native unit label for known disk variables."""
    key = variable_name.strip().lower()
    if key in {"watertable_elevation", "head"}:
        return "m"
    if key == "watertable_depth":
        return "m"
    if key in {"accumulation_flux", "outflow_drain", "seepage_areas"}:
        return "m/day"
    if key.endswith("_m3_s") or "_m3_s" in key:
        return "m3/s"
    if key.endswith("_m_s") or "_m_s" in key:
        return "m/s"
    return ""


def _sort_time_key(key: Any) -> tuple[int, float | str]:
    if isinstance(key, numbers.Real):
        return (0, float(key))
    text = str(key)
    try:
        return (0, float(text))
    except ValueError:
        return (1, text)


def _coerce_series_from_mapping(
    mapping: Mapping[Any, Any],
    *,
    variable_name: str,
    source_path: Path,
    cell_ids: np.ndarray | None = None,
) -> VariableSeries:
    slices = tuple(
        TimeSlice(
            time_key=key,
            time_index=index,
            values=np.asarray(value, dtype=float).ravel(),
        )
        for index, (key, value) in enumerate(
            sorted(mapping.items(), key=lambda item: _sort_time_key(item[0]))
        )
    )
    return VariableSeries(
        variable_name=variable_name,
        source_path=source_path,
        slices=slices,
        cell_ids=cell_ids,
    )


def _load_npy_series(path: Path, *, variable_name: str) -> VariableSeries:
    payload = np.load(path, allow_pickle=True)
    if getattr(payload, "shape", None) == () and hasattr(payload, "item"):
        item = payload.item()
        if isinstance(item, Mapping):
            return _coerce_series_from_mapping(
                item,
                variable_name=variable_name,
                source_path=path,
            )
    arr = np.asarray(payload, dtype=float)
    if arr.ndim <= 1:
        slices = (TimeSlice(time_key=0, time_index=0, values=arr.ravel()),)
    else:
        slices = tuple(
            TimeSlice(
                time_key=index,
                time_index=index,
                values=np.asarray(row, dtype=float).ravel(),
            )
            for index, row in enumerate(arr)
        )
    return VariableSeries(variable_name=variable_name, source_path=path, slices=slices)


def _load_mesh_npz_series(path: Path, *, variable_name: str) -> VariableSeries:
    payload = np.load(path, allow_pickle=True)
    values = np.asarray(payload["values"], dtype=float)
    if "time_index" in payload:
        time_keys = list(payload["time_index"])
    elif "times" in payload:
        time_keys = list(payload["times"])
    else:
        time_keys = list(range(values.shape[0] if values.ndim > 1 else 1))
    elapsed_seconds = (
        np.asarray(payload["times"], dtype=float).ravel()
        if "times" in payload
        else None
    )
    cell_ids = (
        np.asarray(payload["cell_ids"], dtype=int)
        if "cell_ids" in payload
        else None
    )
    if values.ndim <= 1:
        elapsed = (
            float(elapsed_seconds[0])
            if elapsed_seconds is not None and elapsed_seconds.size > 0
            else None
        )
        slices = (
            TimeSlice(
                time_key=time_keys[0],
                time_index=0,
                values=values.ravel(),
                elapsed_seconds=elapsed,
            ),
        )
    else:
        slices = tuple(
            TimeSlice(
                time_key=time_keys[index],
                time_index=index,
                values=values[index].ravel(),
                elapsed_seconds=(
                    float(elapsed_seconds[index])
                    if elapsed_seconds is not None and index < elapsed_seconds.size
                    else None
                ),
            )
            for index in range(values.shape[0])
        )
    return VariableSeries(
        variable_name=variable_name,
        source_path=path,
        slices=slices,
        cell_ids=cell_ids,
    )


def _load_boussinesq_npz_series(
    path: Path,
    *,
    variable_name: str,
) -> VariableSeries:
    payload = np.load(path, allow_pickle=True)
    if variable_name not in payload:
        raise KeyError(variable_name)
    values = np.asarray(payload[variable_name], dtype=float)
    period_lengths = (
        np.asarray(payload["period_lengths_seconds"], dtype=float).ravel()
        if "period_lengths_seconds" in payload
        else np.asarray([], dtype=float)
    )
    if values.ndim <= 1:
        elapsed = (
            float(np.nansum(period_lengths))
            if period_lengths.size > 0
            else None
        )
        slices = (
            TimeSlice(
                time_key="final",
                time_index=max(0, int(period_lengths.size)),
                values=values.ravel(),
                elapsed_seconds=elapsed,
            ),
        )
    else:
        elapsed_by_index: list[float | None]
        if period_lengths.size == values.shape[0] - 1:
            elapsed_by_index = [0.0]
            elapsed_by_index.extend(float(value) for value in np.cumsum(period_lengths))
        elif period_lengths.size == values.shape[0]:
            elapsed_by_index = [float(value) for value in np.cumsum(period_lengths)]
        else:
            elapsed_by_index = [None for _ in range(values.shape[0])]
        slices = tuple(
            TimeSlice(
                time_key=index,
                time_index=index,
                values=values[index].ravel(),
                elapsed_seconds=elapsed_by_index[index],
                is_initial_state=period_lengths.size == values.shape[0] - 1
                and index == 0,
            )
            for index in range(values.shape[0])
        )
    return VariableSeries(variable_name=variable_name, source_path=path, slices=slices)


def load_variable_series(
    *,
    run_folder: Path,
    variable: str,
) -> VariableSeries:
    """Load one variable series from common postprocess disk artefacts."""
    postprocess_dir = run_folder / "_postprocess"
    searched: list[Path] = []
    for variable_name in _variable_candidates(variable):
        npy_path = postprocess_dir / f"{variable_name}.npy"
        searched.append(npy_path)
        if npy_path.exists():
            return _load_npy_series(npy_path, variable_name=variable_name)

        mesh_npz_path = postprocess_dir / "_mesh" / f"flow_{variable_name}.npz"
        searched.append(mesh_npz_path)
        if mesh_npz_path.exists():
            return _load_mesh_npz_series(mesh_npz_path, variable_name=variable_name)

        boussinesq_path = run_folder / "_boussinesq_state_history.npz"
        searched.append(boussinesq_path)
        if boussinesq_path.exists():
            try:
                return _load_boussinesq_npz_series(
                    boussinesq_path,
                    variable_name=variable_name,
                )
            except KeyError:
                pass

    searched_text = ", ".join(str(path) for path in searched)
    raise FileNotFoundError(
        f"Could not find postprocess variable '{variable}' in {run_folder}. "
        f"Searched: {searched_text}"
    )


def _select_time_slices(
    series: VariableSeries,
    observable: MethodComparisonObservableSchema,
) -> tuple[TimeSlice, ...]:
    """Select time slices requested by one observable."""
    if observable.time_window is not None:
        start, end = observable.time_window
        if isinstance(start, numbers.Real) and isinstance(end, numbers.Real):
            selected = [
                item
                for item in series.slices
                if item.elapsed_seconds is not None
                and float(start) <= float(item.elapsed_seconds) <= float(end)
            ]
        else:
            selected = [
                item
                for item in series.slices
                if str(start) <= str(item.time_key) <= str(end)
            ]
        return tuple(selected or series.slices)

    time_selector = observable.time
    if time_selector is None or str(time_selector).strip().lower() == "all":
        return series.slices
    selector_text = str(time_selector).strip().lower()
    if selector_text == "last":
        return (series.slices[-1],)
    if selector_text == "first":
        return (series.slices[0],)

    for item in series.slices:
        if str(item.time_key) == str(time_selector):
            return (item,)
    if isinstance(time_selector, numbers.Integral):
        index = int(time_selector)
        if -len(series.slices) <= index < len(series.slices):
            return (series.slices[index],)
    raise KeyError(
        f"Time selector {time_selector!r} not found for variable "
        f"'{series.variable_name}'"
    )


def _reduce(values: Any, *, reducer: str | None, label: str) -> tuple[float, ...]:
    """Reduce one numeric sequence."""
    arr = np.asarray(values, dtype=float).ravel()
    if arr.size == 0:
        raise ValueError(f"{label} cannot be empty")
    reducer_key = "identity" if reducer is None else str(reducer).strip().lower()
    if reducer_key in {"identity", "all", "none"}:
        return tuple(float(value) for value in arr)
    if reducer_key == "sum":
        return (float(np.nansum(arr)),)
    if reducer_key == "mean":
        return (float(np.nanmean(arr)),)
    if reducer_key == "min":
        return (float(np.nanmin(arr)),)
    if reducer_key == "max":
        return (float(np.nanmax(arr)),)
    if reducer_key == "absmax":
        finite = arr[np.isfinite(arr)]
        if finite.size == 0:
            return (float("nan"),)
        return (float(finite[int(np.argmax(np.abs(finite)))]),)
    if reducer_key == "first":
        return (float(arr[0]),)
    if reducer_key == "last":
        return (float(arr[-1]),)
    if reducer_key == "nearest_cell":
        if arr.size != 1:
            raise ValueError("nearest_cell reducer expects one selected cell value")
        return (float(arr[0]),)
    raise ValueError(f"Unsupported reducer '{reducer}' for {label}")


def _cell_position_for_cell_id(
    series: VariableSeries,
    *,
    cell_id: int,
) -> int:
    if series.cell_ids is not None:
        matches = np.flatnonzero(series.cell_ids == int(cell_id))
        if matches.size == 0:
            raise IndexError(f"cell_id {cell_id} is absent from {series.source_path}")
        return int(matches[0])
    return int(cell_id)


def _select_cell_values(
    *,
    series: VariableSeries,
    values: np.ndarray,
    cell_ids: list[int],
) -> np.ndarray:
    positions = [_cell_position_for_cell_id(series, cell_id=cell_id) for cell_id in cell_ids]
    if any(position >= values.size for position in positions):
        raise IndexError(
            f"cell index outside variable '{series.variable_name}' values "
            f"(size={values.size})"
        )
    return values[np.asarray(positions, dtype=int)]


def _select_spatial_values(
    *,
    series: VariableSeries,
    time_slice: TimeSlice,
    observable: MethodComparisonObservableSchema,
    cells: CellCentroidTable | None,
) -> tuple[tuple[float, ...], dict[str, Any]]:
    """Apply spatial selection for one observable/time slice."""
    values = np.asarray(time_slice.values, dtype=float).ravel()
    details: dict[str, Any] = {}

    if observable.support == "point":
        if observable.cell_index is not None:
            selected_cell_id = int(observable.cell_index)
        elif cells is not None and observable.x is not None and observable.y is not None:
            selected_cell_id = cells.nearest_cell_id(x=observable.x, y=observable.y)
        elif values.size == 1:
            return (float(values[0]),), {"selection": "scalar"}
        else:
            raise ValueError(
                f"Point observable '{observable.name}' needs a mesh bundle cells.csv "
                "for x/y lookup, or a cell_index."
            )
        selected = _select_cell_values(
            series=series,
            values=values,
            cell_ids=[selected_cell_id],
        )
        details["selected_cell_index"] = selected_cell_id
        details["selection"] = "nearest_cell"
        return _reduce(selected, reducer="nearest_cell", label=observable.name), details

    if observable.support == "outlet":
        if observable.cell_index is not None:
            selected_cell_ids = [int(observable.cell_index)]
            details["selection"] = "declared_cell"
        elif observable.x is not None and observable.y is not None and cells is not None:
            selected_cell_ids = [cells.nearest_cell_id(x=observable.x, y=observable.y)]
            details["selection"] = "nearest_declared_outlet_point"
        else:
            if not observable.allow_domain_proxy and values.size > 1:
                raise ValueError(
                    f"Outlet observable '{observable.name}' needs cell_index or x/y "
                    "coordinates for a strict outlet extraction."
                )
            selected_cell_ids = []
            details["selection"] = (
                "domain_reducer_proxy"
                if values.size > 1
                else "scalar_outlet_series"
            )
        if selected_cell_ids:
            selected = _select_cell_values(
                series=series,
                values=values,
                cell_ids=selected_cell_ids,
            )
            details["selected_cell_index"] = selected_cell_ids[0]
        else:
            selected = values
        return _reduce(selected, reducer=observable.reducer, label=observable.name), details

    if observable.support in {"boundary", "cell_mask"}:
        if observable.cell_indices:
            selected = _select_cell_values(
                series=series,
                values=values,
                cell_ids=[int(item) for item in observable.cell_indices],
            )
            details["selected_cell_indices"] = ",".join(
                str(item) for item in observable.cell_indices
            )
            details["selection"] = "declared_cell_indices"
        else:
            selected = values
            details["selection"] = "domain_reducer_proxy"
        return _reduce(selected, reducer=observable.reducer, label=observable.name), details

    if observable.support == "map":
        details["selection"] = "map"
        return _reduce(values, reducer=observable.reducer, label=observable.name), details

    raise KeyError(f"Unsupported observable support: {observable.support}")


def _time_match_key(time_slice: TimeSlice) -> str:
    """Return a stable key used to align rows across variants."""
    if str(time_slice.time_key) == "reduced":
        return "reduced"
    if time_slice.elapsed_seconds is not None and np.isfinite(time_slice.elapsed_seconds):
        return f"elapsed_seconds:{time_slice.elapsed_seconds:.9g}"
    return f"time_index:{time_slice.time_index}"


def extract_observable_rows(
    *,
    comparison_id: str,
    variant: MethodComparisonVariantSchema,
    run_folder: Path,
    observables: tuple[MethodComparisonObservableSchema, ...],
) -> list[dict[str, Any]]:
    """Extract all observable rows for one completed/reused variant."""
    rows: list[dict[str, Any]] = []
    cells = resolve_bundle_cells(run_folder)
    for observable in observables:
        series = load_variable_series(run_folder=run_folder, variable=observable.variable)
        selected_slices = _select_time_slices(series, observable)

        per_time_values: list[tuple[TimeSlice, tuple[float, ...], dict[str, Any]]] = []
        for time_slice in selected_slices:
            values, details = _select_spatial_values(
                series=series,
                time_slice=time_slice,
                observable=observable,
                cells=cells,
            )
            per_time_values.append((time_slice, values, details))

        if observable.time_reducer is not None:
            flat = [
                value
                for _, values, _ in per_time_values
                for value in values
            ]
            reduced_values = _reduce(
                flat,
                reducer=observable.time_reducer,
                label=f"{observable.name} time series",
            )
            reduced_slice = TimeSlice(
                time_key="reduced",
                time_index=-1,
                values=np.asarray(reduced_values, dtype=float),
            )
            per_time_values = [
                (reduced_slice, reduced_values, {"selection": "time_reduced"})
            ]

        for time_slice, values, details in per_time_values:
            for value_index, value in enumerate(values):
                native_unit = _native_unit_for_variable(series.variable_name)
                output_unit = observable.unit or native_unit
                rows.append(
                    {
                        "comparison_id": comparison_id,
                        "variant_id": variant.id,
                        "variant_label": variant.label or variant.id,
                        "solver": variant.solver or "",
                        "mesh_label": variant.mesh_label or "",
                        "mesh_mode": variant.mesh_mode,
                        "observable": observable.name,
                        "variable": observable.variable,
                        "resolved_variable": series.variable_name,
                        "support": observable.support,
                        "time": str(time_slice.time_key),
                        "time_index": time_slice.time_index,
                        "elapsed_seconds": (
                            ""
                            if time_slice.elapsed_seconds is None
                            else float(time_slice.elapsed_seconds)
                        ),
                        "is_initial_state": bool(time_slice.is_initial_state),
                        "comparison_time_key": _time_match_key(time_slice),
                        "value_index": value_index,
                        "value": float(value),
                        "unit": output_unit,
                        "configured_unit": observable.unit or "",
                        "native_unit": native_unit,
                        "source_path": str(series.source_path),
                        "run_folder": str(run_folder),
                        "selection": str(details.get("selection", "")),
                        "allow_domain_proxy": bool(observable.allow_domain_proxy),
                        "selected_cell_index": str(
                            details.get("selected_cell_index", "")
                        ),
                        "selected_cell_indices": str(
                            details.get("selected_cell_indices", "")
                        ),
                    }
                )
    return rows


def write_observables_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Persist long-format comparison observables."""
    fieldnames = [
        "comparison_id",
        "variant_id",
        "variant_label",
        "solver",
        "mesh_label",
        "mesh_mode",
        "observable",
        "variable",
        "resolved_variable",
        "support",
        "time",
        "time_index",
        "elapsed_seconds",
        "is_initial_state",
        "comparison_time_key",
        "value_index",
        "value",
        "unit",
        "configured_unit",
        "native_unit",
        "source_path",
        "run_folder",
        "selection",
        "allow_domain_proxy",
        "selected_cell_index",
        "selected_cell_indices",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


__all__ = (
    "CellCentroidTable",
    "TimeSlice",
    "VariableSeries",
    "extract_observable_rows",
    "load_variable_series",
    "materialize_variant_config",
    "compact_run_metrics",
    "read_json_file",
    "read_variant_run_metadata",
    "resolve_bundle_cells",
    "write_observables_csv",
    "write_toml_payload",
)
