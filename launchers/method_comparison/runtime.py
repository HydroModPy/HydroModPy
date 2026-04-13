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

try:
    import rasterio
except Exception:  # pragma: no cover - optional dependency in lightweight envs
    rasterio = None


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
    area_m2: np.ndarray | None = None
    storage_coefficient: np.ndarray | None = None

    def nearest_cell_id(self, *, x: float, y: float) -> int:
        """Return the cell id whose centroid is closest to ``(x, y)``."""
        distances = np.hypot(self.x - float(x), self.y - float(y))
        if distances.size == 0 or not np.any(np.isfinite(distances)):
            raise ValueError("Mesh bundle cells.csv contains no finite centroids")
        return int(self.cell_ids[int(np.nanargmin(distances))])

    def area_for_cell_id(self, cell_id: int) -> float | None:
        """Return the area for one cell id when the bundle exposes it."""
        if self.area_m2 is None or self.area_m2.size != self.cell_ids.size:
            return None
        matches = np.flatnonzero(self.cell_ids == int(cell_id))
        if matches.size == 0:
            return None
        area = float(self.area_m2[int(matches[0])])
        if not np.isfinite(area) or area <= 0.0:
            return None
        return area

    def storage_for_cell_id(self, cell_id: int) -> float | None:
        """Return the storage coefficient for one cell id when available."""
        if (
            self.storage_coefficient is None
            or self.storage_coefficient.size != self.cell_ids.size
        ):
            return None
        matches = np.flatnonzero(self.cell_ids == int(cell_id))
        if matches.size == 0:
            return None
        storage = float(self.storage_coefficient[int(matches[0])])
        if not np.isfinite(storage):
            return None
        return storage


def _candidate_solver_sections(solver_name: str | None = None) -> tuple[str, ...]:
    sections: list[str] = []
    if solver_name:
        sections.append(str(solver_name).strip().lower())
    sections.extend(("modflow6", "modflownwt"))
    return tuple(dict.fromkeys(section for section in sections if section))


def resolve_structured_shape_from_config(
    config_path: Path,
    *,
    solver_name: str | None = None,
) -> tuple[int, int] | None:
    """Return `(nrow, ncol)` for one structured solver config when declared."""
    try:
        payload = load_toml_with_base_config(config_path)
    except Exception:
        return None

    for section_name in _candidate_solver_sections(solver_name):
        section = payload.get(section_name)
        if not isinstance(section, Mapping):
            continue
        sgrid = section.get("sgrid")
        if not isinstance(sgrid, Mapping):
            continue
        planar = sgrid.get("planar")
        if not isinstance(planar, Mapping):
            continue
        try:
            nx = int(planar["nx"])
            ny = int(planar["ny"])
        except Exception:
            continue
        if nx > 0 and ny > 0:
            return (ny, nx)
    return None


def resolve_structured_shape_from_run_folder(run_folder: Path) -> tuple[int, int] | None:
    """Return `(nrow, ncol)` from one solver grid template written in the run folder."""
    if rasterio is None:
        return None
    raster_path = run_folder / "_solver_grid_template.tif"
    if not raster_path.exists():
        return None
    try:
        with rasterio.open(raster_path) as dataset:
            nrow = int(dataset.height)
            ncol = int(dataset.width)
    except Exception:
        return None
    if nrow <= 0 or ncol <= 0:
        return None
    return (nrow, ncol)


def _structured_bounds_from_run_folder(
    run_folder: Path,
) -> tuple[float, float, float, float] | None:
    if rasterio is None:
        return None
    raster_path = run_folder / "_solver_grid_template.tif"
    if not raster_path.exists():
        return None
    try:
        with rasterio.open(raster_path) as dataset:
            bounds = dataset.bounds
    except Exception:
        return None
    return (
        float(bounds.left),
        float(bounds.bottom),
        float(bounds.right),
        float(bounds.top),
    )


def _resolve_project_root_from_config(config_path: Path) -> Path | None:
    try:
        payload = load_toml_with_base_config(config_path)
    except Exception:
        return None
    workspace = payload.get("workspace")
    if not isinstance(workspace, Mapping):
        return None
    project_root = workspace.get("project_root")
    if project_root in (None, ""):
        return None
    resolved = Path(str(project_root)).expanduser()
    if not resolved.is_absolute():
        resolved = config_path.parent / resolved
    return resolved.resolve()


