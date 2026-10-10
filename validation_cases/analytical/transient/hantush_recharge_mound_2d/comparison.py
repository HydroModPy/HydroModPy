"""Comparison workflow for the 2D recharge mound validation case (Hantush 1967)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from validation_cases.analytical.transient.common import load_transient_profile_outputs
from validation_cases.shared import (
    ValidationRunResult,
    load_case_metadata,
    load_case_tolerances,
    max_abs_error,
    rmse,
    run_launcher_validation_case,
)
from validation_cases.shared.boussinesq_analytical_runtime import DEFAULT_ENGINE_SOLVER
from validation_cases.shared.loaders import (
    bundle_cell_centers,
    load_cell_polygons,
    load_last_cell_values,
    map_polygons_payload,
    resolve_case_mesh_bundle_dir,
)

from .reference import hantush_mound_rise
from .runtime_boussinesq import (
    FINAL_CELL_HEADS,
    nearest_centroid_indices,
    run_boussinesq_hantush_recharge_mound_case,
)

CASE_DIR = Path(__file__).resolve().parent
BOUSSINESQ_SOLVERS = frozenset({"boussinesq", DEFAULT_ENGINE_SOLVER})
SECONDS_PER_DAY = 86400.0
MM_PER_M = 1000.0


@dataclass(frozen=True, slots=True)
class RechargeMoundComparison:
    """Head under the recharge rectangle against Hantush (1967).

    Every head is compared with the reference read at the centre of the solver
    cell that holds it: the cell centre on the structured grid, the centroid of
    the triangle, the node of the Voronoi cell.

    - ``x``: abscissa of the transect through the centre, along the long side
      of the rectangle, in metres from the centre, every 20 m.
    - ``analytical_profiles`` / ``numerical_profiles``: head on the transect,
      one row per output time.
    - ``analytical_centre_rise`` / ``numerical_centre_rise``: head rise at the
      centre over time.
    - ``map_cell_polygons``, ``map_simulated``, ``map_reference``: plan view
      at the final time, one entry per solver cell, in metres from the centre.
    """

    result: ValidationRunResult
    metadata: dict
    tolerances: dict
    observable_name: str
    elapsed_days: np.ndarray
    x: np.ndarray
    transect_cell_xy: np.ndarray
    numerical_profiles: np.ndarray
    analytical_profiles: np.ndarray
    residual_profiles: np.ndarray
    centre_cell_xy: np.ndarray
    numerical_centre_rise: np.ndarray
    analytical_centre_rise: np.ndarray
    space_time_rmse: float
    space_time_max_error: float
    final_profile_rmse: float
    final_profile_max_error: float
    centre_max_error: float
    map_cell_polygons: list[list[tuple[float, float]]]
    map_simulated: np.ndarray
    map_reference: np.ndarray
    map_overlay: dict
    map_max_error: float


def _reference_kwargs(reference_cfg: dict) -> dict:
    return dict(
        recharge_m_per_s=float(reference_cfg["recharge_mm_day"]) / MM_PER_M / SECONDS_PER_DAY,
        hydraulic_conductivity_m_per_s=float(reference_cfg["hydraulic_conductivity_m_per_s"]),
        specific_yield=float(reference_cfg["specific_yield"]),
        initial_thickness_m=float(reference_cfg["initial_head_m"])
        - float(reference_cfg["aquifer_base_m"]),
        half_length_x_m=float(reference_cfg["half_length_x_m"]),
        half_width_y_m=float(reference_cfg["half_width_y_m"]),
    )


def _grid_centres(metadata: dict) -> tuple[np.ndarray, np.ndarray]:
    """Return the x centres and the y centres, from the south, of the validation grid."""
    reference_cfg = dict(metadata["reference"])
    ny, nx = (int(value) for value in metadata["output"]["expected_spatial_shape"])
    dx = (float(reference_cfg["xmax"]) - float(reference_cfg["xmin"])) / nx
    dy = (float(reference_cfg["ymax"]) - float(reference_cfg["ymin"])) / ny
    x = float(reference_cfg["xmin"]) + (np.arange(nx) + 0.5) * dx
    y = float(reference_cfg["ymin"]) + (np.arange(ny) + 0.5) * dy
    return x, y


def _polygon_centres(polygons: list[np.ndarray]) -> np.ndarray:
    return np.asarray([np.asarray(polygon).mean(axis=0) for polygon in polygons], dtype=float)


def _boussinesq_triangles(result) -> tuple[np.ndarray, list[np.ndarray]]:
    """Return the centroids and the outlines of the triangles of a Boussinesq run."""
    bundle_dir = Path(result.out_path) / "mesh_bundle"
    read = dict(delimiter=",", names=True, dtype=None, encoding="utf-8")
    cells = np.genfromtxt(bundle_dir / "cells.csv", **read)
    nodes = np.genfromtxt(bundle_dir / "nodes.csv", **read)
    points = np.column_stack([nodes["x"], nodes["y"]]).astype(float)
    corners = np.column_stack([cells["n0"], cells["n1"], cells["n2"]]).astype(int)
    centroids = np.column_stack([cells["centroid_x"], cells["centroid_y"]]).astype(float)
    return centroids, [points[row] for row in corners]


def _held_cell_centres(*, result, solver_name: str, metadata: dict, observable_name: str):
    """Return the centre of the solver cell each validation grid cell holds.

    The array is ``(ny, nx, 2)``, rows in the order of the loaded heads: from
    the north on the structured MODFLOW grid, which the result store lists that
    way, from the south after the nearest-centre projection of a mesh run.
    """
    x, y = _grid_centres(metadata)
    if solver_name in BOUSSINESQ_SOLVERS:
        centres, _ = _boussinesq_triangles(result)
    else:
        bundle_dir = resolve_case_mesh_bundle_dir(CASE_DIR, metadata, solver_name)
        if bundle_dir is None:
            centres = _polygon_centres(load_cell_polygons(store=result.store, sim_id=result.sim_id))
            return centres.reshape(y.size, x.size, 2)
        n_cells = load_last_cell_values(
            observable_name=observable_name, store=result.store, sim_id=result.sim_id
        ).size
        centres, _ = bundle_cell_centers(bundle_dir, n_cells)
    xx, yy = np.meshgrid(x, y)
    nearest = nearest_centroid_indices(centres, np.column_stack([xx.ravel(), yy.ravel()]))
    return np.asarray(centres, dtype=float)[nearest].reshape(y.size, x.size, 2)


def _final_map(
    *, result, solver_name: str, metadata: dict, observable_name: str, heads: np.ndarray
):
    """Return the outline, the final head and the cell centre of every solver cell."""
    if solver_name in BOUSSINESQ_SOLVERS:
        centres, polygons = _boussinesq_triangles(result)
        simulated = np.load(Path(result.out_path) / FINAL_CELL_HEADS)
        return polygons, simulated, centres
    polygons = load_cell_polygons(store=result.store, sim_id=result.sim_id)
    bundle_dir = resolve_case_mesh_bundle_dir(CASE_DIR, metadata, solver_name)
    if bundle_dir is None:
        return polygons, np.asarray(heads, dtype=float).reshape(-1), _polygon_centres(polygons)
    simulated = load_last_cell_values(
        observable_name=observable_name, store=result.store, sim_id=result.sim_id
    )
    centres, _ = bundle_cell_centers(bundle_dir, simulated.size)
    return polygons, simulated, np.asarray(centres, dtype=float)


def build_hantush_recharge_mound_comparison(
    *,
    result,
    solver: str | None = None,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> RechargeMoundComparison:
    """Load one completed run and compare its mound with the Hantush solution."""
    metadata = load_case_metadata(CASE_DIR) if metadata is None else metadata
    tolerances = load_case_tolerances(CASE_DIR, solver=solver) if tolerances is None else tolerances
    loaded = load_transient_profile_outputs(
        case_dir=CASE_DIR, result=result, metadata=metadata, tolerances=tolerances, solver=solver
    )
    solver_name = str(getattr(result, "solver_name", "")).strip().lower() or str(solver or "")
    reference_cfg = dict(metadata["reference"])
    centre = np.array([float(reference_cfg["center_x_m"]), float(reference_cfg["center_y_m"])])
    initial_head = float(reference_cfg["initial_head_m"])
    kwargs = _reference_kwargs(reference_cfg)

    heads = np.asarray(loaded.heads, dtype=float)
    times = np.asarray(loaded.elapsed_seconds, dtype=float)
    held = _held_cell_centres(
        result=result,
        solver_name=solver_name,
        metadata=metadata,
        observable_name=loaded.observable_name,
    )
    x_grid, _ = _grid_centres(metadata)
    row, column = heads.shape[1] // 2, heads.shape[2] // 2
    on_transect = np.abs(x_grid - centre[0]) <= float(reference_cfg["transect_half_length_m"])
    transect_xy = held[row, on_transect] - centre
    numerical = heads[:, row, on_transect]
    analytical = initial_head + hantush_mound_rise(
        x=transect_xy[:, 0], y=transect_xy[:, 1], times_seconds=times, **kwargs
    )
    centre_xy = held[row, column] - centre
    numerical_centre = heads[:, row, column] - initial_head
    analytical_centre = hantush_mound_rise(
        x=[centre_xy[0]], y=[centre_xy[1]], times_seconds=times, **kwargs
    )[:, 0]

    polygons, map_simulated, map_centres = _final_map(
        result=result,
        solver_name=solver_name,
        metadata=metadata,
        observable_name=loaded.observable_name,
        heads=heads[-1],
    )
    map_xy = map_centres - centre
    map_reference = (
        initial_head
        + hantush_mound_rise(x=map_xy[:, 0], y=map_xy[:, 1], times_seconds=times[-1:], **kwargs)[0]
    )

    return RechargeMoundComparison(
        result=result,
        metadata=metadata,
        tolerances=tolerances,
        observable_name=loaded.observable_name,
        elapsed_days=times / SECONDS_PER_DAY,
        x=x_grid[on_transect] - centre[0],
        transect_cell_xy=transect_xy,
        numerical_profiles=numerical,
        analytical_profiles=analytical,
        residual_profiles=numerical - analytical,
        centre_cell_xy=centre_xy,
        numerical_centre_rise=numerical_centre,
        analytical_centre_rise=analytical_centre,
        space_time_rmse=rmse(numerical, analytical),
        space_time_max_error=max_abs_error(numerical, analytical),
        final_profile_rmse=rmse(numerical[-1], analytical[-1]),
        final_profile_max_error=max_abs_error(numerical[-1], analytical[-1]),
        centre_max_error=max_abs_error(numerical_centre, analytical_centre),
        map_cell_polygons=map_polygons_payload(
            polygons, origin_x=float(centre[0]), origin_y=float(centre[1])
        ),
        map_simulated=np.asarray(map_simulated, dtype=float),
        map_reference=map_reference,
        map_overlay={},
        map_max_error=max_abs_error(map_simulated, map_reference),
    )


def run_hantush_recharge_mound_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
) -> RechargeMoundComparison:
    """Run the case with one solver and return the mound comparison payload."""
    normalized_solver = None if solver is None else str(solver).strip().lower()
    if normalized_solver in BOUSSINESQ_SOLVERS:
        result = run_boussinesq_hantush_recharge_mound_case(
            caller_file=caller_file, timeout=timeout, public_solver_label=normalized_solver
        )
    else:
        result = run_launcher_validation_case(
            case_dir=CASE_DIR, test_file=caller_file, timeout=timeout, solver=solver
        )
    return build_hantush_recharge_mound_comparison(result=result, solver=solver)
