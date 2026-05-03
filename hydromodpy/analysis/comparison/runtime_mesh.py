"""Mesh, structured-grid, and cell-centroid lookup helpers."""

from __future__ import annotations

import csv
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.analysis.comparison._solver_protocol import (
    get_solver_registry_provider,
)
from hydromodpy.analysis.comparison.runtime_metadata import (
    _resolve_project_root_from_config,
    _resolve_recorded_output_path,
    read_json_file,
)
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

try:
    import rasterio
except Exception:  # pragma: no cover - optional dependency in lightweight envs
    rasterio = None


@dataclass(frozen=True, slots=True)
class CellCentroidTable:
    """Minimal cell-centroid lookup loaded from a mesh exchange bundle."""

    cell_ids: np.ndarray
    x: np.ndarray
    y: np.ndarray
    area_m2: np.ndarray | None = None
    storage_coefficient: np.ndarray | None = None
    z_top: np.ndarray | None = None
    z_bottom: np.ndarray | None = None

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
        if self.storage_coefficient is None or self.storage_coefficient.size != self.cell_ids.size:
            return None
        matches = np.flatnonzero(self.cell_ids == int(cell_id))
        if matches.size == 0:
            return None
        storage = float(self.storage_coefficient[int(matches[0])])
        if not np.isfinite(storage):
            return None
        return storage

    def vertical_bounds_for_cell_id(self, cell_id: int) -> tuple[float, float] | None:
        """Return ``(top, bottom)`` elevations for one cell id when available."""
        if (
            self.z_top is None
            or self.z_bottom is None
            or self.z_top.size != self.cell_ids.size
            or self.z_bottom.size != self.cell_ids.size
        ):
            return None
        matches = np.flatnonzero(self.cell_ids == int(cell_id))
        if matches.size == 0:
            return None
        index = int(matches[0])
        top = float(self.z_top[index])
        bottom = float(self.z_bottom[index])
        if not (np.isfinite(top) and np.isfinite(bottom)):
            return None
        return top, bottom


def _candidate_solver_sections(solver_name: str | None = None) -> tuple[str, ...]:
    """Return candidate TOML section names for a structured flow solver.

    Sections are pulled from the solver registry filtered by the
    ``distributed`` category - the only backends that expose a structured
    ``(nrow, ncol)`` shape via their TOML config. ``solver_name``, when
    given, is tried first. The registry lookup goes through
    :class:`SolverRegistryProvider` so analysis stays decoupled from the
    solver layer.
    """
    sections: list[str] = []
    if solver_name:
        sections.append(str(solver_name).strip().lower())

    provider = get_solver_registry_provider()
    if provider is not None:
        sections.extend(provider.distributed_flow_solver_sections())

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


def _bundle_cells_from_dir(bundle_dir: Path) -> CellCentroidTable | None:
    cells_path = bundle_dir / "cells.csv"
    if not cells_path.exists():
        return None

    cell_ids: list[int] = []
    xs: list[float] = []
    ys: list[float] = []
    areas: list[float] = []
    storage_coefficients: list[float] = []
    z_tops: list[float] = []
    z_bottoms: list[float] = []
    with cells_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                cell_ids.append(int(row["cell_id"]))
                xs.append(float(row["centroid_x"]))
                ys.append(float(row["centroid_y"]))
                area_value = row.get("area_m2")
                areas.append(float(area_value) if area_value not in (None, "") else math.nan)
                storage_value = row.get("storage_coefficient")
                storage_coefficients.append(
                    float(storage_value) if storage_value not in (None, "") else math.nan
                )
                top_value = row.get("z_top_centroid") or row.get("z_top")
                bottom_value = row.get("z_bottom_centroid") or row.get("z_bottom")
                z_tops.append(float(top_value) if top_value not in (None, "") else math.nan)
                z_bottoms.append(
                    float(bottom_value) if bottom_value not in (None, "") else math.nan
                )
            except Exception:
                continue

    if not cell_ids:
        return None
    area_array: Any = np.asarray(areas, dtype=float)
    if area_array.size != len(cell_ids) or not np.any(np.isfinite(area_array)):
        area_array = None
    storage_array: Any = np.asarray(storage_coefficients, dtype=float)
    if storage_array.size != len(cell_ids) or not np.any(np.isfinite(storage_array)):
        storage_array = None
    z_top_array: Any = np.asarray(z_tops, dtype=float)
    if z_top_array.size != len(cell_ids) or not np.any(np.isfinite(z_top_array)):
        z_top_array = None
    z_bottom_array: Any = np.asarray(z_bottoms, dtype=float)
    if z_bottom_array.size != len(cell_ids) or not np.any(np.isfinite(z_bottom_array)):
        z_bottom_array = None
    return CellCentroidTable(
        cell_ids=np.asarray(cell_ids, dtype=int),
        x=np.asarray(xs, dtype=float),
        y=np.asarray(ys, dtype=float),
        area_m2=area_array,
        storage_coefficient=storage_array,
        z_top=z_top_array,
        z_bottom=z_bottom_array,
    )


def _bundle_cells_from_config(config_path: Path) -> CellCentroidTable | None:
    try:
        payload = load_toml_with_base_config(config_path)
    except Exception:
        return None
    mesh_input = payload.get("mesh_input")
    if not isinstance(mesh_input, Mapping):
        return None
    bundle_dir_raw = mesh_input.get("bundle_dir")
    if bundle_dir_raw in (None, ""):
        return None
    bundle_dir = _resolve_recorded_output_path(bundle_dir_raw, base_dir=config_path.parent)
    if bundle_dir is None:
        return None
    return _bundle_cells_from_dir(bundle_dir)


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
        if bundle_dir is not None and (cells := _bundle_cells_from_dir(bundle_dir)) is not None:
            return cells

    if config_path is None:
        return _structured_cells_from_run_folder(
            run_folder=run_folder,
            expected_size=expected_size,
        )
    config_bundle_cells = _bundle_cells_from_config(config_path)
    if config_bundle_cells is not None:
        if expected_size is None or config_bundle_cells.cell_ids.size == int(expected_size):
            return config_bundle_cells
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


__all__ = (
    "CellCentroidTable",
    "resolve_bundle_cells",
    "resolve_structured_shape_from_config",
    "resolve_structured_shape_from_run_folder",
)
