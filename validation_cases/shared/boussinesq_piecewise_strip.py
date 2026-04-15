"""Shared helpers for steady Boussinesq piecewise-strip validation cases."""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

import numpy as np

from validation_cases.shared.runtime import (
    REPO_ROOT,
    ValidationRunResult,
    resolve_model_workspace,
    resolve_validation_results_dir,
    run_example_script,
)


PIECEWISE_STRIP_NX = 40
PIECEWISE_STRIP_NY = 3
PIECEWISE_STRIP_LENGTH_X_M = 400.0
PIECEWISE_STRIP_WIDTH_Y_M = 30.0
PIECEWISE_STRIP_Z_TOP_M = 20.0
PIECEWISE_STRIP_Z_BOTTOM_M = 0.0
PIECEWISE_STRIP_X_ZONE_BREAKS_M = (120.0, 280.0)
PIECEWISE_STRIP_HYDRAULIC_CONDUCTIVITY_M_S_BY_ZONE = (2.0e-4, 5.0e-5, 1.0e-4)
PIECEWISE_STRIP_STORAGE_COEFFICIENT = 0.1


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _zone_index_for_x(x_m: float) -> int:
    for index, x_break in enumerate(PIECEWISE_STRIP_X_ZONE_BREAKS_M):
        if float(x_m) < float(x_break):
            return index
    return len(PIECEWISE_STRIP_X_ZONE_BREAKS_M)


def _write_piecewise_strip_mesh(mesh_path: Path) -> Path:
    """Write one deterministic Gmsh 2.2 ASCII triangle mesh for the strip."""
    dx = PIECEWISE_STRIP_LENGTH_X_M / float(PIECEWISE_STRIP_NX)
    dy = PIECEWISE_STRIP_WIDTH_Y_M / float(PIECEWISE_STRIP_NY)

    lines = [
        "$MeshFormat",
        "2.2 0 8",
        "$EndMeshFormat",
        "$Nodes",
        str((PIECEWISE_STRIP_NX + 1) * (PIECEWISE_STRIP_NY + 1)),
    ]
    for iy in range(PIECEWISE_STRIP_NY + 1):
        for ix in range(PIECEWISE_STRIP_NX + 1):
            node_id = iy * (PIECEWISE_STRIP_NX + 1) + ix + 1
            lines.append(
                f"{node_id} {float(ix) * dx:.6f} {float(iy) * dy:.6f} 0.0"
            )
    lines.extend(
        [
            "$EndNodes",
            "$Elements",
            str(PIECEWISE_STRIP_NX * PIECEWISE_STRIP_NY * 2),
        ]
    )

    element_id = 1
    for iy in range(PIECEWISE_STRIP_NY):
        for ix in range(PIECEWISE_STRIP_NX):
            n00 = iy * (PIECEWISE_STRIP_NX + 1) + ix
            n10 = n00 + 1
            n01 = n00 + (PIECEWISE_STRIP_NX + 1)
            n11 = n01 + 1
            for triangle in ((n00, n10, n11), (n00, n11, n01)):
                lines.append(
                    f"{element_id} 2 0 {triangle[0] + 1} {triangle[1] + 1} {triangle[2] + 1}"
                )
                element_id += 1
    lines.extend(["$EndElements", ""])
    mesh_path.write_text("\n".join(lines), encoding="utf-8")
    return mesh_path


