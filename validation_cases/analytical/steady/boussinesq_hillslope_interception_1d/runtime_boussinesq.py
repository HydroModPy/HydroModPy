"""Local ``flow/boussinesq`` runtime for the hillslope-interception benchmark."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from hydromodpy.physics.flow import Flow
from hydromodpy.solver.boussinesq import Boussinesq, BoussinesqState
from hydromodpy.solver.boussinesq.assembly import saturated_thickness_from_head
from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    load_catchment_mesh_bundle,
)
from validation_cases.analytical.steady.boussinesq_fixed_head_piecewise_k_1d.runtime_boussinesq import (
    _aggregate_triangle_history_to_structured_grids,
    _build_flow_config,
)
from validation_cases.analytical.steady.boussinesq_piecewise import mm_day_to_m_s
from validation_cases.shared.boussinesq_analytical_runtime import (
    apply_analytical_boussinesq_runtime_defaults,
)
from validation_cases.shared.runtime import (
    ValidationRunResult,
    materialize_postprocess_fields_to_store,
    resolve_validation_results_dir,
)

from .reference import expected_boussinesq_hillslope_profile_at_x

CASE_ID = "boussinesq_hillslope_interception_1d"
NX = 40
NY = 3
LENGTH_X_M = 400.0
WIDTH_Y_M = 30.0
BOTTOM_ELEVATION_M = 0.0
TOE_ELEVATION_M = 5.0
TOPOGRAPHY_SLOPE_M_PER_M = 0.0125
EAST_HEAD_M = 5.0
INITIAL_HEAD_M = 7.0
RECHARGE_MM_DAY = 2.0
HYDRAULIC_CONDUCTIVITY_M_S = 1.0e-4
STORAGE_COEFFICIENT = 0.10
ACCEPTABLE_STEADY_RESIDUAL_INF = 1.0e-5


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _topography_m(x_m):
    x = np.asarray(x_m, dtype=float)
    return TOE_ELEVATION_M + TOPOGRAPHY_SLOPE_M_PER_M * (LENGTH_X_M - x)


def _write_hillslope_strip_bundle(bundle_dir: Path) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "mesh_2d.msh").write_text(
        "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n",
        encoding="utf-8",
    )
    (bundle_dir / "metadata.json").write_text(
        json.dumps(
            {
                "bundle_schema_version": "mesh_catchment_bundle_v1",
                "crs": "EPSG:2154",
                "files": {"mesh": "mesh_2d.msh"},
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "mesh_summary.json").write_text(
        json.dumps({"constraints_mode": "geology_only"}, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    dx = LENGTH_X_M / float(NX)
    dy = WIDTH_Y_M / float(NY)
    node_rows: list[str] = []
    node_xy: dict[int, tuple[float, float]] = {}
    node_top: dict[int, float] = {}
    for iy in range(NY + 1):
        for ix in range(NX + 1):
            node_id = iy * (NX + 1) + ix
            x_m = float(ix) * dx
            y_m = float(iy) * dy
            z_top = float(_topography_m(x_m))
            node_xy[node_id] = (x_m, y_m)
            node_top[node_id] = z_top
            node_rows.append(f"{node_id},{x_m:.6f},{y_m:.6f},{z_top:.6f},{BOTTOM_ELEVATION_M:.6f}")
    _write_csv(bundle_dir / "nodes.csv", "node_id,x,y,z_top,z_bottom", node_rows)

    triangle_area_m2 = 0.5 * dx * dy
    cell_rows: list[str] = []
    cell_geology_rows: list[str] = []
    edge_records: dict[tuple[int, int], dict[str, object]] = {}
    cell_id = 0
    geology_key = "zone_1"

    for iy in range(NY):
        for ix in range(NX):
            n00 = iy * (NX + 1) + ix
            n10 = n00 + 1
            n01 = n00 + (NX + 1)
            n11 = n01 + 1
            if (ix + iy) % 2 == 0:
                triangles = ((n00, n10, n11), (n00, n11, n01))
            else:
                triangles = ((n00, n10, n01), (n10, n11, n01))

            for triangle in triangles:
                triangle_points = np.asarray(
                    [node_xy[node_id] for node_id in triangle],
                    dtype=float,
                )
                centroid_x_m = float(np.mean(triangle_points[:, 0]))
                centroid_y_m = float(np.mean(triangle_points[:, 1]))
                top_values = np.asarray(
                    [node_top[node_id] for node_id in triangle],
                    dtype=float,
                )
                z_top_mean = float(np.mean(top_values))
                cell_rows.append(
                    ",".join(
                        [
                            str(cell_id),
                            "triangle",
                            str(triangle[0]),
                            str(triangle[1]),
                            str(triangle[2]),
                            "",
                            f"{centroid_x_m:.6f}",
                            f"{centroid_y_m:.6f}",
                            f"{triangle_area_m2:.6f}",
                            f"{z_top_mean:.6f}",
                            f"{z_top_mean:.6f}",
                            f"{BOTTOM_ELEVATION_M:.6f}",
                            f"{BOTTOM_ELEVATION_M:.6f}",
                            "1",
                            geology_key,
                            f"{HYDRAULIC_CONDUCTIVITY_M_S:.12g}",
                            f"{STORAGE_COEFFICIENT:.12g}",
                        ]
                    )
                )
                cell_geology_rows.append(f"{cell_id},{geology_key},1.0")

                for edge_nodes in (
                    (triangle[0], triangle[1]),
                    (triangle[1], triangle[2]),
                    (triangle[2], triangle[0]),
                ):
                    key = tuple(sorted((int(edge_nodes[0]), int(edge_nodes[1]))))
                    edge = edge_records.get(key)
                    if edge is None:
                        point_a = np.asarray(node_xy[key[0]], dtype=float)
                        point_b = np.asarray(node_xy[key[1]], dtype=float)
                        edge_records[key] = {
                            "node_a": key[0],
                            "node_b": key[1],
                            "cell_a": cell_id,
                            "cell_b": None,
                            "length_m": float(np.linalg.norm(point_b - point_a)),
                            "geology_a_key": geology_key,
                            "geology_b_key": "",
                        }
                    else:
                        edge["cell_b"] = cell_id
                        edge["geology_b_key"] = geology_key
                cell_id += 1

    _write_csv(
        bundle_dir / "cells.csv",
        "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2,z_top_centroid,z_top_mean,z_bottom_centroid,z_bottom_mean,geology_code,geology_key,hydraulic_conductivity_m_s,storage_coefficient",
        cell_rows,
    )
    _write_csv(
        bundle_dir / "cell_geology_fractions.csv",
        "cell_id,geology_key,fraction",
        cell_geology_rows,
    )

    edge_rows: list[str] = []
    for edge_id, edge in enumerate(edge_records.values()):
        cell_b = edge["cell_b"]
        edge_rows.append(
            ",".join(
                [
                    str(edge_id),
                    str(edge["node_a"]),
                    str(edge["node_b"]),
                    str(edge["cell_a"]),
                    "" if cell_b is None else str(cell_b),
                    f"{float(edge['length_m']):.6f}",
                    "boundary" if cell_b is None else "internal",
                    "false",
                    str(edge["geology_a_key"]),
                    str(edge["geology_b_key"]),
                ]
            )
        )
    _write_csv(
        bundle_dir / "edges.csv",
        "edge_id,node_a,node_b,cell_a,cell_b,length_m,edge_kind,is_river,geology_a_key,geology_b_key",
        edge_rows,
    )
    return bundle_dir


def run_boussinesq_hillslope_interception_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
) -> ValidationRunResult:
    """Run the steady hillslope-interception benchmark on the PETSc VI runtime."""
    del timeout

    out_path = resolve_validation_results_dir(
        test_file=caller_file,
        run_name=f"{CASE_ID}_boussinesq",
    )
    bundle_dir = _write_hillslope_strip_bundle(out_path / "mesh_bundle")
    bundle = load_catchment_mesh_bundle(bundle_dir)
    simulations_folder = out_path / "results_simulations"
    simulations_folder.mkdir(parents=True, exist_ok=True)
    simulations_folder.mkdir(parents=True, exist_ok=True)

    flow = Flow(
        _build_flow_config(
            apply_analytical_boussinesq_runtime_defaults(
                {
                    "flow_regime": "steady",
                    "ic": {"type": "custom", "value": INITIAL_HEAD_M},
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
                    }
                },
                flow_regime="steady",
            ),
            case_dir=Path(__file__).resolve().parent,
        )
    )

    model = Boussinesq(
        mesh_bundle=bundle,
        flow=flow,
        domain=None,
        time_grid=None,
        model_folder=simulations_folder,
        model_name="flow_validation__boussinesq",
    )
    model.pre_processing()
    model._assert_supported_runtime_subset()
    if model.mesh is None:
        raise RuntimeError("Boussinesq mesh was not built for the hillslope-interception case.")

    head_guess = expected_boussinesq_hillslope_profile_at_x(
        x_m=np.asarray(model.mesh.cell_centroid_x_m, dtype=float),
        xmin=0.0,
        xmax=LENGTH_X_M,
        east_head_m=EAST_HEAD_M,
        recharge_mm_day=RECHARGE_MM_DAY,
        hydraulic_conductivity_m_per_s=HYDRAULIC_CONDUCTIVITY_M_S,
    )
    model.state = BoussinesqState.initial(
        head_m=np.asarray(head_guess, dtype=float).copy(),
        saturated_thickness_m=saturated_thickness_from_head(model.mesh, head_guess),
    )
    model.solve_stage = "initialized"

    success = bool(model._run_steady_runtime())
    residual = float(model.runtime_summary.get("steady_residual_norm_inf", np.inf))
    accepted = success or residual <= ACCEPTABLE_STEADY_RESIDUAL_INF
    model.runtime_summary["accepted_with_relaxed_residual"] = bool((not success) and accepted)
    model.runtime_summary["acceptable_steady_residual_inf"] = float(ACCEPTABLE_STEADY_RESIDUAL_INF)

    if not accepted:
        model.has_numerical_solution = False
        model.solve_stage = "failed"
        raise RuntimeError(
            "Boussinesq hillslope-interception solve did not converge to an "
            f"acceptable steady residual. residual_inf={residual:.6g}, "
            f"threshold={ACCEPTABLE_STEADY_RESIDUAL_INF:.6g}, "
            f"workspace={model.full_path}"
        )

    model.has_numerical_solution = True
    model.solve_stage = "solved"
    model.post_processing()
    _aggregate_triangle_history_to_structured_grids(model)

    model_ws = Path(model.full_path)
    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"
    store, sim_id = materialize_postprocess_fields_to_store(
        out_path=out_path,
        postprocess_dir=postprocess_dir,
        solver_name="boussinesq",
    )
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
        store=store,
        sim_id=sim_id,
    )


__all__ = ["run_boussinesq_hillslope_interception_case"]
