"""``flow/boussinesq`` runtime for the stream depletion 2D validation case.

The run solves on the triangles of the case mesh bundle, the mesh of the MODFLOW
6 triangle variant. Each stress period takes the substeps of the MODFLOW runs.
The store keeps, per triangle and per period, the head, the flux the stream
cells give the aquifer and the well flux, with the MODFLOW sign: positive into
the aquifer.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.core.state.run_state import RunState
from hydromodpy.core.state.setup import SetupContext
from hydromodpy.physics.flow import Flow
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.simulation.planning.plan import ProcessRun, RunContext, SimulationPlan
from hydromodpy.solver.boussinesq.adapters.flow import BoussinesqFlowAdapter
from validation_cases.shared import load_case_metadata
from validation_cases.shared.boussinesq_analytical_runtime import (
    boussinesq_variant_config_name,
    boussinesq_variant_flow_section,
)
from validation_cases.shared.loaders import merge_case_flow_section, resolve_case_mesh_bundle_dir
from validation_cases.shared.runtime import (
    ValidationRunResult,
    resolve_validation_results_dir,
    write_validation_fields_to_store,
)

CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "stream_depletion_glover_balmer_2d"
# The MODFLOW 6 triangle variant names the bundle the Boussinesq runs share.
BUNDLE_SOLVER = "modflow6_irregular_tri"


def _build_flow_config(flow_section: dict[str, object], *, config_name: str) -> FlowConfig:
    merged_flow = merge_case_flow_section(CASE_DIR, flow_section, config_name=config_name)
    return FlowConfig.from_toml_section(merged_flow, base_dir=CASE_DIR)


def _period_rows(history: np.ndarray, n_periods: int, *, label: str) -> np.ndarray:
    """Return one row per stress period, dropping the initial state when stored."""
    rows = np.asarray(history, dtype=float)
    if rows.ndim == 1:
        rows = rows.reshape(1, -1)
    if rows.shape[0] == n_periods + 1:
        return rows[1:]
    if rows.shape[0] != n_periods:
        raise ValueError(f"Boussinesq {label} has {rows.shape[0]} rows for {n_periods} periods.")
    return rows


def run_boussinesq_stream_depletion_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    public_solver_label: str = "boussinesq",
) -> ValidationRunResult:
    """Run the stream depletion case through the Boussinesq adapter."""
    del timeout
    solver_name = str(public_solver_label or "boussinesq")
    metadata = load_case_metadata(CASE_DIR)
    reference_cfg = dict(metadata.get("reference", {}))
    output_cfg = dict(metadata.get("output", {}))
    time_cfg = dict(metadata.get("time", {}))
    base_head_m = float(reference_cfg["base_head_m"])
    n_periods = int(output_cfg["expected_periods"])
    substeps = int(time_cfg["substeps_per_period"])
    simulations_folder_name = str(
        metadata.get("workspace", {}).get("results_folder_name", "results_simulations")
    )

    out_path = resolve_validation_results_dir(
        test_file=caller_file, run_name=f"{CASE_ID}_{solver_name}"
    )
    source_bundle = resolve_case_mesh_bundle_dir(CASE_DIR, metadata, BUNDLE_SOLVER)
    if source_bundle is None:
        raise FileNotFoundError(f"No mesh bundle declared for {BUNDLE_SOLVER}.")
    # The run may write beside its bundle: it works on a copy.
    bundle_dir = out_path / "mesh_bundle"
    shutil.copytree(source_bundle, bundle_dir)
    simulations_folder = out_path / simulations_folder_name

    flow_section = boussinesq_variant_flow_section(
        {
            "flow_regime": "transient",
            "ic": {"type": "custom", "value": base_head_m},
            "active_sinks_sources": ["wells"],
            "active_bc": ["west_side"],
            "sinks_sources": {
                "wells": {
                    "P1": {
                        "location": {
                            "kind": "absolute_xy",
                            "x": float(reference_cfg["well_x_m"]),
                            "y": float(reference_cfg["well_y_m"]),
                        },
                        "flux": -float(reference_cfg["pumping_rate_m3_day"]),
                        "units": "m3/day",
                    }
                }
            },
            "bc": {"west_side": {"value": base_head_m}},
            # One TS step in each substep: the time steps of the MODFLOW runs.
            "ts_vi_steps_per_period": 1,
        },
        flow_regime="transient",
        solver=solver_name,
    )
    state = RunState(
        setup=SetupContext(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(
                _build_flow_config(
                    flow_section, config_name=boussinesq_variant_config_name(solver_name)
                )
            ),
            domain=None,
            time_grid=SimpleNamespace(
                period_lengths_seconds=tuple(
                    float(time_cfg["dt_seconds"]) for _ in range(n_periods)
                ),
                nstp_per_period=substeps,
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
            name="Boussinesq stream depletion validation",
            description="Well beside a stream held on the west side, other sides closed",
            runs=(run,),
        ),
        run=run,
        state=state,
    )
    model = BoussinesqFlowAdapter().execute(ctx).primary_model
    if model.state is None:
        raise RuntimeError("The Boussinesq run returned no state.")

    heads = _period_rows(model.state.head_history_m, n_periods, label="head history")
    # The solver signs the prescribed-head flux positive out of the aquifer.
    stream = -_period_rows(
        model.state.prescribed_head_flux_history_m3_s, n_periods, label="prescribed-head flux"
    )
    well = _period_rows(model.state.well_flux_history_m3_s, n_periods, label="well flux")
    fields = {
        "head": dict(enumerate(heads)),
        "constant_head": dict(enumerate(stream)),
        "well": dict(enumerate(well)),
    }
    model_ws = Path(model.full_path)
    store, sim_id = write_validation_fields_to_store(
        out_path=out_path, fields=fields, solver_name="boussinesq", flow_regime="transient"
    )
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


__all__ = ["run_boussinesq_stream_depletion_case"]
