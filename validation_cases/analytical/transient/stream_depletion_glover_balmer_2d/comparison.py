"""Comparison workflow for the stream depletion 2D validation case.

Every quantity is read on the solver cells, and the closed form is evaluated
where the model computes:

- the stream line sits at the centres of the cells that hold the stream head,
  the cells that own an edge on the west face: half a cell inside the face on
  the 10 m grid, about 3 m inside it on the triangles, on the face itself for
  the Voronoi dual, whose boundary cells are centred on the face nodes. On the
  triangles the centres differ along the stream, so the line is their mean
  weighted by the share of the depletion each one carries in the closed form;
- the well sits at the centre of the cell that takes the pumping;
- a monitor point reads the cell with the nearest centre, and the closed form is
  evaluated at that centre.

The stream depletion is the net flux the stream cells give the aquifer, read
from the per-cell constant-head budget of the run, over the pumping rate. A run
stores the mean flux of each stress period, the mean of its time steps, so the
reference is the mean of the closed form over the same period, not its value
at the period end: over the second half day they differ by 0.05 of the pumping
rate. The drawdown is a state, compared with the closed form at the period end.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

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
    map_polygons_payload,
    resolve_case_mesh_bundle_dir,
)

from .reference import (
    SECONDS_PER_DAY,
    image_well_drawdown,
    stream_depletion_period_mean_fraction,
    transmissivity_m2_day,
)
from .runtime_boussinesq import BUNDLE_SOLVER, run_boussinesq_stream_depletion_case

CASE_DIR = Path(__file__).resolve().parent
BOUSSINESQ_SOLVERS = frozenset({"boussinesq", DEFAULT_ENGINE_SOLVER})
# A vertex closer than this to the west face lies on it.
_FACE_ATOL_M = 1e-6


@dataclass(frozen=True, slots=True)
class StreamDepletionComparison:
    """Stream depletion and drawdown of one run against the image-well solution.

    Times are the ends of the stress periods. The depletion fractions are means
    over the period that ends there. ``numerical_drawdown_mean`` and
    ``analytical_drawdown`` have one row per time and one column per monitor
    point; ``monitor_radii_m`` is the distance from each read cell centre to the
    well cell centre.

    Plan-view map at the final time, one entry per solver cell inside the map
    window, for figures:

    - ``map_cell_polygons``: the cell outline, in metres from the stream face
      (x) and from the well (y), rounded to 0.01 m;
    - ``map_simulated``: the simulated head;
    - ``map_reference``: the closed-form head at the cell centre, the stream
      head on the stream cells and NaN in the well cell, where it is singular;
    - ``map_overlay``: the well. The stream is the west edge of the map.
    """

    result: ValidationRunResult
    metadata: dict
    tolerances: dict
    solver_name: str
    elapsed_days: np.ndarray
    stream_x_m: float
    well_xy_m: tuple[float, float]
    well_to_stream_m: float
    numerical_depletion_fraction: np.ndarray
    analytical_depletion_fraction: np.ndarray
    depletion_max_error: float
    depletion_final_error: float
    monitor_points_m: np.ndarray
    monitor_cell_xy_m: np.ndarray
    monitor_radii_m: np.ndarray
    numerical_drawdown_mean: np.ndarray
    analytical_drawdown: np.ndarray
    space_time_rmse: float
    space_time_max_error: float
    final_time_rmse: float
    final_time_max_error: float
    well_drawdown_fraction: float
    map_cell_polygons: list[list[tuple[float, float]]]
    map_simulated: np.ndarray
    map_reference: np.ndarray
    map_overlay: dict


def _cell_history(store, sim_id: str, name: str, *, n_periods: int) -> np.ndarray:
    """Return one stored per-cell history, as ``(n_periods, n_cells)``.

    Every solver stores one slice per stress period: a head at the period end,
    a flux as the mean of the period.
    """
    sz = store.open_zarr(sim_id)
    try:
        root = sz.root
        group = next(
            (g for g in (root, root.get("budget"), root.get("derived")) if g and name in g),
            None,
        )
        if group is None:
            raise KeyError(f"Run {sim_id} stores no per-cell '{name}' history.")
        values = np.asarray(group[name][:], dtype=float)
    finally:
        sz.close()
    values = values.reshape(values.shape[0], -1)
    if values.shape[0] != n_periods:
        raise AssertionError(
            f"'{name}' has {values.shape[0]} outputs for {n_periods} stress periods; "
            "a run stores one output per stress period."
        )
    return values


def _bundle_triangles(bundle_dir: Path) -> list[np.ndarray]:
    """Return the triangles of a mesh bundle as ``(3, 2)`` vertex arrays."""
    read = lambda name: np.genfromtxt(  # noqa: E731
        bundle_dir / name, delimiter=",", names=True, dtype=None, encoding="utf-8"
    )
    nodes, cells = read("nodes.csv"), read("cells.csv")
    xy = np.column_stack([nodes["x"], nodes["y"]]).astype(float)
    corners = np.column_stack([cells["n0"], cells["n1"], cells["n2"]]).astype(int)
    return [xy[row] for row in corners]


def _cell_geometry(
    *, result, solver_name: str, metadata: dict, n_cells: int
) -> tuple[list[np.ndarray], np.ndarray]:
    """Return the outline and the centre of every solver cell of one run.

    A grid with no mesh bundle has square cells centred on their vertex mean.
    A triangle cell is centred on its centroid, a Voronoi cell on its node.
    """
    bundle_solver = BUNDLE_SOLVER if solver_name in BOUSSINESQ_SOLVERS else solver_name
    bundle_dir = resolve_case_mesh_bundle_dir(CASE_DIR, metadata, bundle_solver)
    if solver_name in BOUSSINESQ_SOLVERS:
        polygons = _bundle_triangles(bundle_dir)
    else:
        polygons = load_cell_polygons(store=result.store, sim_id=result.sim_id)
    if len(polygons) != n_cells:
        raise ValueError(f"{len(polygons)} cell outlines for {n_cells} cells.")
    if bundle_dir is None:
        centers = np.asarray([polygon.mean(axis=0) for polygon in polygons], dtype=float)
    else:
        centers, _ = bundle_cell_centers(bundle_dir, n_cells)
    return polygons, np.asarray(centers, dtype=float)


def _stream_cells_and_weights(
    polygons: list[np.ndarray], *, face_x: float, well_y: float, nominal_distance: float
) -> tuple[np.ndarray, np.ndarray]:
    """Return the cells that own an edge on the west face and the depletion share of each.

    The share is the integral over the cell's face edge of the steady flux
    density of the closed form, ``a / (a^2 + y^2)`` with ``y`` measured from
    the well.
    """
    cells: list[int] = []
    weights: list[float] = []
    for index, polygon in enumerate(polygons):
        on_face = polygon[np.abs(polygon[:, 0] - face_x) <= _FACE_ATOL_M]
        if on_face.shape[0] < 2:
            continue
        y_low, y_high = float(on_face[:, 1].min()), float(on_face[:, 1].max())
        cells.append(index)
        weights.append(
            float(
                np.arctan((y_high - well_y) / nominal_distance)
                - np.arctan((y_low - well_y) / nominal_distance)
            )
        )
    if not cells:
        raise ValueError("No cell owns an edge on the stream face.")
    return np.asarray(cells, dtype=int), np.asarray(weights, dtype=float)


def build_stream_depletion_comparison(
    *,
    result: ValidationRunResult,
    solver: str | None = None,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> StreamDepletionComparison:
    """Load one completed run and compare it with the image-well solution."""
    solver_name = str(getattr(result, "solver_name", "")).strip().lower() or str(solver)
    metadata = load_case_metadata(CASE_DIR) if metadata is None else metadata
    tolerances = (
        load_case_tolerances(CASE_DIR, solver=solver_name) if tolerances is None else tolerances
    )
    reference_cfg = dict(metadata["reference"])
    plot_cfg = dict(metadata.get("plot", {}))
    dt_days = float(metadata["time"]["dt_seconds"]) / SECONDS_PER_DAY

    n_periods = int(metadata["output"]["expected_periods"])
    heads, stream_flux, well_flux = (
        _cell_history(result.store, result.sim_id, name, n_periods=n_periods)
        for name in ("head", "constant_head", "well")
    )
    n_times, n_cells = heads.shape
    elapsed_days = (np.arange(n_times, dtype=float) + 1.0) * dt_days

    polygons, centers = _cell_geometry(
        result=result, solver_name=solver_name, metadata=metadata, n_cells=n_cells
    )
    face_x = float(reference_cfg["xmin"])
    well_cell = int(np.argmax(np.abs(well_flux[-1])))
    well_xy = (float(centers[well_cell, 0]), float(centers[well_cell, 1]))
    stream_cells, stream_weights = _stream_cells_and_weights(
        polygons,
        face_x=face_x,
        well_y=well_xy[1],
        nominal_distance=float(reference_cfg["well_x_m"]) - face_x,
    )
    stream_x = float(np.average(centers[stream_cells, 0], weights=stream_weights))
    distance = well_xy[0] - stream_x

    base_head = float(reference_cfg["base_head_m"])
    thickness = float(reference_cfg["reference_saturated_thickness_m"])
    pumping_m3_day = float(reference_cfg["pumping_rate_m3_day"])
    closed_form = {
        "well_xy": well_xy,
        "stream_x_m": stream_x,
        "pumping_rate_m3_day": pumping_m3_day,
        "transmissivity_m2_day": transmissivity_m2_day(
            hydraulic_conductivity_m_per_s=float(reference_cfg["hydraulic_conductivity_m_per_s"]),
            saturated_thickness_m=thickness,
        ),
        "storage": float(reference_cfg["specific_yield"]),
    }

    numerical_fraction = stream_flux[:, stream_cells].sum(axis=1) * SECONDS_PER_DAY / pumping_m3_day
    analytical_fraction = stream_depletion_period_mean_fraction(
        period_start_days=elapsed_days - dt_days,
        period_end_days=elapsed_days,
        distance_m=distance,
        transmissivity_m2_day=closed_form["transmissivity_m2_day"],
        storage=closed_form["storage"],
    )

    from scipy.spatial import cKDTree

    points = np.asarray(plot_cfg["monitor_points_m"], dtype=float).reshape(-1, 2)
    _, monitor_cells = cKDTree(centers).query(points)
    monitor_xy = centers[monitor_cells]
    numerical_drawdown = base_head - heads[:, monitor_cells]
    analytical_drawdown = image_well_drawdown(
        x_m=monitor_xy[:, 0], y_m=monitor_xy[:, 1], times_days=elapsed_days, **closed_form
    )

    window_x = np.asarray(plot_cfg["map_window_x_m"], dtype=float) + face_x
    window_y = np.asarray(plot_cfg["map_window_y_m"], dtype=float) + well_xy[1]
    in_window = (
        (centers[:, 0] >= window_x[0])
        & (centers[:, 0] <= window_x[1])
        & (centers[:, 1] >= window_y[0])
        & (centers[:, 1] <= window_y[1])
    )
    map_cells = np.flatnonzero(in_window)
    free = np.ones(n_cells, dtype=bool)
    free[stream_cells] = False
    free[well_cell] = False
    map_reference = np.full(n_cells, np.nan, dtype=float)
    map_reference[~free] = base_head
    map_reference[well_cell] = np.nan
    map_reference[free] = (
        base_head
        - image_well_drawdown(
            x_m=centers[free, 0], y_m=centers[free, 1], times_days=elapsed_days[-1:], **closed_form
        )[0]
    )

    return StreamDepletionComparison(
        result=result,
        metadata=metadata,
        tolerances=tolerances,
        solver_name=solver_name,
        elapsed_days=elapsed_days,
        stream_x_m=stream_x,
        well_xy_m=well_xy,
        well_to_stream_m=distance,
        numerical_depletion_fraction=numerical_fraction,
        analytical_depletion_fraction=analytical_fraction,
        depletion_max_error=max_abs_error(numerical_fraction, analytical_fraction),
        depletion_final_error=float(abs(numerical_fraction[-1] - analytical_fraction[-1])),
        monitor_points_m=points,
        monitor_cell_xy_m=monitor_xy,
        monitor_radii_m=np.hypot(monitor_xy[:, 0] - well_xy[0], monitor_xy[:, 1] - well_xy[1]),
        numerical_drawdown_mean=numerical_drawdown,
        analytical_drawdown=analytical_drawdown,
        space_time_rmse=rmse(numerical_drawdown, analytical_drawdown),
        space_time_max_error=max_abs_error(numerical_drawdown, analytical_drawdown),
        final_time_rmse=rmse(numerical_drawdown[-1], analytical_drawdown[-1]),
        final_time_max_error=max_abs_error(numerical_drawdown[-1], analytical_drawdown[-1]),
        well_drawdown_fraction=float(np.max(base_head - heads[:, well_cell]) / thickness),
        map_cell_polygons=map_polygons_payload(
            [polygons[index] for index in map_cells], origin_x=face_x, origin_y=well_xy[1]
        ),
        map_simulated=heads[-1, map_cells],
        map_reference=map_reference[map_cells],
        map_overlay={"well": [round(well_xy[0] - face_x, 2), 0.0]},
    )


def run_stream_depletion_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
) -> StreamDepletionComparison:
    """Run one solver variant of the case and return its comparison payload."""
    solver_name = str(solver or load_case_metadata(CASE_DIR)["default_solver"]).strip().lower()
    if solver_name in BOUSSINESQ_SOLVERS:
        result = run_boussinesq_stream_depletion_case(
            caller_file=caller_file, timeout=timeout, public_solver_label=solver_name
        )
    else:
        result = run_launcher_validation_case(
            case_dir=CASE_DIR, test_file=caller_file, timeout=timeout, solver=solver_name
        )
    return build_stream_depletion_comparison(result=result, solver=solver_name)


__all__ = [
    "StreamDepletionComparison",
    "build_stream_depletion_comparison",
    "run_stream_depletion_comparison",
]