def _candidate_structured_support_rasters(project_root: Path) -> tuple[Path, ...]:
    geographic_dir = project_root / "results_stable" / "geographic"
    return (
        geographic_dir / "watershed_box_buff_dem.tif",
        geographic_dir / "watershed_dem.tif",
        geographic_dir / "watershed_box_buff_fill.tif",
        geographic_dir / "watershed_fill.tif",
        geographic_dir / "watershed.tif",
    )


def _structured_bounds_from_config(config_path: Path) -> tuple[float, float, float, float] | None:
    if rasterio is None:
        return None
    project_root = _resolve_project_root_from_config(config_path)
    if project_root is None:
        return None
    for raster_path in _candidate_structured_support_rasters(project_root):
        if not raster_path.exists():
            continue
        try:
            with rasterio.open(raster_path) as dataset:
                bounds = dataset.bounds
        except Exception:
            continue
        return (
            float(bounds.left),
            float(bounds.bottom),
            float(bounds.right),
            float(bounds.top),
        )
    return None


def _structured_cells_from_config(
    *,
    config_path: Path,
    solver_name: str | None = None,
    expected_size: int | None = None,
) -> CellCentroidTable | None:
    shape = resolve_structured_shape_from_config(config_path, solver_name=solver_name)
    if shape is None:
        return None
    nrow, ncol = shape
    n_cells = int(nrow) * int(ncol)
    if expected_size is not None and n_cells != int(expected_size):
        return None
    bounds = _structured_bounds_from_config(config_path)
    if bounds is None:
        return None
    xmin, ymin, xmax, ymax = bounds
    dx = (xmax - xmin) / float(ncol)
    dy = (ymax - ymin) / float(nrow)
    if dx <= 0.0 or dy <= 0.0:
        return None
    x_values = xmin + (np.arange(ncol, dtype=float) + 0.5) * dx
    y_values = ymax - (np.arange(nrow, dtype=float) + 0.5) * dy
    grid_x, grid_y = np.meshgrid(x_values, y_values)
    area_m2 = np.full(n_cells, float(dx) * float(dy), dtype=float)
    return CellCentroidTable(
        cell_ids=np.arange(n_cells, dtype=int),
        x=grid_x.reshape(-1),
        y=grid_y.reshape(-1),
        area_m2=area_m2,
        storage_coefficient=None,
    )


def _structured_cells_from_run_folder(
    *,
    run_folder: Path,
    expected_size: int | None = None,
) -> CellCentroidTable | None:
    shape = resolve_structured_shape_from_run_folder(run_folder)
    if shape is None:
        return None
    nrow, ncol = shape
    n_cells = int(nrow) * int(ncol)
    if expected_size is not None and n_cells != int(expected_size):
        return None
    bounds = _structured_bounds_from_run_folder(run_folder)
    if bounds is None:
        return None
    xmin, ymin, xmax, ymax = bounds
    dx = (xmax - xmin) / float(ncol)
    dy = (ymax - ymin) / float(nrow)
    if dx <= 0.0 or dy <= 0.0:
        return None
    x_values = xmin + (np.arange(ncol, dtype=float) + 0.5) * dx
    y_values = ymax - (np.arange(nrow, dtype=float) + 0.5) * dy
    grid_x, grid_y = np.meshgrid(x_values, y_values)
    area_m2 = np.full(n_cells, float(dx) * float(dy), dtype=float)
    return CellCentroidTable(
        cell_ids=np.arange(n_cells, dtype=int),
        x=grid_x.reshape(-1),
        y=grid_y.reshape(-1),
        area_m2=area_m2,
        storage_coefficient=None,
    )


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


def _resolve_recorded_output_path(
    raw_path: Any,
    *,
    base_dir: Path,
) -> Path | None:
    """Resolve one recorded output path, including WSL `/mnt/<drive>/...` forms."""
    if raw_path in (None, ""):
        return None
    text = str(raw_path).strip()
    if not text:
        return None

    normalized = text
    if len(text) > 7 and text.startswith("/mnt/") and text[5].isalpha() and text[6] == "/":
        drive = text[5].upper()
        tail = text[7:].replace("/", "\\")
        normalized = f"{drive}:\\{tail}"

    path = Path(normalized).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    else:
        path = path.resolve()
    return path


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
        bundle_dir = _resolve_recorded_output_path(bundle_dir_raw, base_dir=run_folder)
        if bundle_dir is None:
            return payload
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


