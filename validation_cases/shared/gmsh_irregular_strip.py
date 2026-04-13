"""Shared helpers for small irregular Gmsh strip bundles used in validation."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import numpy as np

from hydromodpy.solver.utils.mesh.gmsh_grid._deps import require_gmsh
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._gmsh_export import (
    build_runtime_planar_mesh_from_gmsh,
    write_repository_compatible_mesh,
)


ScalarOrProfile = float | list[float] | tuple[float, ...] | np.ndarray | Callable[[float], float]


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _polygon_area(vertices: np.ndarray) -> float:
    coords = np.asarray(vertices, dtype=float)
    x_values = coords[:, 0]
    y_values = coords[:, 1]
    return 0.5 * float(
        abs(
            np.dot(x_values, np.roll(y_values, -1))
            - np.dot(y_values, np.roll(x_values, -1))
        )
    )


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


def _build_seed_point_cloud(
    *,
    nx_seed: int,
    ny_seed: int,
    length_x_m: float,
    width_y_m: float,
    rng: np.random.Generator,
) -> np.ndarray:
    dx = float(length_x_m) / float(nx_seed)
    dy = float(width_y_m) / float(ny_seed)
    xs: list[float] = []
    ys: list[float] = []
    for iy in range(int(ny_seed)):
        for ix in range(int(nx_seed)):
            center_x = (float(ix) + 0.5) * dx
            center_y = (float(iy) + 0.5) * dy
            jitter_x = rng.uniform(-0.32 * dx, 0.32 * dx)
            jitter_y = rng.uniform(-0.32 * dy, 0.32 * dy)
            xs.append(float(np.clip(center_x + jitter_x, 0.08 * dx, length_x_m - 0.08 * dx)))
            ys.append(float(np.clip(center_y + jitter_y, 0.08 * dy, width_y_m - 0.08 * dy)))
    return np.column_stack((np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)))


def write_irregular_strip_bundle(
    bundle_dir: Path,
    *,
    nx_seed: int,
    ny_seed: int,
    length_x_m: float,
    width_y_m: float,
    z_top_m: ScalarOrProfile,
    z_bottom_m: ScalarOrProfile,
    hydraulic_conductivity_m_s: float,
    storage_coefficient: float,
    seed: int = 20260413,
    base_mesh_size_m: float | None = None,
) -> Path:
    """Write one irregular triangular strip bundle backed by an actual Gmsh mesh."""

    bundle_dir.mkdir(parents=True, exist_ok=True)
    mesh_path = bundle_dir / "mesh_2d.msh"
    rng = np.random.default_rng(int(seed))
    gmsh = require_gmsh()

    if base_mesh_size_m is None:
        target_cells = max(1, int(nx_seed) * int(ny_seed))
        base_mesh_size_m = float(np.sqrt((length_x_m * width_y_m) / (0.433 * target_cells)))

    try:
        gmsh.initialize()
        gmsh.model.add("irregular_strip")
        surface_tag = int(gmsh.model.occ.addRectangle(0.0, 0.0, 0.0, float(length_x_m), float(width_y_m)))
        gmsh.model.occ.synchronize()

        seed_points = _build_seed_point_cloud(
            nx_seed=int(nx_seed),
            ny_seed=int(ny_seed),
            length_x_m=float(length_x_m),
            width_y_m=float(width_y_m),
            rng=rng,
        )
        point_tags: list[int] = []
        for x_m, y_m in seed_points:
            local_size = float(base_mesh_size_m) * float(rng.uniform(0.78, 1.24))
            point_tags.append(
                int(gmsh.model.occ.addPoint(float(x_m), float(y_m), 0.0, local_size))
            )

        gmsh.model.occ.synchronize()
        if point_tags:
            gmsh.model.mesh.embed(0, point_tags, 2, surface_tag)

        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 1.0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0.0)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 1.0)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", max(0.25, 0.55 * float(base_mesh_size_m)))
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", 1.45 * float(base_mesh_size_m))
        gmsh.model.mesh.generate(2)

        planar_mesh = build_runtime_planar_mesh_from_gmsh(gmsh, source_path=mesh_path)
        write_repository_compatible_mesh(gmsh, mesh_path)
    finally:
        try:
            gmsh.finalize()
        except Exception:
            pass

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
        json.dumps(
            {
                "constraints_mode": "geology_only",
                "generator": "gmsh_irregular_strip",
                "seed": int(seed),
                "base_mesh_size_m": float(base_mesh_size_m),
                "n_cells": int(planar_mesh.n_cells),
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )

    node_x_m = np.asarray(planar_mesh.points_xy[:, 0], dtype=float)
    node_top_m = _resolve_profile_values(z_top_m, x_values_m=node_x_m, label="z_top_m")
    node_bottom_m = _resolve_profile_values(z_bottom_m, x_values_m=node_x_m, label="z_bottom_m")
    if np.any(node_bottom_m >= node_top_m):
        raise ValueError("z_bottom_m must remain strictly below z_top_m along the strip.")

    node_rows = [
        f"{node_id},{float(x_m):.6f},{float(y_m):.6f},{float(node_top_m[node_id]):.6f},{float(node_bottom_m[node_id]):.6f}"
        for node_id, (x_m, y_m) in enumerate(np.asarray(planar_mesh.points_xy, dtype=float))
    ]
    _write_csv(bundle_dir / "nodes.csv", "node_id,x,y,z_top,z_bottom", node_rows)

    edge_records: dict[tuple[int, int], dict[str, object]] = {}
    cell_rows: list[str] = []
    cell_geology_rows: list[str] = []
    for cell in planar_mesh.cells:
        centroid_x_m = float(cell.centroid[0])
        centroid_y_m = float(cell.centroid[1])
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
        node_indices = tuple(int(node_idx) for node_idx in cell.node_indices)
        n3_value = "" if len(node_indices) < 4 else str(node_indices[3])
        cell_rows.append(
            ",".join(
                [
                    str(int(cell.index)),
                    str(cell.kind),
                    str(node_indices[0]),
                    str(node_indices[1]),
                    str(node_indices[2]),
                    n3_value,
                    f"{centroid_x_m:.6f}",
                    f"{centroid_y_m:.6f}",
                    f"{_polygon_area(np.asarray(cell.vertices, dtype=float)):.6f}",
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
        cell_geology_rows.append(f"{int(cell.index)},zone_1,1.0")

        for edge_nodes in (
            (node_indices[0], node_indices[1]),
            (node_indices[1], node_indices[2]),
            (node_indices[2], node_indices[0]),
        ):
            key = tuple(sorted((int(edge_nodes[0]), int(edge_nodes[1]))))
            edge = edge_records.get(key)
            if edge is None:
                point_a = np.asarray(planar_mesh.points_xy[key[0]], dtype=float)
                point_b = np.asarray(planar_mesh.points_xy[key[1]], dtype=float)
                edge_records[key] = {
                    "node_a": key[0],
                    "node_b": key[1],
                    "cell_a": int(cell.index),
                    "cell_b": None,
                    "length_m": float(np.linalg.norm(point_b - point_a)),
                    "geology_a_key": "zone_1",
                    "geology_b_key": "",
                }
            else:
                edge["cell_b"] = int(cell.index)
                edge["geology_b_key"] = "zone_1"

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


__all__ = ["write_irregular_strip_bundle"]
