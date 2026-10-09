"""Shared Boussinesq runtime for Brutsaert recession validation strips."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.physics.flow import Flow
from hydromodpy.solver.boussinesq import Boussinesq, BoussinesqState
from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    load_catchment_mesh_bundle,
)
from validation_cases.analytical.transient.runtime_boussinesq_1d import (
    aggregate_triangle_history_to_structured_fields,
)
from validation_cases.shared.boussinesq_analytical_runtime import (
    boussinesq_variant_config_name,
    boussinesq_variant_flow_section,
)
from validation_cases.shared.boussinesq_uniform_strip import (
    build_flow_config,
    write_uniform_strip_bundle,
)
from validation_cases.shared.loaders import load_case_config, load_case_metadata
from validation_cases.shared.runtime import (
    ValidationRunResult,
    resolve_validation_results_dir,
    write_validation_fields_to_store,
)


def _mm_day_to_m_s(mm_day: float) -> float:
    return float(mm_day) * 1.0e-3 / 86400.0


def _east_outlet_discharge_m3_s(model, internal_edge_flux_m3_s: np.ndarray) -> float:
    if model.mesh is None:
        raise RuntimeError("Boussinesq mesh must exist before extracting outlet flux.")
    east_cells = np.asarray(
        model.mesh.boundary_cell_indices_for_side("east_side"),
        dtype=int,
    ).reshape(-1)
    if east_cells.size == 0:
        return 0.0
    prescribed_mask = np.zeros(model.mesh.n_cells, dtype=bool)
    prescribed_mask[east_cells] = True
    outward_flux_m3_s = 0.0
    edge_flux = np.asarray(internal_edge_flux_m3_s, dtype=float).reshape(-1)
    for edge_index in range(model.mesh.n_edges):
        cell_a = int(model.mesh.edge_cell_a[edge_index])
        cell_b = int(model.mesh.edge_cell_b[edge_index])
        if cell_a < 0 or cell_b < 0:
            continue
        a_prescribed = bool(prescribed_mask[cell_a])
        b_prescribed = bool(prescribed_mask[cell_b])
        if a_prescribed == b_prescribed:
            continue
        flux = float(edge_flux[edge_index])
        if a_prescribed:
            outward_flux_m3_s += -flux
        else:
            outward_flux_m3_s += flux
    return float(max(outward_flux_m3_s, 0.0))


def _case_steps_per_period(case_dir: Path) -> int:
    """Return the backward-Euler steps per period the case gives MODFLOW."""
    metadata = load_case_metadata(case_dir)
    config = load_case_config(case_dir, str(metadata["base_config"]))
    time_cfg = dict(config.get("simulation", {}).get("time", {}))
    return int(time_cfg.get("substeps_per_period", 1))


def run_boussinesq_brutsaert_recession_case(
    *,
    case_dir: Path,
    case_id: str,
    caller_file: str | Path,
    timeout: int,
    nx: int,
    ny: int,
    length_x_m: float,
    width_y_m: float,
    z_top_m: float,
    z_bottom_m: float,
    hydraulic_conductivity_m_s: float,
    storage_coefficient: float,
    east_head_m: float,
    steady_recharge_mm_day: float,
    nper: int,
    dt_seconds: float,
    acceptable_steady_residual_inf: float = 1.0e-6,
    public_solver_label: str = "boussinesq",
) -> ValidationRunResult:
    """Run one transient Brutsaert recession benchmark on one Boussinesq variant.

    The time grid carries the backward-Euler steps a period of the case, as a
    run with ``[simulation.time].substeps_per_period`` does.
    """
    del timeout
    solver_name = str(public_solver_label or "boussinesq")
    config_name = boussinesq_variant_config_name(solver_name)
    out_path = resolve_validation_results_dir(
        test_file=caller_file,
        run_name=f"{case_id}_{solver_name}",
    )
    bundle_dir = write_uniform_strip_bundle(
        out_path / "mesh_bundle",
        nx=int(nx),
        ny=int(ny),
        length_x_m=float(length_x_m),
        width_y_m=float(width_y_m),
        z_top_m=float(z_top_m),
        z_bottom_m=float(z_bottom_m),
        hydraulic_conductivity_m_s=float(hydraulic_conductivity_m_s),
        storage_coefficient=float(storage_coefficient),
    )
    bundle = load_catchment_mesh_bundle(bundle_dir)
    simulations_folder = out_path / "results_simulations"
    simulations_folder.mkdir(parents=True, exist_ok=True)

    steady_flow = Flow(
        build_flow_config(
            boussinesq_variant_flow_section(
                {
                    "flow_regime": "steady",
                    "ic": {"type": "custom", "value": float(east_head_m)},
                    "active_sinks_sources": ["recharge"],
                    "active_bc": ["east_side"],
                    "sinks_sources": {
                        "recharge": {
                            "values": _mm_day_to_m_s(steady_recharge_mm_day),
                            "first_clim": "mean",
                            "units": "m/s",
                        }
                    },
                    "bc": {
                        "east_side": {"value": float(east_head_m)},
                    },
                },
                flow_regime="steady",
                solver=solver_name,
            ),
            case_dir=case_dir,
            config_name=config_name,
        )
    )
    steady_model = Boussinesq(
        mesh_bundle=bundle,
        flow=steady_flow,
        domain=None,
        time_grid=None,
        model_folder=simulations_folder,
        model_name="flow_validation__boussinesq_steady",
    )
    steady_model.pre_processing()
    steady_success = bool(steady_model.processing(write_model=True, run_model=True))
    steady_residual = float(steady_model.runtime_summary.get("steady_residual_norm_inf", np.inf))
    if not steady_success and steady_residual > float(acceptable_steady_residual_inf):
        raise RuntimeError(
            "Brutsaert steady pre-run did not converge to an acceptable residual. "
            f"residual_inf={steady_residual:.6g}, "
            f"threshold={float(acceptable_steady_residual_inf):.6g}, "
            f"workspace={steady_model.full_path}"
        )
    if steady_model.state is None:
        raise RuntimeError("Brutsaert steady pre-run did not leave one valid solver state.")

    transient_flow = Flow(
        build_flow_config(
            boussinesq_variant_flow_section(
                {
                    "flow_regime": "transient",
                    # The time grid holds the steps; TS VI takes one per grid step.
                    "ts_vi_steps_per_period": 1,
                    "ic": {"type": "custom", "value": float(east_head_m)},
                    "active_bc": ["east_side"],
                    "bc": {
                        "east_side": {"value": float(east_head_m)},
                    },
                },
                flow_regime="transient",
                solver=solver_name,
            ),
            case_dir=case_dir,
            config_name=config_name,
        )
    )
    period_lengths_seconds = tuple(float(dt_seconds) for _ in range(int(nper)))
    transient_model = Boussinesq(
        mesh_bundle=bundle,
        flow=transient_flow,
        domain=None,
        time_grid=SimpleNamespace(
            period_lengths_seconds=period_lengths_seconds,
            window=None,
            # Same time steps as MODFLOW: the recession rate drops by a dt / 2.
            nstp_per_period=_case_steps_per_period(case_dir),
        ),
        model_folder=simulations_folder,
        model_name="flow_validation__boussinesq",
    )
    transient_model.pre_processing()
    transient_model.state = BoussinesqState.initial(
        head_m=np.asarray(steady_model.state.head_m, dtype=float).copy(),
        saturated_thickness_m=np.asarray(
            steady_model.state.saturated_thickness_m,
            dtype=float,
        ).copy(),
    )
    transient_success = bool(transient_model._run_transient_runtime())
    if not transient_success:
        raise RuntimeError(
            f"Brutsaert transient recession run failed on the {solver_name} variant. "
            f"workspace={transient_model.full_path}"
        )
    transient_model.has_numerical_solution = True
    transient_model.solve_stage = "solved"
    transient_model.post_processing()
    field_series = aggregate_triangle_history_to_structured_fields(
        transient_model,
        nx=int(nx),
        ny=int(ny),
    )

    initial_outlet_discharge_m3_s = _east_outlet_discharge_m3_s(
        steady_model,
        np.asarray(steady_model.state.internal_edge_flux_m3_s, dtype=float),
    )
    edge_flux_history = np.asarray(
        transient_model.state.internal_edge_flux_history_m3_s,
        dtype=float,
    )
    outlet_history_m3_s = np.asarray(
        [
            _east_outlet_discharge_m3_s(transient_model, edge_flux_by_edge)
            for edge_flux_by_edge in edge_flux_history
        ],
        dtype=float,
    )

    model_ws = Path(transient_model.full_path)
    postprocess_dir = model_ws / "_postprocess"
    postprocess_dir.mkdir(parents=True, exist_ok=True)
    discharge_series = {
        int(time_key): np.asarray([float(value)], dtype=float)
        for time_key, value in zip(
            range(1, int(outlet_history_m3_s[1:].size) + 1),
            np.asarray(outlet_history_m3_s[1:], dtype=float),
            strict=True,
        )
    }
    field_series["outlet_discharge_m3_s"] = discharge_series
    field_series["outlet_discharge_east_side_m3_s"] = dict(discharge_series)
    context_payload = {
        "initial_outlet_discharge_m3_s": float(initial_outlet_discharge_m3_s),
        "steady_residual_norm_inf": float(steady_residual),
        "acceptable_steady_residual_inf": float(acceptable_steady_residual_inf),
        "steady_runtime_backend": str(steady_model.runtime_summary.get("runtime_backend")),
        "steady_surface_interaction_model": str(steady_model.flow.config.surface_interaction_model),
        "transient_runtime_backend": str(transient_model.runtime_summary.get("runtime_backend")),
        "transient_time_steps_per_period": int(
            transient_model.runtime_summary.get("time_steps_per_period", 1)
        ),
        "transient_surface_interaction_model": str(
            transient_model.flow.config.surface_interaction_model
        ),
        "nx": int(nx),
        "ny": int(ny),
        "length_x_m": float(length_x_m),
        "width_y_m": float(width_y_m),
        "z_top_m": float(z_top_m),
        "z_bottom_m": float(z_bottom_m),
        "east_head_m": float(east_head_m),
        "steady_recharge_mm_day": float(steady_recharge_mm_day),
    }
    (postprocess_dir / "brutsaert_context.json").write_text(
        json.dumps(context_payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    particles_dir = postprocess_dir / "_particles"
    store, sim_id = write_validation_fields_to_store(
        out_path=out_path,
        fields=field_series,
        solver_name="boussinesq",
        flow_regime="transient",
    )
    return ValidationRunResult(
        case_dir=case_dir,
        solver_name=solver_name,
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


__all__ = ["run_boussinesq_brutsaert_recession_case"]
