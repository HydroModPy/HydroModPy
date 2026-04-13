"""Runtime for the transient hillslope recharge-pulse overflow case."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.process.flow import Flow
from hydromodpy.simulation.adapters.flow.boussinesq import BoussinesqFlowAdapter
from hydromodpy.simulation.planning.plan import (
    ProcessRun,
    RunContext,
    SimulationPlan,
)
from validation_cases.analytical.steady.boussinesq_piecewise import mm_day_to_m_s
from validation_cases.shared.boussinesq_uniform_strip import (
    aggregate_triangle_history_to_structured_grids,
    build_flow_config,
    write_uniform_strip_bundle,
)
from validation_cases.shared.loaders import load_case_metadata
from validation_cases.shared.runtime import (
    ValidationRunResult,
    resolve_validation_results_dir,
)


CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "boussinesq_hillslope_recharge_pulse_overflow_1d"
DEFAULT_SOLVER = "petsc_partition"


@dataclass(frozen=True, slots=True)
class SolverVariant:
    """One solver flavor exposed by the hillslope overflow runner."""

    solver_name: str
    label: str
    runtime_backend: str | None
    surface_interaction_model: str | None


_SOLVER_VARIANTS: dict[str, SolverVariant] = {
    "boussinesq": SolverVariant(
        solver_name="boussinesq",
        label="Local dense runtime",
        runtime_backend=None,
        surface_interaction_model="regularized_partition",
    ),
    "scipy_sparse": SolverVariant(
        solver_name="scipy_sparse",
        label="SciPy sparse regularized partition",
        runtime_backend="scipy_sparse",
        surface_interaction_model="regularized_partition",
    ),
    "petsc": SolverVariant(
        solver_name="petsc",
        label="PETSc complementarity",
        runtime_backend="petsc",
        surface_interaction_model="complementarity",
    ),
    "petsc_partition": SolverVariant(
        solver_name="petsc_partition",
        label="PETSc regularized partition",
        runtime_backend="petsc",
        surface_interaction_model="regularized_partition",
    ),
}


def resolve_solver_variant(solver: str | None) -> SolverVariant:
    """Normalize one solver name into the runtime settings used by the case."""
    key = DEFAULT_SOLVER if solver is None else str(solver).strip().lower()
    if key not in _SOLVER_VARIANTS:
        supported = ", ".join(sorted(_SOLVER_VARIANTS))
        raise ValueError(f"Unsupported solver '{solver}'. Supported values: {supported}.")
    return _SOLVER_VARIANTS[key]


def _topography_m(x_m: np.ndarray | float, *, geometry_cfg: dict[str, object]) -> np.ndarray:
    x_values = np.asarray(x_m, dtype=float)
    return float(geometry_cfg["toe_elevation_m"]) + (
        float(geometry_cfg["topography_slope_m_per_m"])
        * (float(geometry_cfg["length_x_m"]) - x_values)
    )


def _resolve_case_settings(
    metadata: dict[str, object],
    *,
    variant: SolverVariant,
    forcing_preset: str | None,
    forcing_scale: float,
    east_head_m: float | None,
    initial_head_m: float | None,
    dt_days: float | None,
    runtime_max_iterations: int | None,
    runtime_tol_residual_inf: float | None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], int | None, float | None]:
    geometry_cfg = dict(metadata.get("geometry", {}))
    time_cfg = dict(metadata.get("time", {}))
    forcing_cfg = dict(metadata.get("forcing", {}))

    preset_name = str(forcing_preset or "").strip().lower()
    if preset_name not in {"", "default", "baseline"}:
        presets = dict(metadata.get("forcing_presets", {}))
        if preset_name not in presets:
            supported = ", ".join(sorted(str(key) for key in presets))
            raise ValueError(
                f"Unsupported forcing preset '{forcing_preset}'. Supported values: {supported}."
            )
        preset_cfg = dict(presets[preset_name])
        if "east_head_m" in preset_cfg:
            geometry_cfg["east_head_m"] = float(preset_cfg["east_head_m"])
        if "initial_head_m" in preset_cfg:
            geometry_cfg["initial_head_m"] = float(preset_cfg["initial_head_m"])
        if "dt_days" in preset_cfg:
            time_cfg["dt_days"] = float(preset_cfg["dt_days"])
        if "recharge_mm_day" in preset_cfg:
            forcing_cfg["recharge_mm_day"] = list(preset_cfg["recharge_mm_day"])

    if east_head_m is not None:
        geometry_cfg["east_head_m"] = float(east_head_m)
    if initial_head_m is not None:
        geometry_cfg["initial_head_m"] = float(initial_head_m)
    if dt_days is not None:
        time_cfg["dt_days"] = float(dt_days)

    recharge_mm_day = np.asarray(forcing_cfg.get("recharge_mm_day", ()), dtype=float).reshape(-1)
    if recharge_mm_day.size == 0:
        raise ValueError("The overflow case requires a non-empty recharge chronicle.")
    if float(forcing_scale) <= 0.0:
        raise ValueError("forcing_scale must be strictly positive.")
    recharge_mm_day = recharge_mm_day * float(forcing_scale)
    forcing_cfg["recharge_mm_day"] = [float(value) for value in recharge_mm_day]
    time_cfg["nper"] = int(recharge_mm_day.size)

    solver_overrides = dict(dict(metadata.get("solver_overrides", {})).get(variant.solver_name, {}))
    resolved_runtime_max_iterations = (
        int(runtime_max_iterations)
        if runtime_max_iterations is not None
        else (
            int(solver_overrides["runtime_max_iterations"])
            if "runtime_max_iterations" in solver_overrides
            else None
        )
    )
    resolved_runtime_tol_residual_inf = (
        float(runtime_tol_residual_inf)
        if runtime_tol_residual_inf is not None
        else (
            float(solver_overrides["runtime_tol_residual_inf"])
            if "runtime_tol_residual_inf" in solver_overrides
            else None
        )
    )
    return (
        geometry_cfg,
        time_cfg,
        forcing_cfg,
        resolved_runtime_max_iterations,
        resolved_runtime_tol_residual_inf,
    )


def run_boussinesq_hillslope_overflow_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
    forcing_preset: str | None = None,
    forcing_scale: float = 1.0,
    east_head_m: float | None = None,
    initial_head_m: float | None = None,
    dt_days: float | None = None,
    runtime_max_iterations: int | None = None,
    runtime_tol_residual_inf: float | None = None,
) -> ValidationRunResult:
    """Run the transient hillslope pulse-overflow scenario for one solver flavor."""
    del timeout

    metadata = load_case_metadata(CASE_DIR)
    variant = resolve_solver_variant(solver)
    (
        geometry_cfg,
        time_cfg,
        forcing_cfg,
        resolved_runtime_max_iterations,
        resolved_runtime_tol_residual_inf,
    ) = _resolve_case_settings(
        metadata,
        variant=variant,
        forcing_preset=forcing_preset,
        forcing_scale=float(forcing_scale),
        east_head_m=east_head_m,
        initial_head_m=initial_head_m,
        dt_days=dt_days,
        runtime_max_iterations=runtime_max_iterations,
        runtime_tol_residual_inf=runtime_tol_residual_inf,
    )

    nx = int(geometry_cfg["nx"])
    ny = int(geometry_cfg["ny"])
    nper = int(time_cfg["nper"])
    dt_days = float(time_cfg["dt_days"])
    recharge_mm_day = np.asarray(forcing_cfg.get("recharge_mm_day", ()), dtype=float).reshape(-1)
    if recharge_mm_day.size != nper:
        raise ValueError(
            f"Expected {nper} recharge periods, got {recharge_mm_day.size} values."
        )

    out_path = resolve_validation_results_dir(
        test_file=caller_file,
        run_name=f"{CASE_ID}_{variant.solver_name}",
    )
    bundle_dir = write_uniform_strip_bundle(
        out_path / "mesh_bundle",
        nx=nx,
        ny=ny,
        length_x_m=float(geometry_cfg["length_x_m"]),
        width_y_m=float(geometry_cfg["width_y_m"]),
        z_top_m=lambda x_m: _topography_m(x_m, geometry_cfg=geometry_cfg),
        z_bottom_m=float(geometry_cfg["bottom_elevation_m"]),
        hydraulic_conductivity_m_s=float(geometry_cfg["hydraulic_conductivity_m_per_s"]),
        storage_coefficient=float(geometry_cfg["storage_coefficient"]),
    )
    simulations_folder = out_path / "results_simulations"
    dt_seconds = 86_400.0 * dt_days
    period_lengths_seconds = tuple(dt_seconds for _ in range(nper))

    flow_section: dict[str, object] = {
        "flow_regime": "transient",
        "ic": {"type": "custom", "value": float(geometry_cfg["initial_head_m"])},
        "active_sinks_sources": ["recharge"],
        "active_bc": ["east_side"],
        "sinks_sources": {
            "recharge": {
                "values": [mm_day_to_m_s(float(value)) for value in recharge_mm_day],
                "first_clim": str(forcing_cfg.get("first_clim", "first")),
            }
        },
        "bc": {
            "dirichlet": {
                "east_side": {"value": float(geometry_cfg["east_head_m"])},
            }
        },
        "surface_interaction_model": str(variant.surface_interaction_model),
    }
    if variant.runtime_backend is not None:
        flow_section["runtime_backend"] = str(variant.runtime_backend)
    if resolved_runtime_max_iterations is not None:
        flow_section["runtime_max_iterations"] = int(resolved_runtime_max_iterations)
    if resolved_runtime_tol_residual_inf is not None:
        flow_section["runtime_tol_residual_inf"] = float(resolved_runtime_tol_residual_inf)

    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(build_flow_config(flow_section, case_dir=CASE_DIR)),
            domain=None,
            time_grid=SimpleNamespace(
                period_lengths_seconds=period_lengths_seconds,
                window=None,
            ),
            workspace=SimpleNamespace(simulations_folder=simulations_folder),
        ),
    )
    run = ProcessRun(
        id=f"flow_validation::{variant.solver_name}",
        process_id="flow_validation",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(
            name=f"Hillslope overflow pulse ({variant.label})",
            description="Transient hillslope overflow stress case",
            runs=(run,),
        ),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model
    aggregate_triangle_history_to_structured_grids(
        model,
        nx=nx,
        ny=ny,
        export_initial_state=True,
    )

    model_ws = Path(model.full_path)
    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"
    return ValidationRunResult(
        case_dir=CASE_DIR,
        solver_name=variant.solver_name,
        out_path=out_path,
        model_ws=model_ws,
        postprocess_dir=postprocess_dir,
        particles_dir=particles_dir,
        run_returncode=0,
        run_stdout="",
        run_stderr="",
    )


__all__ = [
    "CASE_DIR",
    "CASE_ID",
    "DEFAULT_SOLVER",
    "SolverVariant",
    "_resolve_case_settings",
    "resolve_solver_variant",
    "run_boussinesq_hillslope_overflow_case",
]
