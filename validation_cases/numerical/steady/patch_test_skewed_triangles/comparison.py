"""Comparison of the patch test: a uniform flow on skewed triangles.

The steady head of a uniform flow is linear in ``x``. With a transmissivity
``K (h - z_b)`` the exact field is linear in ``(h - z_b)^2``; across this thick
aquifer the two differ by 5e-6 m. A consistent flux reproduces it at every cell
centre, whatever the shape of the cells. The heads are held at the centroids of
the triangles that own a west or an east edge, so the reference is anchored
there.
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
from validation_cases.shared.loaders import (
    bundle_cell_centers,
    load_cell_polygons,
    load_last_cell_values,
    map_polygons_payload,
    resolve_case_mesh_bundle_dir,
)

CASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class PatchTestComparison:
    """Cell heads of one run against the uniform-flow head at the cell centroids.

    ``map_cell_polygons``, ``map_simulated`` and ``map_reference`` give the
    plan-view map of the run, one entry per triangle, in metres from the
    south-west corner.
    """

    result: ValidationRunResult
    metadata: dict
    tolerances: dict
    centroids_xy: np.ndarray
    numerical_heads: np.ndarray
    reference_heads: np.ndarray
    west_x_m: float
    east_x_m: float
    rms_error: float
    max_error: float
    map_cell_polygons: list[list[tuple[float, float]]]
    map_simulated: np.ndarray
    map_reference: np.ndarray


def _held_x(bundle_dir: Path, centroids_xy: np.ndarray, *, side: str) -> float:
    """Return the centroid x of the triangles that own a west or an east edge."""
    nodes = np.genfromtxt(bundle_dir / "nodes.csv", delimiter=",", names=True)
    edges = np.genfromtxt(
        bundle_dir / "edges.csv", delimiter=",", names=True, dtype=None, encoding="utf-8"
    )
    node_x = np.asarray(nodes["x"], dtype=float)
    edge_x = 0.5 * (node_x[edges["node_a"].astype(int)] + node_x[edges["node_b"].astype(int)])
    target = float(node_x.min()) if side == "west" else float(node_x.max())
    on_side = (edges["edge_kind"] == "boundary") & np.isclose(edge_x, target)
    owners = np.unique(edges["cell_a"][on_side].astype(int))
    held = np.asarray(centroids_xy[owners, 0], dtype=float)
    if held.size == 0 or np.ptp(held) > 1.0e-6:
        raise ValueError(f"The {side} held cells do not share one centroid x: {held}.")
    return float(held[0])


def uniform_flow_head(
    x_m: np.ndarray,
    *,
    west_x_m: float,
    east_x_m: float,
    west_head_m: float,
    east_head_m: float,
    bottom_elevation_m: float,
) -> np.ndarray:
    """Return the steady head with ``(h - z_b)^2`` linear between the held centroids."""
    fraction = (np.asarray(x_m, dtype=float) - west_x_m) / (east_x_m - west_x_m)
    west_sq = (west_head_m - bottom_elevation_m) ** 2
    east_sq = (east_head_m - bottom_elevation_m) ** 2
    return bottom_elevation_m + np.sqrt(west_sq + (east_sq - west_sq) * fraction)


def build_patch_test_comparison(
    *,
    result: ValidationRunResult,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> PatchTestComparison:
    """Compare the cell heads of one run with the uniform-flow head."""
    case_metadata = load_case_metadata(CASE_DIR) if metadata is None else metadata
    solver_name = str(result.solver_name).strip().lower()
    case_tolerances = (
        load_case_tolerances(CASE_DIR, solver=solver_name) if tolerances is None else tolerances
    )
    reference_cfg = dict(case_metadata["reference"])
    observable_name = str(case_metadata["output"]["observable_name"])
    heads = load_last_cell_values(
        observable_name=observable_name, store=result.store, sim_id=result.sim_id
    )
    bundle_dir = resolve_case_mesh_bundle_dir(CASE_DIR, case_metadata, solver_name)
    if bundle_dir is None:
        raise ValueError(f"No mesh bundle for solver '{solver_name}'.")
    centroids, _ = bundle_cell_centers(bundle_dir, heads.size)
    west_x_m = _held_x(bundle_dir, centroids, side="west")
    east_x_m = _held_x(bundle_dir, centroids, side="east")
    reference = uniform_flow_head(
        centroids[:, 0],
        west_x_m=west_x_m,
        east_x_m=east_x_m,
        west_head_m=float(reference_cfg["west_head_m"]),
        east_head_m=float(reference_cfg["east_head_m"]),
        bottom_elevation_m=float(reference_cfg["bottom_elevation_m"]),
    )
    polygons = load_cell_polygons(store=result.store, sim_id=result.sim_id)
    return PatchTestComparison(
        result=result,
        metadata=case_metadata,
        tolerances=case_tolerances,
        centroids_xy=centroids,
        numerical_heads=np.asarray(heads, dtype=float),
        reference_heads=reference,
        west_x_m=west_x_m,
        east_x_m=east_x_m,
        rms_error=rmse(heads, reference),
        max_error=max_abs_error(heads, reference),
        map_cell_polygons=map_polygons_payload(polygons, origin_x=0.0, origin_y=0.0),
        map_simulated=np.asarray(heads, dtype=float),
        map_reference=reference,
    )


def run_patch_test_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 600,
    solver: str | None = None,
) -> PatchTestComparison:
    """Run one solver variant through ``hmp run`` and compare its cell heads."""
    result = run_launcher_validation_case(
        case_dir=CASE_DIR,
        test_file=caller_file,
        timeout=timeout,
        solver=solver,
    )
    return build_patch_test_comparison(result=result)


__all__ = [
    "PatchTestComparison",
    "build_patch_test_comparison",
    "run_patch_test_comparison",
    "uniform_flow_head",
]
