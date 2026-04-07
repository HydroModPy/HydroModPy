"""Shared local Boussinesq runtime for Brutsaert recession validation strips."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.process.flow import Flow
from hydromodpy.solver.boussinesq import Boussinesq, BoussinesqState
from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    load_catchment_mesh_bundle,
)
from validation_cases.analytical.transient.runtime_boussinesq_1d import (
    aggregate_triangle_history_to_structured_grids,
)
from validation_cases.shared.boussinesq_uniform_strip import (
    build_flow_config,
    write_uniform_strip_bundle,
)
from validation_cases.shared.runtime import (
    ValidationRunResult,
    resolve_validation_results_dir,
)


def _mm_day_to_m_s(mm_day: float) -> float:
    return float(mm_day) * 1.0e-3 / 86400.0


def _east_outlet_discharge_m3_s(model, edge_flux_by_edge: np.ndarray) -> float:
    if model.mesh is None:
        raise RuntimeError("Boussinesq mesh must exist before extracting outlet flux.")
    east_edges = model.mesh.boundary_edge_indices_for_side("east_side")
    edge_flux = np.asarray(edge_flux_by_edge, dtype=float)
    return float(np.sum(np.maximum(edge_flux[east_edges], 0.0)))


def _save_scalar_series_npy(
    *,
    postprocess_dir: Path,
    observable_name: str,
    values: np.ndarray,
) -> None:
    payload = {
        int(index): np.asarray([float(value)], dtype=float)
        for index, value in enumerate(np.asarray(values, dtype=float).tolist())
    }
    np.save(postprocess_dir / f"{observable_name}.npy", payload)


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
) -> ValidationRunResult:
    """Run one transient Brutsaert recession benchmark on the local Boussinesq backend."""
    del timeout
    # Keep small validation strips on the historical dense backend, but switch
    # larger aligned strips to the sparse Newton path before the 256-cell limit.
    runtime_backend = "scipy_sparse" if int(nx) * int(ny) > 256 else "local"

    out_path = resolve_validation_results_dir(
        test_file=caller_file,
        run_name=f"{case_id}_boussinesq",
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
            {
                "flow_regime": "steady",
                "runtime_backend": runtime_backend,
                "ic": {"type": "custom", "value": float(east_head_m)},
                "active_sinks_sources": ["recharge"],
                "active_bc": ["east_side"],
                "sinks_sources": {
                    "recharge": {
                        "values": _mm_day_to_m_s(steady_recharge_mm_day),
                        "first_clim": "mean",
                    }
                },
                "bc": {
                    "dirichlet": {
                        "east_side": {"value": float(east_head_m)},
                    }
                },
            },
            case_dir=case_dir,
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
    steady_residual = float(
        steady_model.runtime_summary.get("steady_residual_norm_inf", np.inf)
    )
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
            {
                "flow_regime": "transient",
                "runtime_backend": runtime_backend,
                "ic": {"type": "custom", "value": float(east_head_m)},
                "active_bc": ["east_side"],
                "bc": {
                    "dirichlet": {
                        "east_side": {"value": float(east_head_m)},
                    }
                },
            },
            case_dir=case_dir,
        )
    )
    transient_model = Boussinesq(
        mesh_bundle=bundle,
        flow=transient_flow,
        domain=None,
        time_grid=SimpleNamespace(
            period_lengths_seconds=tuple(float(dt_seconds) for _ in range(int(nper))),
            window=None,
        ),
        model_folder=simulations_folder,
        model_name="flow_validation__boussinesq",
    )
    transient_model.pre_processing()
    transient_model.state = BoussinesqState(
        head_m=np.asarray(steady_model.state.head_m, dtype=float).copy(),
        saturated_thickness_m=np.asarray(
            steady_model.state.saturated_thickness_m,
            dtype=float,
        ).copy(),
    )
    transient_success = bool(transient_model._run_transient_runtime())
    if not transient_success:
        raise RuntimeError(
            "Brutsaert transient recession run failed on the local Boussinesq backend. "
            f"workspace={transient_model.full_path}"
        )
    transient_model.has_numerical_solution = True
    transient_model.solve_stage = "solved"
    transient_model.post_processing()
    aggregate_triangle_history_to_structured_grids(
        transient_model,
        nx=int(nx),
        ny=int(ny),
        export_initial_state=False,
    )

    initial_outlet_discharge_m3_s = _east_outlet_discharge_m3_s(
        steady_model,
        np.asarray(steady_model.state.imposed_head_edge_flux_m3_s, dtype=float),
    )
    edge_flux_history = np.asarray(
        transient_model.state.imposed_head_edge_flux_history_m3_s,
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
    _save_scalar_series_npy(
        postprocess_dir=postprocess_dir,
        observable_name="outlet_discharge_m3_s",
        values=outlet_history_m3_s[1:],
    )
    _save_scalar_series_npy(
        postprocess_dir=postprocess_dir,
        observable_name="outlet_discharge_east_side_m3_s",
        values=outlet_history_m3_s[1:],
    )
    context_payload = {
        "initial_outlet_discharge_m3_s": float(initial_outlet_discharge_m3_s),
        "steady_residual_norm_inf": float(steady_residual),
        "acceptable_steady_residual_inf": float(acceptable_steady_residual_inf),
        "nx": int(nx),
        "ny": int(ny),
        "length_x_m": float(length_x_m),
        "width_y_m": float(width_y_m),
        "z_top_m": float(z_top_m),
        "z_bottom_m": float(z_bottom_m),
        "east_head_m": float(east_head_m),
        "steady_recharge_mm_day": float(steady_recharge_mm_day),
        "runtime_backend": runtime_backend,
    }
    (postprocess_dir / "brutsaert_context.json").write_text(
        json.dumps(context_payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    particles_dir = postprocess_dir / "_particles"
    return ValidationRunResult(
        case_dir=case_dir,
        solver_name="boussinesq",
        out_path=out_path,
        model_ws=model_ws,
        postprocess_dir=postprocess_dir,
        particles_dir=particles_dir,
        run_returncode=0,
        run_stdout="",
        run_stderr="",
    )


__all__ = ["run_boussinesq_brutsaert_recession_case"]