def write_piecewise_strip_bundle(bundle_dir: Path) -> Path:
    """Write one deterministic triangular strip bundle with a valid `.msh`."""
    bundle_dir.mkdir(parents=True, exist_ok=True)
    mesh_path = _write_piecewise_strip_mesh(bundle_dir / "mesh_2d.msh")
    (bundle_dir / "metadata.json").write_text(
        json.dumps(
            {
                "bundle_schema_version": "mesh_catchment_bundle_v1",
                "crs": "EPSG:2154",
                "files": {
                    "mesh": "mesh_2d.msh",
                    "nodes": "nodes.csv",
                    "cells": "cells.csv",
                    "edges": "edges.csv",
                    "cell_geology_fractions": "cell_geology_fractions.csv",
                    "metadata": "metadata.json",
                    "mesh_summary": "mesh_summary.json",
                },
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

    dx = PIECEWISE_STRIP_LENGTH_X_M / float(PIECEWISE_STRIP_NX)
    dy = PIECEWISE_STRIP_WIDTH_Y_M / float(PIECEWISE_STRIP_NY)
    node_rows: list[str] = []
    for iy in range(PIECEWISE_STRIP_NY + 1):
        for ix in range(PIECEWISE_STRIP_NX + 1):
            node_id = iy * (PIECEWISE_STRIP_NX + 1) + ix
            node_rows.append(
                f"{node_id},{float(ix) * dx:.6f},{float(iy) * dy:.6f},{PIECEWISE_STRIP_Z_TOP_M:.6f},{PIECEWISE_STRIP_Z_BOTTOM_M:.6f}"
            )
    _write_csv(bundle_dir / "nodes.csv", "node_id,x,y,z_top,z_bottom", node_rows)

    node_xy = {
        iy * (PIECEWISE_STRIP_NX + 1) + ix: (float(ix) * dx, float(iy) * dy)
        for iy in range(PIECEWISE_STRIP_NY + 1)
        for ix in range(PIECEWISE_STRIP_NX + 1)
    }
    triangle_area_m2 = 0.5 * dx * dy
    cell_rows: list[str] = []
    cell_geology_rows: list[str] = []
    edge_records: dict[tuple[int, int], dict[str, object]] = {}
    cell_id = 0

    for iy in range(PIECEWISE_STRIP_NY):
        for ix in range(PIECEWISE_STRIP_NX):
            n00 = iy * (PIECEWISE_STRIP_NX + 1) + ix
            n10 = n00 + 1
            n01 = n00 + (PIECEWISE_STRIP_NX + 1)
            n11 = n01 + 1
            for triangle in ((n00, n10, n11), (n00, n11, n01)):
                triangle_points = np.asarray(
                    [node_xy[node_id] for node_id in triangle],
                    dtype=float,
                )
                centroid_x_m = float(np.mean(triangle_points[:, 0]))
                centroid_y_m = float(np.mean(triangle_points[:, 1]))
                zone_index = _zone_index_for_x(centroid_x_m)
                geology_key = f"zone_{zone_index + 1}"
                conductivity = PIECEWISE_STRIP_HYDRAULIC_CONDUCTIVITY_M_S_BY_ZONE[
                    zone_index
                ]
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
                            f"{PIECEWISE_STRIP_Z_TOP_M:.6f}",
                            f"{PIECEWISE_STRIP_Z_TOP_M:.6f}",
                            f"{PIECEWISE_STRIP_Z_BOTTOM_M:.6f}",
                            f"{PIECEWISE_STRIP_Z_BOTTOM_M:.6f}",
                            str(zone_index + 1),
                            geology_key,
                            f"{conductivity:.12g}",
                            f"{PIECEWISE_STRIP_STORAGE_COEFFICIENT:.12g}",
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
    if not mesh_path.exists():
        raise AssertionError(f"Piecewise-strip mesh was not written: {mesh_path}")
    return bundle_dir


def _structured_bin_indices(
    *,
    cell_centroid_x_m: np.ndarray,
    cell_centroid_y_m: np.ndarray,
    x_min_m: float,
    x_max_m: float,
    y_min_m: float,
    y_max_m: float,
    nx: int,
    ny: int,
) -> tuple[np.ndarray, np.ndarray]:
    dx = (float(x_max_m) - float(x_min_m)) / float(nx)
    dy = (float(y_max_m) - float(y_min_m)) / float(ny)
    col_index = np.clip(
        np.floor((np.asarray(cell_centroid_x_m, dtype=float) - float(x_min_m)) / dx).astype(int),
        0,
        int(nx) - 1,
    )
    row_index = np.clip(
        np.floor((np.asarray(cell_centroid_y_m, dtype=float) - float(y_min_m)) / dy).astype(int),
        0,
        int(ny) - 1,
    )
    return row_index, col_index


def _mean_field_to_grid(
    values: np.ndarray,
    *,
    row_index: np.ndarray,
    col_index: np.ndarray,
    nx: int,
    ny: int,
) -> np.ndarray:
    total = np.zeros((int(ny), int(nx)), dtype=float)
    counts = np.zeros((int(ny), int(nx)), dtype=int)
    for cell_idx, value in enumerate(np.asarray(values, dtype=float)):
        row = int(row_index[cell_idx])
        col = int(col_index[cell_idx])
        total[row, col] += float(value)
        counts[row, col] += 1
    if np.any(counts == 0):
        raise AssertionError("Every structured validation bin must receive at least one triangle.")
    return total / counts


def _aggregate_triangle_history(
    *,
    head_history: np.ndarray,
    time_keys: list[int],
    cell_centroid_x_m: np.ndarray,
    cell_centroid_y_m: np.ndarray,
    z_top_m: np.ndarray,
    x_min_m: float,
    x_max_m: float,
    y_min_m: float,
    y_max_m: float,
    nx: int,
    ny: int,
) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray]]:
    row_index, col_index = _structured_bin_indices(
        cell_centroid_x_m=cell_centroid_x_m,
        cell_centroid_y_m=cell_centroid_y_m,
        x_min_m=x_min_m,
        x_max_m=x_max_m,
        y_min_m=y_min_m,
        y_max_m=y_max_m,
        nx=int(nx),
        ny=int(ny),
    )
    top_grid = _mean_field_to_grid(
        z_top_m,
        row_index=row_index,
        col_index=col_index,
        nx=int(nx),
        ny=int(ny),
    )

    watertable_elevation: dict[int, np.ndarray] = {}
    watertable_depth: dict[int, np.ndarray] = {}
    for time_index, key in enumerate(time_keys):
        head_grid = _mean_field_to_grid(
            np.asarray(head_history[time_index], dtype=float),
            row_index=row_index,
            col_index=col_index,
            nx=int(nx),
            ny=int(ny),
        )
        watertable_elevation[int(key)] = head_grid
        watertable_depth[int(key)] = np.maximum(top_grid - head_grid, 0.0)
    return watertable_elevation, watertable_depth


def aggregate_triangle_history_to_structured_grids(
    model,
    *,
    nx: int = PIECEWISE_STRIP_NX,
    ny: int = PIECEWISE_STRIP_NY,
    export_initial_state: bool = True,
) -> None:
    """Overwrite vector postprocess outputs with one regular structured grid."""
    if model.state is None or model.mesh is None:
        raise RuntimeError("Boussinesq validation case requires a solved model state.")

    head_history = np.asarray(model.state.head_history_m, dtype=float)
    if head_history.ndim == 1:
        head_history = head_history.reshape(1, -1)
    if not bool(export_initial_state) and head_history.shape[0] > 1:
        head_history = head_history[1:, :]

    watertable_elevation, watertable_depth = _aggregate_triangle_history(
        head_history=head_history,
        time_keys=list(range(head_history.shape[0])),
        cell_centroid_x_m=np.asarray(model.mesh.cell_centroid_x_m, dtype=float),
        cell_centroid_y_m=np.asarray(model.mesh.cell_centroid_y_m, dtype=float),
        z_top_m=np.asarray(model.mesh.z_top_m, dtype=float),
        x_min_m=float(model.mesh.x_min_m),
        x_max_m=float(model.mesh.x_max_m),
        y_min_m=float(model.mesh.y_min_m),
        y_max_m=float(model.mesh.y_max_m),
        nx=int(nx),
        ny=int(ny),
    )
    postprocess_dir = Path(model.full_path) / "_postprocess"
    postprocess_dir.mkdir(parents=True, exist_ok=True)
    np.save(postprocess_dir / "watertable_elevation.npy", watertable_elevation)
    np.save(postprocess_dir / "watertable_depth.npy", watertable_depth)


def _load_piecewise_strip_bundle_geometry(
    bundle_dir: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float, float, float]:
    cells_path = Path(bundle_dir) / "cells.csv"
    nodes_path = Path(bundle_dir) / "nodes.csv"

    with cells_path.open("r", encoding="utf-8", newline="") as stream:
        cell_rows = list(csv.DictReader(stream))
    with nodes_path.open("r", encoding="utf-8", newline="") as stream:
        node_rows = list(csv.DictReader(stream))

    if not cell_rows or not node_rows:
        raise AssertionError(f"Piecewise-strip bundle is incomplete: {bundle_dir}")

    centroid_x_m = np.asarray([float(row["centroid_x"]) for row in cell_rows], dtype=float)
    centroid_y_m = np.asarray([float(row["centroid_y"]) for row in cell_rows], dtype=float)
    z_top_m = np.asarray([float(row["z_top_centroid"]) for row in cell_rows], dtype=float)
    node_x = np.asarray([float(row["x"]) for row in node_rows], dtype=float)
    node_y = np.asarray([float(row["y"]) for row in node_rows], dtype=float)
    return (
        centroid_x_m,
        centroid_y_m,
        z_top_m,
        float(np.min(node_x)),
        float(np.max(node_x)),
        float(np.min(node_y)),
        float(np.max(node_y)),
    )


def aggregate_piecewise_strip_postprocess(
    postprocess_dir: Path,
    *,
    bundle_dir: Path,
    nx: int = PIECEWISE_STRIP_NX,
    ny: int = PIECEWISE_STRIP_NY,
) -> None:
    """Rewrite launcher-produced vector `.npy` outputs to `(ny, nx)` grids."""
    head_payload = np.load(
        Path(postprocess_dir) / "watertable_elevation.npy",
        allow_pickle=True,
    ).item()
    if not head_payload:
        raise AssertionError("watertable_elevation.npy is empty.")

    ordered_items = sorted(
        (int(key), np.asarray(value, dtype=float))
        for key, value in dict(head_payload).items()
    )
    if all(
        array.ndim == 2 and tuple(array.shape) == (int(ny), int(nx))
        for _, array in ordered_items
    ):
        return

    head_arrays = [array.reshape(-1) for _, array in ordered_items]
    n_cells = head_arrays[0].size
    if any(array.ndim != 1 for array in head_arrays):
        raise AssertionError("Piecewise-strip launcher aggregation expects one cell vector per timestep.")
    if any(array.size != n_cells for array in head_arrays):
        raise AssertionError("All piecewise-strip timesteps must share the same vector length.")

    (
        centroid_x_m,
        centroid_y_m,
        z_top_m,
        x_min_m,
        x_max_m,
        y_min_m,
        y_max_m,
    ) = _load_piecewise_strip_bundle_geometry(Path(bundle_dir))
    if centroid_x_m.size != n_cells:
        raise AssertionError(
            "Bundle cell count does not match launcher Boussinesq postprocess length."
        )

    watertable_elevation, watertable_depth = _aggregate_triangle_history(
        head_history=np.stack(head_arrays, axis=0),
        time_keys=[key for key, _ in ordered_items],
        cell_centroid_x_m=centroid_x_m,
        cell_centroid_y_m=centroid_y_m,
        z_top_m=z_top_m,
        x_min_m=x_min_m,
        x_max_m=x_max_m,
        y_min_m=y_min_m,
        y_max_m=y_max_m,
        nx=int(nx),
        ny=int(ny),
    )
    np.save(Path(postprocess_dir) / "watertable_elevation.npy", watertable_elevation)
    np.save(Path(postprocess_dir) / "watertable_depth.npy", watertable_depth)


def write_piecewise_strip_launcher_config(
    config_path: Path,
    *,
    run_id: str,
    process_id: str,
    simulation_name: str,
    simulation_description: str,
    bundle_dir: Path,
    initial_head_m: float,
    west_head_m: float | None = None,
    east_head_m: float | None = None,
    recharge_rate_m_s: float | None = None,
    runtime_backend: str = "scipy_sparse",
) -> Path:
    """Write one minimal self-contained launcher config for the strip bundle."""
    active_bc: list[str] = []
    if west_head_m is not None:
        active_bc.append("west_side")
    if east_head_m is not None:
        active_bc.append("east_side")
    active_sinks_sources: list[str] = []
    if recharge_rate_m_s is not None:
        active_sinks_sources.append("recharge")

    lines = [
        "[workspace]",
        'project_root = "."',
        "",
        "[geographic]",
        'source_mode = "synthetic"',
        "",
        "[geographic.synthetic]",
        f'case_id = {json.dumps(str(run_id))}',
        "",
        "[geographic.synthetic.grid]",
        f'length_x = "{PIECEWISE_STRIP_LENGTH_X_M:.1f} m"',
        f'length_y = "{PIECEWISE_STRIP_WIDTH_Y_M:.1f} m"',
        f"nx = {PIECEWISE_STRIP_NX}",
        f"ny = {PIECEWISE_STRIP_NY}",
        "",
        "[geographic.synthetic.topography]",
        'kind = "flat"',
        f"base_elevation = {PIECEWISE_STRIP_Z_TOP_M:.1f}",
        "",
        "[domain.depth_model]",
        'type = "constant_thickness"',
        f'thickness = "{PIECEWISE_STRIP_Z_TOP_M - PIECEWISE_STRIP_Z_BOTTOM_M:.1f} m"',
        "",
        "[simulation]",
        f"name = {json.dumps(str(simulation_name))}",
        f"description = {json.dumps(str(simulation_description))}",
        f"run_id = {json.dumps(str(run_id))}",
        "",
        "[[simulation.process]]",
        f"id = {json.dumps(str(process_id))}",
        'type = "flow"',
        'solvers = ["boussinesq"]',
        "",
        "[mesh_input]",
        f"bundle_dir = {json.dumps(str(Path(bundle_dir).resolve()))}",
        "",
        "[flow]",
        'flow_regime = "steady"',
        f"runtime_backend = {json.dumps(str(runtime_backend))}",
        f"active_sinks_sources = [{', '.join(json.dumps(item) for item in active_sinks_sources)}]",
        f"active_bc = [{', '.join(json.dumps(item) for item in active_bc)}]",
        "",
        "[flow.ic]",
        'type = "custom"',
        f"value = {float(initial_head_m):.12g}",
    ]
    if west_head_m is not None:
        lines.extend(
            [
                "",
                "[flow.bc.dirichlet.west_side]",
                'type = "dirichlet"',
                f"value = {float(west_head_m):.12g}",
            ]
        )
    if east_head_m is not None:
        lines.extend(
            [
                "",
                "[flow.bc.dirichlet.east_side]",
                'type = "dirichlet"',
                f"value = {float(east_head_m):.12g}",
            ]
        )
    if recharge_rate_m_s is not None:
        lines.extend(
            [
                "",
                "[flow.sinks_sources.recharge]",
                'first_clim = "mean"',
                f"values = {float(recharge_rate_m_s):.17g}",
                'units = "m/s"',
            ]
        )
    lines.extend(
        [
            "",
            "[simulation.results]",
            "keep_solver_files = true",
            "",
            "[data]",
            "types = []",
            "",
            "[postprocess]",
            "enabled = false",
            "",
        ]
    )
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return config_path


def run_piecewise_strip_boussinesq_launcher_case(
    *,
    case_dir: Path,
    case_id: str,
    caller_file: str | Path,
    timeout: int,
    process_id: str,
    simulation_name: str,
    simulation_description: str,
    initial_head_m: float,
    west_head_m: float | None = None,
    east_head_m: float | None = None,
    recharge_rate_m_s: float | None = None,
    runtime_backend: str = "scipy_sparse",
) -> ValidationRunResult:
    """Run one steady Boussinesq piecewise-strip case through ``hmp run``."""
    out_path = resolve_validation_results_dir(
        test_file=caller_file,
        run_name=f"{case_id}_boussinesq",
    )
    bundle_dir = write_piecewise_strip_bundle(out_path / "mesh_bundle")
    config_path = write_piecewise_strip_launcher_config(
        out_path / "config_boussinesq_launcher.toml",
        run_id=f"{case_id}_boussinesq",
        process_id=process_id,
        simulation_name=simulation_name,
        simulation_description=simulation_description,
        bundle_dir=bundle_dir,
        initial_head_m=float(initial_head_m),
        west_head_m=None if west_head_m is None else float(west_head_m),
        east_head_m=None if east_head_m is None else float(east_head_m),
        recharge_rate_m_s=(
            None if recharge_rate_m_s is None else float(recharge_rate_m_s)
        ),
        runtime_backend=runtime_backend,
    )

    import subprocess as _sp

    env = os.environ.copy()
    env["HYDROMODPY_PROJECT_ROOT"] = str(out_path)
    env["HYDROMODPY_NO_DISPLAY"] = "1"
    env.setdefault("MPLBACKEND", "Agg")
    command = [sys.executable, "-m", "hydromodpy", "run", str(config_path)]
    completed = _sp.run(
        command, cwd=str(REPO_ROOT), env=env,
        text=True, capture_output=True, timeout=timeout,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"hmp run failed for {case_id}.\n"
            f"Command: {' '.join(command)}\n"
            f"Stdout:\n{completed.stdout}\n"
            f"Stderr:\n{completed.stderr}"
        )

    from validation_cases.shared.runtime import _discover_result_store

    store, sim_id = _discover_result_store(out_path)

    try:
        model_ws, postprocess_dir, particles_dir = resolve_model_workspace(
            out_path,
            results_folder_name="results_simulations",
            model_name=f"{process_id}__boussinesq",
        )
        aggregate_piecewise_strip_postprocess(
            postprocess_dir,
            bundle_dir=bundle_dir,
        )
    except AssertionError:
        if store is not None and sim_id is not None:
            model_ws = out_path
            postprocess_dir = out_path
            particles_dir = out_path
        else:
            raise

    return ValidationRunResult(
        case_dir=Path(case_dir),
        solver_name="boussinesq",
        out_path=out_path,
        model_ws=model_ws,
        postprocess_dir=postprocess_dir,
        particles_dir=particles_dir,
        run_returncode=int(completed.returncode),
        run_stdout=str(completed.stdout),
        run_stderr=str(completed.stderr),
        store=store,
        sim_id=sim_id,
    )


__all__ = [
    "PIECEWISE_STRIP_NX",
    "PIECEWISE_STRIP_NY",
    "PIECEWISE_STRIP_LENGTH_X_M",
    "PIECEWISE_STRIP_WIDTH_Y_M",
    "PIECEWISE_STRIP_Z_TOP_M",
    "PIECEWISE_STRIP_Z_BOTTOM_M",
    "PIECEWISE_STRIP_X_ZONE_BREAKS_M",
    "PIECEWISE_STRIP_HYDRAULIC_CONDUCTIVITY_M_S_BY_ZONE",
    "PIECEWISE_STRIP_STORAGE_COEFFICIENT",
    "aggregate_piecewise_strip_postprocess",
    "aggregate_triangle_history_to_structured_grids",
    "run_piecewise_strip_boussinesq_launcher_case",
    "write_piecewise_strip_bundle",
    "write_piecewise_strip_launcher_config",
]