def resolve_bundle_cells(
    run_folder: Path,
    *,
    config_path: Path | None = None,
    expected_size: int | None = None,
    solver_name: str | None = None,
) -> CellCentroidTable | None:
    """Load cell centroids from an exchange bundle or structured-grid support."""
    metrics = read_json_file(run_folder / "_metrics.json")
    bundle_dir_raw = metrics.get("mesh_output_exchange_bundle_dir")
    if not bundle_dir_raw:
        boussinesq_summary = read_json_file(run_folder / "_boussinesq_summary.json")
        bundle_dir_raw = boussinesq_summary.get("bundle_dir")
    if bundle_dir_raw:
        bundle_dir = _resolve_recorded_output_path(bundle_dir_raw, base_dir=run_folder)
        cells_path = None if bundle_dir is None else (bundle_dir / "cells.csv")
        if cells_path is not None and cells_path.exists():
            cell_ids: list[int] = []
            xs: list[float] = []
            ys: list[float] = []
            areas: list[float] = []
            storage_coefficients: list[float] = []
            with cells_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    try:
                        cell_ids.append(int(row["cell_id"]))
                        xs.append(float(row["centroid_x"]))
                        ys.append(float(row["centroid_y"]))
                        area_value = row.get("area_m2")
                        areas.append(
                            float(area_value) if area_value not in (None, "") else math.nan
                        )
                        storage_value = row.get("storage_coefficient")
                        storage_coefficients.append(
                            float(storage_value)
                            if storage_value not in (None, "")
                            else math.nan
                        )
                    except Exception:
                        continue

            if cell_ids:
                area_array = np.asarray(areas, dtype=float)
                if area_array.size != len(cell_ids) or not np.any(np.isfinite(area_array)):
                    area_array = None
                storage_array = np.asarray(storage_coefficients, dtype=float)
                if (
                    storage_array.size != len(cell_ids)
                    or not np.any(np.isfinite(storage_array))
                ):
                    storage_array = None
                return CellCentroidTable(
                    cell_ids=np.asarray(cell_ids, dtype=int),
                    x=np.asarray(xs, dtype=float),
                    y=np.asarray(ys, dtype=float),
                    area_m2=area_array,
                    storage_coefficient=storage_array,
                )

    if config_path is None:
        return _structured_cells_from_run_folder(
            run_folder=run_folder,
            expected_size=expected_size,
        )
    structured_cells = _structured_cells_from_config(
        config_path=config_path,
        solver_name=solver_name,
        expected_size=expected_size,
    )
    if structured_cells is not None:
        return structured_cells
    return _structured_cells_from_run_folder(
        run_folder=run_folder,
        expected_size=expected_size,
    )


