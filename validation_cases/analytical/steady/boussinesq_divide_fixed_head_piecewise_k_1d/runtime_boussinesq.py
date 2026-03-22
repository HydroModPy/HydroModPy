"""Local `flow/boussinesq` runtime for the divide-fixed-head piecewise-K validation case."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hydromodpy.process.flow import Flow
from hydromodpy.simulation.adapters.flow.boussinesq import BoussinesqFlowAdapter
from hydromodpy.simulation.planning.plan import (
    ProcessRun,
    RunContext,
    SimulationPlan,
)
from validation_cases.analytical.steady.boussinesq_fixed_head_piecewise_k_1d.runtime_boussinesq import (
    _aggregate_triangle_history_to_structured_grids,
    _build_flow_config,
    _write_piecewise_strip_bundle,
)
from validation_cases.analytical.steady.boussinesq_piecewise import mm_day_to_m_s
from validation_cases.shared.runtime import (
    ValidationRunResult,
    resolve_validation_results_dir,
)


CASE_ID = "boussinesq_divide_fixed_head_piecewise_k_1d"
EAST_HEAD_M = 5.0
RECHARGE_MM_DAY = 1.0


def run_boussinesq_divide_fixed_head_piecewise_k_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
) -> ValidationRunResult:
    """Run the divide-fixed-head piecewise-K case through the local `flow/boussinesq` adapter."""
    del timeout

    out_path = resolve_validation_results_dir(
        test_file=caller_file,
        run_name=f"{CASE_ID}_boussinesq",
    )
    bundle_dir = _write_piecewise_strip_bundle(out_path / "mesh_bundle")
    simulations_folder = out_path / "results_simulations"

    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(
                _build_flow_config(
                    {
                        "flow_regime": "steady",
                        "ic": {"type": "custom", "value": 7.0},
                        "active_sinks_sources": ["recharge"],
                        "active_bc": ["east_side"],
                        "sinks_sources": {
                            "recharge": {
                                "values": mm_day_to_m_s(RECHARGE_MM_DAY),
                                "first_clim": "mean",
                            }
                        },
                        "bc": {
                            "dirichlet": {
                                "east_side": {"value": EAST_HEAD_M},
                            }
                        },
                    },
                    case_dir=Path(__file__).resolve().parent,
                )
            ),
            domain=None,
            time_grid=None,
            workspace=SimpleNamespace(simulations_folder=simulations_folder),
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
            name="Boussinesq divide validation",
            description="Steady piecewise-K west-divide strip",
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


__all__ = ["run_boussinesq_divide_fixed_head_piecewise_k_case"]
