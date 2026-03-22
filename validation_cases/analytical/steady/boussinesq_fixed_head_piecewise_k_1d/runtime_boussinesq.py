"""Local `flow/boussinesq` runtime for the fixed-head piecewise-K validation case."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

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


CASE_ID = "boussinesq_fixed_head_piecewise_k_1d"
NX = 40
NY = 3
LENGTH_X_M = 400.0
WIDTH_Y_M = 30.0
Z_TOP_M = 20.0
Z_BOTTOM_M = 0.0
WEST_HEAD_M = 10.0
EAST_HEAD_M = 5.0
X_ZONE_BREAKS_M = (120.0, 280.0)
HYDRAULIC_CONDUCTIVITY_M_S_BY_ZONE = (2.0e-4, 5.0e-5, 1.0e-4)
STORAGE_COEFFICIENT = 0.1


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


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


def _zone_index_for_x(x_m: float) -> int:
    for index, x_break in enumerate(X_ZONE_BREAKS_M):
        if float(x_m) < float(x_break):
            return index
    return len(X_ZONE_BREAKS_M)


def _write_piecewise_strip_bundle(bundle_dir: Path) -> Path:
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
        json.dumps({"constraints_mode": "geology_only"}, indent=2, ensure_ascii=True)
        + "\n",
        encoding="utf-8",
    )

    dx = LENGTH_X_M / float(NX)
    dy = WIDTH_Y_M / float(NY)
    node_rows: list[str] = []
    for iy in range(NY + 1):
        for ix in range(NX + 1):
            node_id = iy * (NX + 1) + ix
            node_rows.append(
                f"{node_id},{float(ix) * dx:.6f},{float(iy) * dy:.6f},{Z_TOP_M:.6f},{Z_BOTTOM_M:.6f}"
            )
    _write_csv(bundle_dir / "nodes.csv", "node_id,x,y,z_top,z_bottom", node_rows)

    node_xy = {
        iy * (NX + 1) + ix: (float(ix) * dx, float(iy) * dy)
        for iy in range(NY + 1)
        for ix in range(NX + 1)
    }
    triangle_area_m2 = 0.5 * dx * dy
    cell_rows: list[str] = []
    cell_geology_rows: list[str] = []
    edge_records: dict[tuple[int, int], dict[str, object]] = {}
    cell_id = 0

    for iy in range(NY):
        for ix in range(NX):
            n00 = iy * (NX + 1) + ix
            n10 = n00 + 1
            n01 = n00 + (NX + 1)
            n11 = n01 + 1
            for triangle in ((n00, n10, n11), (n00, n11, n01)):
                triangle_points = np.asarray([node_xy[node_id] for node_id in triangle], dtype=float)
                centroid_x_m = float(np.mean(triangle_points[:, 0]))
                centroid_y_m = float(np.mean(triangle_points[:, 1]))
                zone_index = _zone_index_for_x(centroid_x_m)
                geology_key = f"zone_{zone_index + 1}"
                conductivity = HYDRAULIC_CONDUCTIVITY_M_S_BY_ZONE[zone_index]
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
                            f"{Z_TOP_M:.6f}",
                            f"{Z_TOP_M:.6f}",
                            f"{Z_BOTTOM_M:.6f}",
                            f"{Z_BOTTOM_M:.6f}",
                            str(zone_index + 1),
                            geology_key,
                            f"{conductivity:.12g}",
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


def _aggregate_triangle_history_to_structured_grids(model) -> None:
    """Overwrite the default cell-vector postprocess with a regular profile grid."""
    if model.state is None or model.mesh is None:
        raise RuntimeError("Boussinesq validation case requires a solved model state.")

    head_history = np.asarray(model.state.head_history_m, dtype=float)
    if head_history.ndim == 1:
        head_history = head_history.reshape(1, -1)

    dx = (float(model.mesh.x_max_m) - float(model.mesh.x_min_m)) / float(NX)
    dy = (float(model.mesh.y_max_m) - float(model.mesh.y_min_m)) / float(NY)
    col_index = np.clip(
        np.floor((np.asarray(model.mesh.cell_centroid_x_m, dtype=float) - float(model.mesh.x_min_m)) / dx).astype(int),
        0,
        NX - 1,
    )
    row_index = np.clip(
        np.floor((np.asarray(model.mesh.cell_centroid_y_m, dtype=float) - float(model.mesh.y_min_m)) / dy).astype(int),
        0,
        NY - 1,
    )

    top_sum = np.zeros((NY, NX), dtype=float)
    counts = np.zeros((NY, NX), dtype=int)
    for cell_idx in range(model.mesh.n_cells):
        row = int(row_index[cell_idx])
        col = int(col_index[cell_idx])
        top_sum[row, col] += float(model.mesh.z_top_m[cell_idx])
        counts[row, col] += 1
    if np.any(counts == 0):
        raise AssertionError("Every structured validation bin must receive at least one triangle.")
    top_grid = top_sum / counts

    watertable_elevation: dict[int, np.ndarray] = {}
    watertable_depth: dict[int, np.ndarray] = {}
    for time_index, head_values in enumerate(head_history):
        head_sum = np.zeros((NY, NX), dtype=float)
        head_count = np.zeros((NY, NX), dtype=int)
        for cell_idx in range(model.mesh.n_cells):
            row = int(row_index[cell_idx])
            col = int(col_index[cell_idx])
            head_sum[row, col] += float(head_values[cell_idx])
            head_count[row, col] += 1
        if np.any(head_count == 0):
            raise AssertionError("Every structured validation bin must receive at least one triangle.")
        head_grid = head_sum / head_count
        watertable_elevation[int(time_index)] = head_grid
        watertable_depth[int(time_index)] = np.maximum(top_grid - head_grid, 0.0)

    postprocess_dir = Path(model.full_path) / "_postprocess"
    np.save(postprocess_dir / "watertable_elevation.npy", watertable_elevation)
    np.save(postprocess_dir / "watertable_depth.npy", watertable_depth)


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
