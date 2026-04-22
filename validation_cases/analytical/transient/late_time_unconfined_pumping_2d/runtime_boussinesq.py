"""Local ``flow/boussinesq`` runtime for the late-time pumping 2D validation case."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.physics.flow import Flow
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.simulation.adapters.flow.boussinesq import BoussinesqFlowAdapter
from hydromodpy.simulation.planning.plan import (
    ProcessRun,
    RunContext,
    SimulationPlan,
)
from validation_cases.shared import load_case_metadata
from validation_cases.shared.loaders import merge_case_flow_section
from validation_cases.shared.runtime import (
    ValidationRunResult,
    resolve_validation_results_dir,
)

CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "late_time_unconfined_pumping_2d"
MESH_NX = 31
MESH_NY = 31


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _build_flow_config(flow_section: dict[str, object]) -> FlowConfig:
    merged_flow = merge_case_flow_section(
        CASE_DIR, flow_section, config_name="config_boussinesq.toml"
    )
    return FlowConfig.from_toml_section(merged_flow, base_dir=CASE_DIR)


def _write_uniform_square_bundle(
    bundle_dir: Path,
    *,
    nx: int,
    ny: int,
    xmin: float,
    xmax: float,
    ymin: float,
    ymax: float,
    z_top_m: float,
    z_bottom_m: float,
    hydraulic_conductivity_m_s: float,
    storage_coefficient: float,
) -> Path:
    """Write one deterministic triangular square bundle for transient 2D validation."""
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

    dx = (float(xmax) - float(xmin)) / float(nx)
    dy = (float(ymax) - float(ymin)) / float(ny)

    node_rows: list[str] = []
    node_xy: dict[int, tuple[float, float]] = {}
    for row in range(int(ny) + 1):
        y_m = float(ymin) + float(row) * dy
        for col in range(int(nx) + 1):
            x_m = float(xmin) + float(col) * dx
            node_id = row * (int(nx) + 1) + col
            node_xy[node_id] = (x_m, y_m)
            node_rows.append(
                f"{node_id},{x_m:.6f},{y_m:.6f},{float(z_top_m):.6f},{float(z_bottom_m):.6f}"
            )
    _write_csv(bundle_dir / "nodes.csv", "node_id,x,y,z_top,z_bottom", node_rows)

    cell_rows: list[str] = []
    geology_rows: list[str] = []
    edge_records: dict[tuple[int, int], dict[str, object]] = {}
    cell_id = 0
    triangle_area_m2 = 0.5 * dx * dy

    def _append_triangle(node_ids: tuple[int, int, int]) -> None:
        nonlocal cell_id
        triangle_points = np.asarray([node_xy[node_id] for node_id in node_ids], dtype=float)
        centroid_x_m = float(np.mean(triangle_points[:, 0]))
        centroid_y_m = float(np.mean(triangle_points[:, 1]))
        cell_rows.append(
            ",".join(
                [
                    str(cell_id),
                    "triangle",
                    str(node_ids[0]),
                    str(node_ids[1]),
                    str(node_ids[2]),
                    "",
                    f"{centroid_x_m:.6f}",
                    f"{centroid_y_m:.6f}",
                    f"{triangle_area_m2:.6f}",
                    f"{float(z_top_m):.6f}",
                    f"{float(z_top_m):.6f}",
                    f"{float(z_bottom_m):.6f}",
                    f"{float(z_bottom_m):.6f}",
                    "1",
                    "zone_1",
                    f"{float(hydraulic_conductivity_m_s):.12g}",
                    f"{float(storage_coefficient):.12g}",
                ]
            )
        )
        geology_rows.append(f"{cell_id},zone_1,1.0")

        for edge_nodes in (
            (node_ids[0], node_ids[1]),
            (node_ids[1], node_ids[2]),
            (node_ids[2], node_ids[0]),
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
                    "geology_a_key": "zone_1",
                    "geology_b_key": "",
                }
            else:
                edge["cell_b"] = cell_id
                edge["geology_b_key"] = "zone_1"
        cell_id += 1

    for row in range(int(ny)):
        for col in range(int(nx)):
            n00 = row * (int(nx) + 1) + col
            n10 = n00 + 1
            n01 = n00 + (int(nx) + 1)
            n11 = n01 + 1
            if (row + col) % 2 == 0:
                triangles = ((n00, n10, n11), (n00, n11, n01))
            else:
                triangles = ((n00, n10, n01), (n10, n11, n01))
            for triangle in triangles:
                _append_triangle(triangle)

    _write_csv(
        bundle_dir / "cells.csv",
        "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2,z_top_centroid,z_top_mean,z_bottom_centroid,z_bottom_mean,geology_code,geology_key,hydraulic_conductivity_m_s,storage_coefficient",
        cell_rows,
    )
    _write_csv(
        bundle_dir / "cell_geology_fractions.csv",
        "cell_id,geology_key,fraction",
        geology_rows,
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


def _project_head_history_to_reference_grid(
    model,
    *,
    xmin: float,
    xmax: float,
    ymin: float,
    ymax: float,
    nx: int,
    ny: int,
    z_top_m: float,
) -> None:
    """Overwrite the default cell-vector outputs with regular 2D head rasters."""
    if model.state is None or model.mesh is None:
        raise RuntimeError("Boussinesq validation case requires a solved model state.")

    raw_head_history = np.asarray(model.state.head_history_m, dtype=float)
    if raw_head_history.ndim == 1:
        head_history = raw_head_history.reshape(1, -1)
    else:
        head_history = raw_head_history
    if head_history.shape[0] > 1:
        head_history = head_history[1:, :]

    x_centers = float(xmin) + (np.arange(int(nx), dtype=float) + 0.5) * (
        (float(xmax) - float(xmin)) / float(nx)
    )
    y_centers = float(ymin) + (np.arange(int(ny), dtype=float) + 0.5) * (
        (float(ymax) - float(ymin)) / float(ny)
    )
    xx, yy = np.meshgrid(x_centers, y_centers)

    projection_indices = np.empty((int(ny), int(nx)), dtype=int)
    for row in range(int(ny)):
        for col in range(int(nx)):
            projection_indices[row, col] = model.mesh.locate_cell_index_for_point(
                float(xx[row, col]),
                float(yy[row, col]),
                allow_nearest=True,
            )

    watertable_elevation: dict[int, np.ndarray] = {}
    watertable_depth: dict[int, np.ndarray] = {}
    for time_index, head_values in enumerate(head_history):
        head_grid = np.asarray(head_values, dtype=float)[projection_indices]
        watertable_elevation[int(time_index)] = head_grid
        watertable_depth[int(time_index)] = np.maximum(float(z_top_m) - head_grid, 0.0)

    postprocess_dir = Path(model.full_path) / "_postprocess"
    postprocess_dir.mkdir(parents=True, exist_ok=True)
    np.save(postprocess_dir / "watertable_elevation.npy", watertable_elevation)
    np.save(postprocess_dir / "watertable_depth.npy", watertable_depth)


def run_boussinesq_late_time_unconfined_pumping_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
) -> ValidationRunResult:
    """Run the transient 2D pumping case through the local sparse Boussinesq adapter."""
    del timeout

    metadata = load_case_metadata(CASE_DIR)
    reference_cfg = dict(metadata.get("reference", {}))
    output_cfg = dict(metadata.get("output", {}))
    time_cfg = dict(metadata.get("time", {}))

    xmin = float(reference_cfg["xmin"])
    xmax = float(reference_cfg["xmax"])
    ymin = float(reference_cfg["ymin"])
    ymax = float(reference_cfg["ymax"])
    base_head_m = float(reference_cfg["base_head_m"])
    reference_thickness_m = float(reference_cfg["reference_saturated_thickness_m"])
    z_top_m = base_head_m + (reference_thickness_m / 3.0)
    z_bottom_m = z_top_m - 40.0
    nper = int(output_cfg["expected_periods"])
    dt_seconds = float(time_cfg["dt_seconds"])
    simulations_folder_name = str(
        metadata.get("workspace", {}).get("results_folder_name", "results_simulations")
    )

    out_path = resolve_validation_results_dir(
        test_file=caller_file,
        run_name=f"{CASE_ID}_boussinesq",
    )
    bundle_dir = _write_uniform_square_bundle(
        out_path / "mesh_bundle",
        nx=MESH_NX,
        ny=MESH_NY,
        xmin=xmin,
        xmax=xmax,
        ymin=ymin,
        ymax=ymax,
        z_top_m=z_top_m,
        z_bottom_m=z_bottom_m,
        hydraulic_conductivity_m_s=float(reference_cfg["hydraulic_conductivity_m_per_s"]),
        storage_coefficient=float(reference_cfg["specific_yield"]),
    )
    simulations_folder = out_path / simulations_folder_name
    period_lengths_seconds = tuple(float(dt_seconds) for _ in range(int(nper)))

    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(
                _build_flow_config(
                    {
                        "flow_regime": "transient",
                        "ic": {"type": "custom", "value": base_head_m},
                        "active_sinks_sources": ["wells"],
                        "active_bc": ["west_side", "east_side", "north_side", "south_side"],
                        "sinks_sources": {
                            "wells": {
                                "P1": {
                                    "location_mode": "absolute_xy",
                                    "x": float(reference_cfg["center_x_m"]),
                                    "y": float(reference_cfg["center_y_m"]),
                                    "flux": -float(reference_cfg["pumping_rate_m3_day"]),
                                    "units": "m3/day",
                                }
                            }
                        },
                        "bc": {
                            "dirichlet": {
                                "west_side": {"value": base_head_m},
                                "east_side": {"value": base_head_m},
                                "north_side": {"value": base_head_m},
                                "south_side": {"value": base_head_m},
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
            name="Boussinesq late-time pumping validation",
            description="Transient square-domain pumping with side Dirichlet boundaries",
            runs=(run,),
        ),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model
    _project_head_history_to_reference_grid(
        model,
        xmin=xmin,
        xmax=xmax,
        ymin=ymin,
        ymax=ymax,
        nx=int(output_cfg["expected_spatial_shape"][1]),
        ny=int(output_cfg["expected_spatial_shape"][0]),
        z_top_m=z_top_m,
    )

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


__all__ = ["run_boussinesq_late_time_unconfined_pumping_case"]
