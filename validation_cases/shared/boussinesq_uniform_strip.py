"""Shared local ``flow/boussinesq`` runtimes for homogeneous 1D strip cases."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from hydromodpy.physics.flow import Flow
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.flow.regime import normalize_flow_regime
from hydromodpy.simulation.planning.plan import (
    ProcessRun,
    RunContext,
    SimulationPlan,
)
from hydromodpy.solver.boussinesq.adapters.flow import BoussinesqFlowAdapter
from validation_cases.shared.loaders import merge_case_flow_section
from validation_cases.shared.runtime import (
    ValidationRunResult,
    materialize_postprocess_fields_to_store,
    resolve_validation_results_dir,
)

ScalarOrProfile = float | list[float] | tuple[float, ...] | np.ndarray | Callable[[float], float]


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def build_flow_config(
    flow_section: dict[str, object],
    *,
    case_dir: Path | None = None,
) -> FlowConfig:
    """Build one validation flow config from a TOML-like mapping."""
    base_dir = Path(".") if case_dir is None else Path(case_dir)
    merged_flow = (
        dict(flow_section)
        if case_dir is None
        else merge_case_flow_section(Path(case_dir), flow_section)
    )
    sequence_boundary_values: dict[str, list[float]] = {}
    raw_bc = merged_flow.get("bc")
    if isinstance(raw_bc, dict):
        dirichlet = raw_bc.get("dirichlet")
        if isinstance(dirichlet, dict):
            for bc_id, payload in dirichlet.items():
                if not isinstance(payload, dict):
                    continue
                raw_value = payload.get("value")
                if isinstance(raw_value, (list, tuple, np.ndarray)):
                    values = [
                        float(item) for item in np.asarray(raw_value, dtype=float).reshape(-1)
                    ]
                    sequence_boundary_values[str(bc_id)] = values
        for bc_id, payload in raw_bc.items():
            if bc_id in {"dirichlet", "cauchy", "robin"} or not isinstance(payload, dict):
                continue
            raw_value = payload.get("value")
            if isinstance(raw_value, (list, tuple, np.ndarray)):
                values = [float(item) for item in np.asarray(raw_value, dtype=float).reshape(-1)]
                sequence_boundary_values[str(bc_id)] = values

    validation_flow = dict(merged_flow)
    if sequence_boundary_values and isinstance(raw_bc, dict):
        validation_bc = dict(raw_bc)
        validation_dirichlet = dict(validation_bc.get("dirichlet", {}))
        for bc_id, values in sequence_boundary_values.items():
            if bc_id in validation_dirichlet and isinstance(validation_dirichlet[bc_id], dict):
                payload = dict(validation_dirichlet[bc_id])
                payload["value"] = float(values[0])
                validation_dirichlet[bc_id] = payload
            elif bc_id in validation_bc and isinstance(validation_bc[bc_id], dict):
                payload = dict(validation_bc[bc_id])
                payload["value"] = float(values[0])
                validation_bc[bc_id] = payload
        validation_bc["dirichlet"] = validation_dirichlet
        validation_flow["bc"] = validation_bc

    config = FlowConfig.from_toml_section(validation_flow, base_dir=base_dir)
    for bc_id, values in sequence_boundary_values.items():
        if bc_id in config.bc and isinstance(config.bc[bc_id], dict):
            normalized = dict(config.bc[bc_id])
            normalized["value"] = list(values)
            config.bc[bc_id] = normalized
    return config


def _resolve_profile_values(
    profile: ScalarOrProfile,
    *,
    x_values_m: np.ndarray,
    label: str,
) -> np.ndarray:
    if callable(profile):
        return np.asarray([float(profile(float(x_m))) for x_m in x_values_m], dtype=float)
    if np.isscalar(profile) and not isinstance(profile, (str, bytes)):
        return np.full(x_values_m.size, float(profile), dtype=float)
    values = np.asarray(profile, dtype=float).reshape(-1)
    if values.size != x_values_m.size:
        raise ValueError(
            f"{label} must provide exactly {x_values_m.size} values, got {values.size}."
        )
    return values


def write_uniform_strip_bundle(
    bundle_dir: Path,
    *,
    nx: int,
    ny: int,
    length_x_m: float,
    width_y_m: float,
    z_top_m: ScalarOrProfile,
    z_bottom_m: ScalarOrProfile,
    hydraulic_conductivity_m_s: float,
    storage_coefficient: float,
) -> Path:
    """Write one deterministic triangular strip bundle for 1D profile validation."""
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

    dx = float(length_x_m) / float(nx)
    dy = float(width_y_m) / float(ny)
    node_x_m = np.asarray([float(ix) * dx for ix in range(int(nx) + 1)], dtype=float)
    node_top_m = _resolve_profile_values(z_top_m, x_values_m=node_x_m, label="z_top_m")
    node_bottom_m = _resolve_profile_values(
        z_bottom_m,
        x_values_m=node_x_m,
        label="z_bottom_m",
    )
    if np.any(node_bottom_m >= node_top_m):
        raise ValueError("z_bottom_m must remain strictly below z_top_m along the strip.")

    node_rows: list[str] = []
    for iy in range(int(ny) + 1):
        for ix in range(int(nx) + 1):
            node_id = iy * (int(nx) + 1) + ix
            node_rows.append(
                ",".join(
                    [
                        str(node_id),
                        f"{node_x_m[ix]:.6f}",
                        f"{float(iy) * dy:.6f}",
                        f"{node_top_m[ix]:.6f}",
                        f"{node_bottom_m[ix]:.6f}",
                    ]
                )
            )
    _write_csv(bundle_dir / "nodes.csv", "node_id,x,y,z_top,z_bottom", node_rows)

    node_xy = {
        iy * (int(nx) + 1) + ix: (float(ix) * dx, float(iy) * dy)
        for iy in range(int(ny) + 1)
        for ix in range(int(nx) + 1)
    }
    triangle_area_m2 = 0.5 * dx * dy
    cell_rows: list[str] = []
    cell_geology_rows: list[str] = []
    edge_records: dict[tuple[int, int], dict[str, object]] = {}
    cell_id = 0

    for iy in range(int(ny)):
        for ix in range(int(nx)):
            n00 = iy * (int(nx) + 1) + ix
            n10 = n00 + 1
            n01 = n00 + (int(nx) + 1)
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
                cell_top_m = float(
                    _resolve_profile_values(
                        z_top_m,
                        x_values_m=np.asarray([centroid_x_m], dtype=float),
                        label="z_top_m",
                    )[0]
                )
                cell_bottom_m = float(
                    _resolve_profile_values(
                        z_bottom_m,
                        x_values_m=np.asarray([centroid_x_m], dtype=float),
                        label="z_bottom_m",
                    )[0]
                )
                if cell_bottom_m >= cell_top_m:
                    raise ValueError(
                        "z_bottom_m must remain strictly below z_top_m at every cell centroid."
                    )
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
                            f"{cell_top_m:.6f}",
                            f"{cell_top_m:.6f}",
                            f"{cell_bottom_m:.6f}",
                            f"{cell_bottom_m:.6f}",
                            "1",
                            "zone_1",
                            f"{float(hydraulic_conductivity_m_s):.12g}",
                            f"{float(storage_coefficient):.12g}",
                        ]
                    )
                )
                cell_geology_rows.append(f"{cell_id},zone_1,1.0")

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
                            "geology_a_key": "zone_1",
                            "geology_b_key": "",
                        }
                    else:
                        edge["cell_b"] = cell_id
                        edge["geology_b_key"] = "zone_1"
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


def aggregate_triangle_history_to_structured_grids(
    model,
    *,
    nx: int,
    ny: int,
    export_initial_state: bool = False,
) -> None:
    """Overwrite the default cell-vector postprocess with a regular profile grid."""
    if model.state is None or model.mesh is None:
        raise RuntimeError("Boussinesq validation case requires a solved model state.")

    head_history = np.asarray(model.state.head_history_m, dtype=float)
    if head_history.ndim == 1:
        head_history = head_history.reshape(1, -1)
    if not bool(export_initial_state) and head_history.shape[0] > 1:
        head_history = head_history[1:, :]

    dx = (float(model.mesh.x_max_m) - float(model.mesh.x_min_m)) / float(nx)
    dy = (float(model.mesh.y_max_m) - float(model.mesh.y_min_m)) / float(ny)
    col_index = np.clip(
        np.floor(
            (np.asarray(model.mesh.cell_centroid_x_m, dtype=float) - float(model.mesh.x_min_m)) / dx
        ).astype(int),
        0,
        int(nx) - 1,
    )
    row_index = np.clip(
        np.floor(
            (np.asarray(model.mesh.cell_centroid_y_m, dtype=float) - float(model.mesh.y_min_m)) / dy
        ).astype(int),
        0,
        int(ny) - 1,
    )

    top_sum = np.zeros((int(ny), int(nx)), dtype=float)
    counts = np.zeros((int(ny), int(nx)), dtype=int)
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
        head_sum = np.zeros((int(ny), int(nx)), dtype=float)
        head_count = np.zeros((int(ny), int(nx)), dtype=int)
        for cell_idx in range(model.mesh.n_cells):
            row = int(row_index[cell_idx])
            col = int(col_index[cell_idx])
            head_sum[row, col] += float(head_values[cell_idx])
            head_count[row, col] += 1
        if np.any(head_count == 0):
            raise AssertionError(
                "Every structured validation bin must receive at least one triangle."
            )
        head_grid = head_sum / head_count
        watertable_elevation[int(time_index)] = head_grid
        watertable_depth[int(time_index)] = np.maximum(top_grid - head_grid, 0.0)

    postprocess_dir = Path(model.full_path) / "_postprocess"
    postprocess_dir.mkdir(parents=True, exist_ok=True)
    np.save(postprocess_dir / "watertable_elevation.npy", watertable_elevation)
    np.save(postprocess_dir / "watertable_depth.npy", watertable_depth)


def run_boussinesq_uniform_strip_case(
    *,
    case_dir: Path,
    case_id: str,
    caller_file: str | Path,
    timeout: int,
    nx: int,
    ny: int,
    length_x_m: float,
    width_y_m: float,
    z_top_m: ScalarOrProfile,
    z_bottom_m: ScalarOrProfile,
    hydraulic_conductivity_m_s: float,
    storage_coefficient: float,
    flow_section: dict[str, Any],
    plan_name: str,
    plan_description: str,
    process_id: str = "flow_validation",
    flow_regime: str = "steady",
    nper: int | None = None,
    dt_seconds: float | None = None,
    export_initial_state: bool | None = None,
) -> ValidationRunResult:
    """Run one Boussinesq validation case on a small homogeneous strip mesh."""
    del timeout

    normalized_regime = normalize_flow_regime(flow_regime)
    if normalized_regime == "transient":
        if nper is None or dt_seconds is None:
            raise ValueError("Transient strip cases require nper and dt_seconds.")
    elif export_initial_state is None:
        export_initial_state = True
    if export_initial_state is None:
        export_initial_state = False

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
        z_top_m=z_top_m,
        z_bottom_m=z_bottom_m,
        hydraulic_conductivity_m_s=float(hydraulic_conductivity_m_s),
        storage_coefficient=float(storage_coefficient),
    )
    simulations_folder = out_path / "results_simulations"
    simulations_folder.mkdir(parents=True, exist_ok=True)

    time_grid = None
    if normalized_regime == "transient":
        period_lengths_seconds = tuple(float(dt_seconds) for _ in range(int(nper)))
        time_grid = SimpleNamespace(
            period_lengths_seconds=period_lengths_seconds,
            window=None,
        )

    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(build_flow_config(flow_section, case_dir=case_dir)),
            domain=None,
            time_grid=time_grid,
            workspace=SimpleNamespace(
                simulations_folder=simulations_folder, solver_scratch_folder=simulations_folder
            ),
        ),
    )
    run = ProcessRun(
        id=f"{process_id}::boussinesq",
        process_id=process_id,
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(
            name=plan_name,
            description=plan_description,
            runs=(run,),
        ),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model
    aggregate_triangle_history_to_structured_grids(
        model,
        nx=int(nx),
        ny=int(ny),
        export_initial_state=bool(export_initial_state),
    )

    model_ws = Path(model.full_path)
    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"
    store, sim_id = materialize_postprocess_fields_to_store(
        out_path=out_path,
        postprocess_dir=postprocess_dir,
        solver_name="boussinesq",
    )
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
        store=store,
        sim_id=sim_id,
    )


__all__ = [
    "aggregate_triangle_history_to_structured_grids",
    "build_flow_config",
    "run_boussinesq_uniform_strip_case",
    "write_uniform_strip_bundle",
]