def _variable_candidates(variable: str) -> tuple[str, ...]:
    """Return postprocess file aliases for one observable variable."""
    key = variable.strip()
    lowered = key.lower()
    candidates = [key]
    alias_map = {
        "outlet_flux": [
            "outlet_discharge_east_side_m3_s",
            "drainage_flux_history_m3_s",
            "drainage_flux_m3_s",
            "accumulation_flux",
        ],
        "outlet_flux_m3_s": [
            "outlet_discharge_east_side_m3_s",
            "drainage_flux_history_m3_s",
            "drainage_flux_m3_s",
            "accumulation_flux",
        ],
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
        "outflow_drain": [
            "drainage_flux_history_m3_s",
            "drainage_flux_m3_s",
        ],
        "surface_excess_flux": [
            "surface_excess_total_m3_s",
            "surface_threshold_total_m3_s",
            "saturation_excess_total_m3_s",
            "saturation_excess_history_m_s",
        ],
        "surface_excess_rate": [
            "saturation_excess_history_m_s",
        ],
        "surface_excess_map": [
            "saturation_excess_history_m_s",
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
    if key in {"outlet_flux", "outlet_flux_m3_s"}:
        return "m3/s"
    if key in {
        "surface_excess_flux",
        "surface_excess_total_m3_s",
        "surface_threshold_total_m3_s",
        "saturation_excess_total_m3_s",
    }:
        return "m3/s"
    if key in {"watertable_elevation", "head"}:
        return "m"
    if key == "watertable_depth":
        return "m"
    if key in {"surface_excess_rate", "surface_excess_map"}:
        return "m/day"
    if key in {"accumulation_flux", "outflow_drain", "seepage_areas"}:
        return "m/day"
    if key.endswith("_m3_s") or "_m3_s" in key:
        return "m3/s"
    if key.endswith("_m_s") or "_m_s" in key:
        return "m/s"
    return ""


def _is_canonical_outlet_flux(variable_name: str) -> bool:
    key = variable_name.strip().lower()
    return key in {"outlet_flux", "outlet_flux_m3_s"}


def _is_canonical_surface_excess_flux(variable_name: str) -> bool:
    key = variable_name.strip().lower()
    return key in {"surface_excess_flux", "surface_excess_total_m3_s"}


def _convert_accumulation_rate_to_m3_s(
    *,
    value_m_per_day: float,
    cell_area_m2: float,
) -> float:
    """Convert one accumulation depth-rate to a volumetric cell outflow."""
    return (float(value_m_per_day) * float(cell_area_m2)) / 86400.0


def _convert_flux_m3_s_to_depth_m_per_day(
    *,
    value_m3_s: float,
    cell_area_m2: float,
) -> float:
    """Convert one volumetric cell flux to a depth-rate over that cell."""
    return (float(value_m3_s) / float(cell_area_m2)) * 86400.0


def _convert_rate_m_s_to_m_per_day(*, value_m_s: float) -> float:
    """Convert one depth-rate from `m/s` to `m/day`."""
    return float(value_m_s) * 86400.0


def _area_for_series_value(
    *,
    series: VariableSeries,
    cells: CellCentroidTable | None,
    value_index: int,
) -> float | None:
    """Return the cell area associated with one extracted scalar value."""
    if cells is None:
        return None
    if series.cell_ids is not None and value_index < int(series.cell_ids.size):
        return cells.area_for_cell_id(int(series.cell_ids[int(value_index)]))
    if cells.area_m2 is None or value_index >= int(cells.cell_ids.size):
        return None
    area = float(cells.area_m2[int(value_index)])
    if not np.isfinite(area) or area <= 0.0:
        return None
    return area


_NODATA_SENTINELS = (-9999.0, -99999.0, -999999.0)


def is_nodata_value(value: Any) -> bool:
    """Return True for common HydroModPy numeric sentinel values."""
    try:
        parsed = float(value)
    except Exception:
        return False
    if not math.isfinite(parsed):
        return True
    return any(
        math.isclose(parsed, sentinel, rel_tol=0.0, abs_tol=1.0e-6)
        for sentinel in _NODATA_SENTINELS
    )


def normalize_observable_value(
    *,
    observable: MethodComparisonObservableSchema,
    series: VariableSeries,
    value: float,
    value_index: int,
    details: Mapping[str, Any],
    cells: CellCentroidTable | None,
) -> dict[str, Any]:
    """Normalize one selected observable value and its output metadata."""
    native_unit = _native_unit_for_variable(series.variable_name)
    output_value = float(value)
    derived_from_variable = series.variable_name
    conversion_applied = ""
    cell_area_m2: float | str = ""

    if _is_canonical_outlet_flux(observable.variable):
        native_unit = "m3/s"
        if series.variable_name == "accumulation_flux":
            selected_cell_raw = details.get("selected_cell_index")
            if selected_cell_raw in ("", None):
                raise ValueError(
                    f"Observable '{observable.name}' cannot derive "
                    "canonical outlet_flux from accumulation_flux "
                    "without an explicit outlet cell selection."
                )
            if cells is None:
                raise ValueError(
                    f"Observable '{observable.name}' cannot derive "
                    "canonical outlet_flux without mesh bundle areas."
                )
            area_m2 = cells.area_for_cell_id(int(selected_cell_raw))
            if area_m2 is None:
                raise ValueError(
                    f"Observable '{observable.name}' cannot derive "
                    f"canonical outlet_flux because area_m2 is missing "
                    f"for cell {selected_cell_raw}."
                )
            output_value = _convert_accumulation_rate_to_m3_s(
                value_m_per_day=output_value,
                cell_area_m2=area_m2,
            )
            conversion_applied = "accumulation_flux_m_per_day_to_m3_s"
            cell_area_m2 = area_m2
        elif native_unit == "":
            native_unit = "m3/s"
    elif observable.variable.strip().lower() == "outflow_drain" and series.variable_name in {
        "drainage_flux_history_m3_s",
        "drainage_flux_m3_s",
    }:
        area_m2 = _area_for_series_value(
            series=series,
            cells=cells,
            value_index=value_index,
        )
        if area_m2 is None:
            raise ValueError(
                f"Observable '{observable.name}' cannot derive outflow_drain "
                "from drainage_flux without cell areas."
            )
        output_value = _convert_flux_m3_s_to_depth_m_per_day(
            value_m3_s=output_value,
            cell_area_m2=area_m2,
        )
        native_unit = "m3/s"
        conversion_applied = "drainage_flux_m3_s_to_m_per_day"
        cell_area_m2 = area_m2
    elif observable.variable.strip().lower() in {
        "surface_excess_rate",
        "surface_excess_map",
    } and series.variable_name == "saturation_excess_history_m_s":
        output_value = _convert_rate_m_s_to_m_per_day(value_m_s=output_value)
        native_unit = "m/s"
        conversion_applied = "surface_excess_m_s_to_m_per_day"

    return {
        "value": output_value,
        "unit": observable.unit or native_unit,
        "native_unit": native_unit,
        "derived_from_variable": derived_from_variable,
        "conversion_applied": conversion_applied,
        "cell_area_m2": cell_area_m2,
    }


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


def _elapsed_seconds_from_period_lengths(
    *,
    n_snapshots: int,
    period_lengths: np.ndarray,
) -> list[float | None]:
    if n_snapshots <= 0:
        return []
    if period_lengths.size == n_snapshots - 1:
        elapsed: list[float | None] = [0.0]
        elapsed.extend(float(value) for value in np.cumsum(period_lengths))
        return elapsed
    if period_lengths.size == n_snapshots:
        return [float(value) for value in np.cumsum(period_lengths)]
    return [None for _ in range(n_snapshots)]


def _load_boussinesq_surface_excess_total_series(
    run_folder: Path,
    path: Path,
    *,
    variable_name: str,
) -> VariableSeries:
    payload = np.load(path, allow_pickle=True)
    if "saturation_excess_history_m_s" not in payload:
        raise KeyError(variable_name)
    values = np.asarray(payload["saturation_excess_history_m_s"], dtype=float)
    if values.ndim == 1:
        values = values.reshape(1, -1)
    if values.ndim != 2:
        raise ValueError(
            "saturation_excess_history_m_s must be 2-D to derive surface-excess totals"
        )

    cells = resolve_bundle_cells(
        run_folder,
        expected_size=int(values.shape[1]),
        solver_name="boussinesq",
    )
    if cells is None or cells.area_m2 is None:
        raise ValueError(
            "Cannot derive surface_excess_total_m3_s without bundle cell areas"
        )
    area_m2 = np.asarray(cells.area_m2, dtype=float).reshape(-1)
    if area_m2.size != values.shape[1]:
        raise ValueError(
            "Bundle cell areas do not match saturation_excess_history_m_s width"
        )

    positive = np.maximum(values, 0.0)
    totals_m3_s = np.sum(positive * area_m2[None, :], axis=1, dtype=float)
    period_lengths = (
        np.asarray(payload["period_lengths_seconds"], dtype=float).ravel()
        if "period_lengths_seconds" in payload
        else np.asarray([], dtype=float)
    )
    elapsed_by_index = _elapsed_seconds_from_period_lengths(
        n_snapshots=int(totals_m3_s.size),
        period_lengths=period_lengths,
    )
    slices = tuple(
        TimeSlice(
            time_key=index,
            time_index=index,
            values=np.asarray([float(total)], dtype=float),
            elapsed_seconds=elapsed_by_index[index],
            is_initial_state=period_lengths.size == totals_m3_s.size - 1 and index == 0,
        )
        for index, total in enumerate(totals_m3_s.tolist())
    )
    return VariableSeries(
        variable_name=variable_name,
        source_path=path,
        slices=slices,
        cell_ids=None,
    )


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
                if variable_name in {
                    "surface_excess_total_m3_s",
                    "surface_threshold_total_m3_s",
                    "saturation_excess_total_m3_s",
                }:
                    return _load_boussinesq_surface_excess_total_series(
                        run_folder,
                        boussinesq_path,
                        variable_name=variable_name,
                    )
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


def mask_depth_series_from_head_nodata(
    *,
    run_folder: Path,
    series: VariableSeries,
) -> VariableSeries:
    """Mask `watertable_depth` where the companion head series carries nodata."""
    if series.variable_name.strip().lower() != "watertable_depth":
        return series

    try:
        head_series = load_variable_series(
            run_folder=run_folder,
            variable="watertable_elevation",
        )
    except Exception:
        return series

    if len(head_series.slices) != len(series.slices):
        return series

    masked_slices: list[TimeSlice] = []
    for depth_slice, head_slice in zip(series.slices, head_series.slices, strict=False):
        depth_values = np.asarray(depth_slice.values, dtype=float).ravel().copy()
        head_values = np.asarray(head_slice.values, dtype=float).ravel()
        if depth_values.size != head_values.size:
            return series
        nodata_mask = np.asarray(
            [is_nodata_value(value) for value in head_values],
            dtype=bool,
        )
        if nodata_mask.size == depth_values.size and np.any(nodata_mask):
            depth_values[nodata_mask] = np.nan
        masked_slices.append(
            TimeSlice(
                time_key=depth_slice.time_key,
                time_index=depth_slice.time_index,
                values=depth_values,
                elapsed_seconds=depth_slice.elapsed_seconds,
                is_initial_state=depth_slice.is_initial_state,
            )
        )

    return VariableSeries(
        variable_name=series.variable_name,
        source_path=series.source_path,
        slices=tuple(masked_slices),
        cell_ids=series.cell_ids,
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


def select_time_slices(
    series: VariableSeries,
    observable: MethodComparisonObservableSchema,
) -> tuple[TimeSlice, ...]:
    """Public wrapper exposing observable time selection for reuse."""
    return _select_time_slices(series, observable)


def _reduce(values: Any, *, reducer: str | None, label: str) -> tuple[float, ...]:
    """Reduce one numeric sequence."""
    arr = np.asarray(values, dtype=float).ravel()
    if arr.size > 0:
        for sentinel in _NODATA_SENTINELS:
            arr[np.isclose(arr, sentinel, rtol=0.0, atol=1.0e-6)] = np.nan
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
        if values.size == 1 and series.cell_ids is None:
            if selected_cell_ids:
                details["selected_cell_index"] = selected_cell_ids[0]
            details["selection"] = "native_outlet_series"
            return (float(values[0]),), details
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


def _fallback_time_key(
    *,
    observable: MethodComparisonObservableSchema,
    time_slice: TimeSlice,
    selection_time_order: int,
    non_initial_time_order: int | None,
) -> str:
    """Return a semantic fallback key used when raw time keys differ across variants."""
    reducer_key = str(observable.time_reducer or "").strip().lower()
    if reducer_key:
        return f"time_reducer:{reducer_key}"

    selector_key = str(observable.time or "all").strip().lower()
    if selector_key in {"last", "first"}:
        return f"time_selector:{selector_key}"

    if observable.time_window is not None:
        if time_slice.is_initial_state:
            return "initial_state"
        if non_initial_time_order is not None:
            return f"time_window_non_initial_order:{non_initial_time_order}"
        return f"time_window_selection_order:{selection_time_order}"

    if selector_key in {"", "all"}:
        if time_slice.is_initial_state:
            return "initial_state"
        if non_initial_time_order is not None:
            return f"non_initial_order:{non_initial_time_order}"
        return f"selection_order:{selection_time_order}"

    return f"requested_time:{selector_key}"


def extract_observable_rows(
    *,
    comparison_id: str,
    variant: MethodComparisonVariantSchema,
    run_folder: Path,
    observables: tuple[MethodComparisonObservableSchema, ...],
    config_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Extract all observable rows for one completed/reused variant."""
    rows: list[dict[str, Any]] = []
    cells: CellCentroidTable | None = None
    for observable in observables:
        if observable.variants is not None and variant.id not in set(observable.variants):
            continue
        series = load_variable_series(run_folder=run_folder, variable=observable.variable)
        series = mask_depth_series_from_head_nodata(run_folder=run_folder, series=series)
        if cells is None:
            first_slice_size = (
                int(series.slices[0].values.size) if series.slices else None
            )
            cells = resolve_bundle_cells(
                run_folder,
                config_path=config_path,
                expected_size=(
                    None
                    if first_slice_size is None or first_slice_size <= 1
                    else first_slice_size
                ),
                solver_name=variant.solver,
            )
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
            reducer_key = str(observable.time_reducer).strip().lower()
            reduced_values = _reduce(
                flat,
                reducer=observable.time_reducer,
                label=f"{observable.name} time series",
            )
            if reducer_key == "last":
                reduced_details = dict(per_time_values[-1][2])
            elif reducer_key == "first":
                reduced_details = dict(per_time_values[0][2])
            else:
                reduced_details = dict(per_time_values[-1][2])
            reduced_details["time_reducer"] = observable.time_reducer
            reduced_slice = TimeSlice(
                time_key="reduced",
                time_index=-1,
                values=np.asarray(reduced_values, dtype=float),
            )
            per_time_values = [
                (reduced_slice, reduced_values, reduced_details)
            ]

        non_initial_counter = 0
        for selection_time_order, (time_slice, values, details) in enumerate(per_time_values):
            non_initial_time_order: int | None
            if time_slice.is_initial_state:
                non_initial_time_order = None
            else:
                non_initial_time_order = non_initial_counter
                non_initial_counter += 1
            fallback_time_key = _fallback_time_key(
                observable=observable,
                time_slice=time_slice,
                selection_time_order=selection_time_order,
                non_initial_time_order=non_initial_time_order,
            )
            for value_index, value in enumerate(values):
                normalized = normalize_observable_value(
                    observable=observable,
                    series=series,
                    value=float(value),
                    value_index=value_index,
                    details=details,
                    cells=cells,
                )
                is_nodata = is_nodata_value(normalized["value"])
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
                        "requested_time": (
                            "all"
                            if observable.time is None
                            else str(observable.time)
                        ),
                        "requested_time_reducer": (
                            ""
                            if observable.time_reducer is None
                            else str(observable.time_reducer)
                        ),
                        "selection_time_order": selection_time_order,
                        "non_initial_time_order": (
                            ""
                            if non_initial_time_order is None
                            else non_initial_time_order
                        ),
                        "is_initial_state": bool(time_slice.is_initial_state),
                        "comparison_time_key": _time_match_key(time_slice),
                        "match_fallback_key": fallback_time_key,
                        "value_index": value_index,
                        "value": normalized["value"],
                        "is_nodata": is_nodata,
                        "unit": normalized["unit"],
                        "configured_unit": observable.unit or "",
                        "native_unit": normalized["native_unit"],
                        "derived_from_variable": normalized["derived_from_variable"],
                        "conversion_applied": normalized["conversion_applied"],
                        "cell_area_m2": normalized["cell_area_m2"],
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
        "requested_time",
        "requested_time_reducer",
        "selection_time_order",
        "non_initial_time_order",
        "is_initial_state",
        "comparison_time_key",
        "match_fallback_key",
        "value_index",
        "value",
        "is_nodata",
        "unit",
        "configured_unit",
        "native_unit",
        "derived_from_variable",
        "conversion_applied",
        "cell_area_m2",
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
    "mask_depth_series_from_head_nodata",
    "compact_run_metrics",
    "read_json_file",
    "read_variant_run_metadata",
    "is_nodata_value",
    "normalize_observable_value",
    "resolve_bundle_cells",
    "resolve_structured_shape_from_config",
    "resolve_structured_shape_from_run_folder",
    "select_time_slices",
    "write_observables_csv",
    "write_toml_payload",
)
