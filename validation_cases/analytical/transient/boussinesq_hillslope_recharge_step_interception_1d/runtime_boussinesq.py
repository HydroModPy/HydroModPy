"""Local transient Boussinesq runtime for the hillslope recharge-step interception case."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hydromodpy.model.flow import Flow
from validation_cases.analytical.steady.boussinesq_hillslope_interception_1d.runtime_boussinesq import (
    EAST_HEAD_M,
    NX,
    NY,
    _build_flow_config,
    _write_hillslope_strip_bundle,
)
from validation_cases.analytical.steady.boussinesq_piecewise import mm_day_to_m_s
from validation_cases.analytical.transient.runtime_boussinesq_1d import (
    aggregate_triangle_history_to_structured_fields,
)
from validation_cases.shared.boussinesq_analytical_runtime import (
    boussinesq_variant_flow_section,
    boussinesq_variant_options,
    solve_boussinesq_bundle,
)
from validation_cases.shared.runtime import (
    ValidationRunResult,
    resolve_validation_results_dir,
    write_validation_fields_to_store,
)

CASE_ID = "boussinesq_hillslope_recharge_step_interception_1d"
DT_DAYS = 10.0
NPER = 12
RECHARGE_MM_DAY = 2.0


def run_boussinesq_hillslope_recharge_step_interception_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    public_solver_label: str = "boussinesq",
) -> ValidationRunResult:
    """Run the transient recharge-step hillslope case for one Boussinesq variant."""
    del timeout

    out_path = resolve_validation_results_dir(
        test_file=caller_file,
        run_name=f"{CASE_ID}_{public_solver_label}",
    )
    bundle_dir = _write_hillslope_strip_bundle(out_path / "mesh_bundle")
    simulations_folder = out_path / "results_simulations"
    simulations_folder.mkdir(parents=True, exist_ok=True)
    period_lengths_seconds = tuple(86400.0 * DT_DAYS for _ in range(NPER))

    solved = solve_boussinesq_bundle(
        flow=Flow(
            _build_flow_config(
                boussinesq_variant_flow_section(
                    {
                        "flow_regime": "transient",
                        "ic": {"kind": "custom", "value": EAST_HEAD_M},
                        "sinks_sources": {
                            "recharge": {
                                "values": mm_day_to_m_s(RECHARGE_MM_DAY),
                                "first_clim": "mean",
                                "units": "m/s",
                            }
                        },
                        "bc": {
                            "east_side": {"value": EAST_HEAD_M},
                        },
                    },
                    flow_regime="transient",
                )
            )
        ),
        bundle_dir=bundle_dir,
        simulations_folder=simulations_folder,
        time_grid=SimpleNamespace(
            period_lengths_seconds=period_lengths_seconds,
            window=None,
        ),
        options=boussinesq_variant_options(
            flow_regime="transient",
            solver=public_solver_label,
        ),
        plan_name="Boussinesq hillslope recharge-step interception validation",
        plan_description="Transient recharge-step hillslope with seepage onset",
    )
    model = solved.solver_model
    field_series = aggregate_triangle_history_to_structured_fields(
        model,
        nx=NX,
        ny=NY,
    )

    model_ws = Path(model.full_path)
    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"
    store, sim_id = write_validation_fields_to_store(
        out_path=out_path,
        fields=field_series,
        solver_name="boussinesq",
        flow_regime="transient",
    )
    return ValidationRunResult(
        case_dir=Path(__file__).resolve().parent,
        solver_name=public_solver_label,
        out_path=out_path,
        model_ws=model_ws,
        postprocess_dir=postprocess_dir,
        particles_dir=particles_dir,
        run_returncode=0,
        run_stdout="",
        run_stderr="",
        store=store,
        sim_id=sim_id,
    )


__all__ = ["run_boussinesq_hillslope_recharge_step_interception_case"]
