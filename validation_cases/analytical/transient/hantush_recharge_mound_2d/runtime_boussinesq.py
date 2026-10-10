"""``flow/boussinesq`` runtime for the 2D recharge mound validation case.

The runtime solves the case on the triangles of the case mesh bundle, refined
under the recharge rectangle, and reads the recharge from the same raster as
the launcher runs, through the same discretization: each triangle takes the
pixel under its centroid.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.core.state.run_state import RunState
from hydromodpy.core.state.setup import SetupContext
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.ingest.custom_grids import load_custom_tif
from hydromodpy.physics.flow import Flow
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.simulation.planning.plan import ProcessRun, RunContext, SimulationPlan
from hydromodpy.solver.boussinesq.adapters.flow import BoussinesqFlowAdapter
from validation_cases.shared import load_case_metadata
from validation_cases.shared.boussinesq_analytical_runtime import (
    boussinesq_variant_config_name,
    boussinesq_variant_flow_section,
)
from validation_cases.shared.loaders import merge_case_flow_section
from validation_cases.shared.runtime import (
    ValidationRunResult,
    resolve_validation_results_dir,
    write_validation_fields_to_store,
)

from .build_inputs import RASTER_PATH, TRIANGLE_BUNDLE_DIR

CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "hantush_recharge_mound_2d"
FINAL_CELL_HEADS = "final_cell_heads.npy"
# Top of the cells in the bundle, for the depth to the water table.
TOP_M = 60.0


def nearest_centroid_indices(centroids_xy: np.ndarray, points_xy: np.ndarray) -> np.ndarray:
    """Return the index of the triangle centroid nearest to each point."""
    from scipy.spatial import cKDTree

    _, nearest = cKDTree(np.asarray(centroids_xy, dtype=float)).query(
        np.asarray(points_xy, dtype=float)
    )
    return np.asarray(nearest, dtype=int)


def _structured_centres(metadata: dict) -> tuple[np.ndarray, np.ndarray]:
    """Return the x and y centres of the validation grid, y from the south."""
    reference_cfg = dict(metadata["reference"])
    ny, nx = (int(value) for value in metadata["output"]["expected_spatial_shape"])
    dx = (float(reference_cfg["xmax"]) - float(reference_cfg["xmin"])) / nx
    dy = (float(reference_cfg["ymax"]) - float(reference_cfg["ymin"])) / ny
    x = float(reference_cfg["xmin"]) + (np.arange(nx) + 0.5) * dx
    y = float(reference_cfg["ymin"]) + (np.arange(ny) + 0.5) * dy
    return x, y


def run_boussinesq_hantush_recharge_mound_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    public_solver_label: str = "boussinesq",
) -> ValidationRunResult:
    """Run the recharge mound through the Boussinesq adapter on the case triangles.

    The head history is projected on the 101 x 101 validation grid, rows from
    the south, each grid cell taking the triangle with the nearest centroid.
    The final head of every triangle is kept in ``final_cell_heads.npy``.
    """
    del timeout
    solver_name = str(public_solver_label or "boussinesq")
    metadata = load_case_metadata(CASE_DIR)
    reference_cfg = dict(metadata["reference"])
    nper = int(metadata["output"]["expected_periods"])
    dt_seconds = float(metadata["time"]["dt_seconds"])
    initial_head_m = float(reference_cfg["initial_head_m"])

    out_path = resolve_validation_results_dir(
        test_file=caller_file, run_name=f"{CASE_ID}_{solver_name}"
    )
    bundle_dir = out_path / "mesh_bundle"
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    shutil.copytree(TRIANGLE_BUNDLE_DIR, bundle_dir)
    simulations_folder = out_path / "results_simulations"

    recharge_source = LoadResult(
        fields=load_custom_tif(
            RASTER_PATH, variable="recharge", unit="mm/day", source_unit="mm/day"
        )
    )
    flow_section = boussinesq_variant_flow_section(
        {
            "flow_regime": "transient",
            "ic": {"type": "custom", "value": initial_head_m},
            "active_sinks_sources": ["recharge"],
            "active_bc": ["west_side", "east_side", "north_side", "south_side"],
            "sinks_sources": {
                "recharge": {
                    "heterogeneous_source": recharge_source,
                    "spatial_mode": "heterogeneous",
                    "interpolation_method": "nearest",
                }
            },
            "bc": {
                side: {"value": initial_head_m}
                for side in ("west_side", "east_side", "north_side", "south_side")
            },
        },
        flow_regime="transient",
        solver=solver_name,
    )
    merged_flow = merge_case_flow_section(
        CASE_DIR, flow_section, config_name=boussinesq_variant_config_name(solver_name)
    )
    flow = Flow(FlowConfig.from_toml_section(merged_flow, base_dir=CASE_DIR))

    state = RunState(
        setup=SetupContext(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=flow,
            domain=None,
            time_grid=SimpleNamespace(
                period_lengths_seconds=tuple(dt_seconds for _ in range(nper)),
                window=None,
            ),
            workspace=SimpleNamespace(
                simulations_folder=simulations_folder, solver_scratch_folder=simulations_folder
            ),
        ),
    )
    run = ProcessRun(
        id="flow_validation::boussinesq",
        process_id="flow_validation",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(
            name="Boussinesq recharge mound validation",
            description="Transient mound under a rectangle of recharge, side Dirichlet boundaries",
            runs=(run,),
        ),
        run=run,
        state=state,
    )
    model = BoussinesqFlowAdapter().execute(ctx).primary_model
    if model.state is None or model.mesh is None:
        raise RuntimeError("Boussinesq recharge mound case requires a solved model state.")

    history = np.atleast_2d(np.asarray(model.state.head_history_m, dtype=float))
    if history.shape[0] > nper:
        history = history[1:, :]
    np.save(out_path / FINAL_CELL_HEADS, history[-1])

    x_centres, y_centres = _structured_centres(metadata)
    xx, yy = np.meshgrid(x_centres, y_centres)
    centroids = np.column_stack([model.mesh.cell_centroid_x_m, model.mesh.cell_centroid_y_m])
    nearest = nearest_centroid_indices(centroids, np.column_stack([xx.ravel(), yy.ravel()]))
    nearest = nearest.reshape(y_centres.size, x_centres.size)
    fields = {
        "watertable_elevation": {index: heads[nearest] for index, heads in enumerate(history)},
        "watertable_depth": {
            index: np.maximum(TOP_M - heads[nearest], 0.0) for index, heads in enumerate(history)
        },
    }
    store, sim_id = write_validation_fields_to_store(
        out_path=out_path, fields=fields, solver_name="boussinesq", flow_regime="transient"
    )
    model_ws = Path(model.full_path)
    return ValidationRunResult(
        case_dir=CASE_DIR,
        solver_name=solver_name,
        out_path=out_path,
        model_ws=model_ws,
        postprocess_dir=model_ws / "_postprocess",
        particles_dir=model_ws / "_postprocess" / "_particles",
        run_returncode=0,
        run_stdout="",
        run_stderr="",
        store=store,
        sim_id=sim_id,
    )


__all__ = ["nearest_centroid_indices", "run_boussinesq_hantush_recharge_mound_case"]
