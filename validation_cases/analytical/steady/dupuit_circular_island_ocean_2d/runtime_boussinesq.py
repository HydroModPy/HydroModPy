"""Local `flow/boussinesq` runtime for the steady circular-island ocean case."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hydromodpy.physics.flow import Flow
from hydromodpy.simulation.planning.plan import (
    ProcessRun,
    RunContext,
    SimulationPlan,
)
from hydromodpy.solver.boussinesq.adapters.flow import BoussinesqFlowAdapter
from validation_cases.analytical.steady.boussinesq_circular_island_piecewise_k_2d import (
    runtime_boussinesq as circular_runtime,
)
from validation_cases.analytical.steady.boussinesq_fixed_head_piecewise_k_1d.runtime_boussinesq import (
    _build_flow_config,
)
from validation_cases.shared import load_case_metadata
from validation_cases.shared.runtime import (
    ValidationRunResult,
    resolve_validation_results_dir,
)

CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "dupuit_circular_island_ocean_2d"
DUPUIT_ISLAND_N_SECTORS = 18
DUPUIT_ISLAND_SUPPORT_RADII_M = (25.0, 50.0, 70.0, 100.0, 140.0, 180.0, 200.0)


def _build_uniform_reference_cfg(case_metadata: dict) -> dict:
    """Adapt the Dupuit metadata to the ring-based bundle writer used by the 2D Boussinesq runtime."""
    reference_cfg = dict(case_metadata.get("reference", {}))
    hydraulic_conductivity_m_s = float(reference_cfg["hydraulic_conductivity_m_per_s"])
    reference_cfg["ring_radius_breaks_m"] = []
    reference_cfg["hydraulic_conductivity_m_per_s_by_ring"] = [hydraulic_conductivity_m_s]
    return reference_cfg


def run_boussinesq_dupuit_circular_island_ocean_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
) -> ValidationRunResult:
    """Run the steady circular-island ocean case through the local `flow/boussinesq` adapter."""
    del timeout

    case_metadata = load_case_metadata(CASE_DIR)
    reference_cfg = _build_uniform_reference_cfg(case_metadata)
    out_path = resolve_validation_results_dir(
        test_file=caller_file,
        run_name=f"{CASE_ID}_boussinesq",
    )
    recharge_rate_m_s = float(reference_cfg["recharge_mm_day"]) * 1.0e-3 / 86400.0
    previous_sectors = int(circular_runtime.N_SECTORS)
    previous_radii = tuple(float(value) for value in circular_runtime.LAND_SUPPORT_RADII_M)
    circular_runtime.N_SECTORS = DUPUIT_ISLAND_N_SECTORS
    circular_runtime.LAND_SUPPORT_RADII_M = DUPUIT_ISLAND_SUPPORT_RADII_M
    try:
        bundle_dir, ocean_cell_specs = circular_runtime._write_circular_island_bundle(
            out_path / "mesh_bundle",
            reference_cfg,
        )
    finally:
        circular_runtime.N_SECTORS = previous_sectors
        circular_runtime.LAND_SUPPORT_RADII_M = previous_radii
    simulations_folder = out_path / "results_simulations"
    simulations_folder.mkdir(parents=True, exist_ok=True)
    wells_payload = {
        f"ocean_comp_{index:03d}": {
            "location_mode": "absolute_xy",
            "layer": 0,
            "x": float(x_m),
            "y": float(y_m),
            "flux": -recharge_rate_m_s * float(area_m2),
        }
        for index, (x_m, y_m, area_m2) in enumerate(ocean_cell_specs)
    }

    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(
                _build_flow_config(
                    {
                        "flow_regime": "steady",
                        # This medium-size island mesh still converges more
                        # robustly on the dense local Newton path than on the
                        # sparse validation backend.
                        "runtime_backend": "local",
                        "ic": {"type": "custom", "value": 1.0},
                        "active_sinks_sources": ["recharge", "wells"],
                        "active_bc": ["ocean"],
                        "sinks_sources": {
                            "recharge": {
                                "values": recharge_rate_m_s,
                                "first_clim": "mean",
                                "units": "m/s",
                            },
                            "wells": wells_payload,
                        },
                        "bc": {
                            "dirichlet": {
                                "ocean": {"value": float(reference_cfg["sea_level_m"])},
                            }
                        },
                    },
                    case_dir=CASE_DIR,
                )
            ),
            domain=None,
            time_grid=None,
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
            name="Boussinesq circular-island ocean validation",
            description="Steady circular island with one uniform conductivity and one ocean boundary",
            runs=(run,),
        ),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model
    circular_runtime._aggregate_triangle_history_to_reference_grid(model, reference_cfg)

    model_ws = Path(model.full_path)
    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"
    return ValidationRunResult(
        case_dir=CASE_DIR,
        solver_name="boussinesq",
        out_path=out_path,
        model_ws=model_ws,
        postprocess_dir=postprocess_dir,
        particles_dir=particles_dir,
        run_returncode=0,
        run_stdout="",
        run_stderr="",
    )


__all__ = ["run_boussinesq_dupuit_circular_island_ocean_case"]
