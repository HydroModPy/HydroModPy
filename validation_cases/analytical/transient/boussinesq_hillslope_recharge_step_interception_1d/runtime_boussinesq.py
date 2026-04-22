"""Local transient Boussinesq runtime for the hillslope recharge-step interception case."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hydromodpy.physics.flow import Flow
from hydromodpy.simulation.adapters.flow.boussinesq import BoussinesqFlowAdapter
from hydromodpy.simulation.planning.plan import (
    ProcessRun,
    RunContext,
    SimulationPlan,
)
from validation_cases.analytical.steady.boussinesq_hillslope_interception_1d.runtime_boussinesq import (
    _build_flow_config,
    _write_hillslope_strip_bundle,
    EAST_HEAD_M,
    NY,
    NX,
)
from validation_cases.analytical.steady.boussinesq_piecewise import mm_day_to_m_s
from validation_cases.analytical.transient.runtime_boussinesq_1d import (
    aggregate_triangle_history_to_structured_grids,
)
from validation_cases.shared.runtime import (
    ValidationRunResult,
    resolve_validation_results_dir,
)


CASE_ID = "boussinesq_hillslope_recharge_step_interception_1d"
DT_DAYS = 10.0
NPER = 12
RECHARGE_MM_DAY = 2.0


def run_boussinesq_hillslope_recharge_step_interception_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
) -> ValidationRunResult:
    """Run the transient recharge-step hillslope case through the local Boussinesq adapter."""
    del timeout

    out_path = resolve_validation_results_dir(
        test_file=caller_file,
        run_name=f"{CASE_ID}_boussinesq",
    )
    bundle_dir = _write_hillslope_strip_bundle(out_path / "mesh_bundle")
    simulations_folder = out_path / "results_simulations"
    simulations_folder.mkdir(parents=True, exist_ok=True)
    period_lengths_seconds = tuple(86400.0 * DT_DAYS for _ in range(NPER))

    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(
                _build_flow_config(
                    {
                        "flow_regime": "transient",
                        "ic": {"type": "custom", "value": EAST_HEAD_M},
                        "active_sinks_sources": ["recharge"],
                        "active_bc": ["east_side"],
                        "sinks_sources": {
                            "recharge": {
                                "values": mm_day_to_m_s(RECHARGE_MM_DAY),
                                "first_clim": "mean",
                                "units": "m/s",
                            }
                        },
                        "bc": {
                            "dirichlet": {
                                "east_side": {"value": EAST_HEAD_M},
                            }
                        },
                    }
                )
            ),
            domain=None,
            time_grid=SimpleNamespace(
                period_lengths_seconds=period_lengths_seconds,
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
            name="Boussinesq hillslope recharge-step interception validation",
            description="Transient recharge-step hillslope with seepage onset",
            runs=(run,),
        ),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model
    aggregate_triangle_history_to_structured_grids(
        model,
        nx=NX,
        ny=NY,
    )

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


__all__ = ["run_boussinesq_hillslope_recharge_step_interception_case"]
