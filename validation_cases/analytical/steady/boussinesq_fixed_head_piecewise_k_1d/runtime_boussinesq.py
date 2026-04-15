"""Local `flow/boussinesq` runtime for the fixed-head piecewise-K validation case."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hydromodpy.process.flow import Flow
from hydromodpy.process.flow.flow_config import FlowConfig
from hydromodpy.simulation.adapters.flow.boussinesq import BoussinesqFlowAdapter
from hydromodpy.simulation.planning.plan import (
    ProcessRun,
    RunContext,
    SimulationPlan,
)
from validation_cases.shared.runtime import (
    ValidationRunResult,
    resolve_validation_results_dir,
)
from validation_cases.shared.loaders import merge_case_flow_section
from validation_cases.shared.boussinesq_piecewise_strip import (
    PIECEWISE_STRIP_HYDRAULIC_CONDUCTIVITY_M_S_BY_ZONE,
    PIECEWISE_STRIP_LENGTH_X_M,
    PIECEWISE_STRIP_NX,
    PIECEWISE_STRIP_NY,
    PIECEWISE_STRIP_STORAGE_COEFFICIENT,
    PIECEWISE_STRIP_WIDTH_Y_M,
    PIECEWISE_STRIP_X_ZONE_BREAKS_M,
    PIECEWISE_STRIP_Z_BOTTOM_M,
    PIECEWISE_STRIP_Z_TOP_M,
    aggregate_triangle_history_to_structured_grids,
    write_piecewise_strip_bundle,
)


CASE_ID = "boussinesq_fixed_head_piecewise_k_1d"
NX = PIECEWISE_STRIP_NX
NY = PIECEWISE_STRIP_NY
LENGTH_X_M = PIECEWISE_STRIP_LENGTH_X_M
WIDTH_Y_M = PIECEWISE_STRIP_WIDTH_Y_M
Z_TOP_M = PIECEWISE_STRIP_Z_TOP_M
Z_BOTTOM_M = PIECEWISE_STRIP_Z_BOTTOM_M
WEST_HEAD_M = 10.0
EAST_HEAD_M = 5.0
X_ZONE_BREAKS_M = PIECEWISE_STRIP_X_ZONE_BREAKS_M
HYDRAULIC_CONDUCTIVITY_M_S_BY_ZONE = PIECEWISE_STRIP_HYDRAULIC_CONDUCTIVITY_M_S_BY_ZONE
STORAGE_COEFFICIENT = PIECEWISE_STRIP_STORAGE_COEFFICIENT


def _build_flow_config(
    flow_section: dict[str, object],
    *,
    case_dir: Path | None = None,
) -> FlowConfig:
    base_dir = Path(".") if case_dir is None else Path(case_dir)
    merged_flow = (
        dict(flow_section)
        if case_dir is None
        else merge_case_flow_section(Path(case_dir), flow_section)
    )
    return FlowConfig.from_toml_section(merged_flow, base_dir=base_dir)


def _write_piecewise_strip_bundle(bundle_dir: Path) -> Path:
    return write_piecewise_strip_bundle(bundle_dir)


def _aggregate_triangle_history_to_structured_grids(model) -> None:
    aggregate_triangle_history_to_structured_grids(
        model,
        nx=NX,
        ny=NY,
        export_initial_state=True,
    )


def run_boussinesq_fixed_head_piecewise_k_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
) -> ValidationRunResult:
    """Run the fixed-head piecewise-K case through the local `flow/boussinesq` adapter."""
    del timeout

    out_path = resolve_validation_results_dir(
        test_file=caller_file,
        run_name=f"{CASE_ID}_boussinesq",
    )
    bundle_dir = _write_piecewise_strip_bundle(out_path / "mesh_bundle")
    simulations_folder = out_path / "results_simulations"
    simulations_folder.mkdir(parents=True, exist_ok=True)

    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(
                _build_flow_config(
                    {
                        "flow_regime": "steady",
                        "ic": {"type": "custom", "value": 7.5},
                        "active_bc": ["west_side", "east_side"],
                        "bc": {
                            "dirichlet": {
                                "west_side": {"value": WEST_HEAD_M},
                                "east_side": {"value": EAST_HEAD_M},
                            }
                        },
                    },
                    case_dir=Path(__file__).resolve().parent,
                )
            ),
            domain=None,
            time_grid=None,
            workspace=SimpleNamespace(simulations_folder=simulations_folder, solver_scratch_folder=simulations_folder),
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
            name="Boussinesq fixed-head validation",
            description="Steady piecewise-K fixed-head strip",
            runs=(run,),
        ),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model
    _aggregate_triangle_history_to_structured_grids(model)

    model_ws = Path(model.full_path)
    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"
    return ValidationRunResult(
        case_dir=Path(__file__).resolve().parent,
        solver_name="boussinesq",
        out_path=out_path,
        model_ws=model_ws,
        postprocess_dir=postprocess_dir,
        particles_dir=particles_dir,
        run_returncode=0,
        run_stdout="",
        run_stderr="",
    )


__all__ = ["run_boussinesq_fixed_head_piecewise_k_case"]
