"""Shared helpers for small irregular Gmsh strip bundles used in validation."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import numpy as np

from hydromodpy.spatial.mesh.gmsh_grid._deps import require_gmsh
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._gmsh_export import (
    build_runtime_planar_mesh_from_gmsh,
    write_repository_compatible_mesh,
)

ScalarOrProfile = float | list[float] | tuple[float, ...] | np.ndarray | Callable[[float], float]


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _load_bundle_cell_centroids(bundle_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    cells = np.genfromtxt(
        bundle_dir / "cells.csv",
        delimiter=",",
        names=True,
        dtype=None,
        encoding="utf-8",
    )
    return (
        np.asarray(cells["centroid_x"], dtype=float).reshape(-1),
        np.asarray(cells["centroid_y"], dtype=float).reshape(-1),
    )


def _load_bundle_cell_centroids_and_areas(
    bundle_dir: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cells = np.genfromtxt(
        bundle_dir / "cells.csv",
        delimiter=",",
        names=True,
        dtype=None,
        encoding="utf-8",
    )
    return (
        np.asarray(cells["centroid_x"], dtype=float).reshape(-1),
        np.asarray(cells["centroid_y"], dtype=float).reshape(-1),
        np.asarray(cells["area_m2"], dtype=float).reshape(-1),
    )


def _load_bundle_xy_extents(bundle_dir: Path) -> tuple[float, float, float, float]:
    nodes = np.genfromtxt(
        bundle_dir / "nodes.csv",
        delimiter=",",
        names=True,
        dtype=None,
        encoding="utf-8",
    )
    x_values = np.asarray(nodes["x"], dtype=float).reshape(-1)
    y_values = np.asarray(nodes["y"], dtype=float).reshape(-1)
    return (
        float(np.min(x_values)),
        float(np.max(x_values)),
        float(np.min(y_values)),
        float(np.max(y_values)),
    )


def _polygon_area(vertices: np.ndarray) -> float:
    coords = np.asarray(vertices, dtype=float)
    x_values = coords[:, 0]
    y_values = coords[:, 1]
    return 0.5 * float(
        abs(np.dot(x_values, np.roll(y_values, -1)) - np.dot(y_values, np.roll(x_values, -1)))
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
    extra_seed_points_m: tuple[tuple[float, float, float], ...] = (),
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
        surface_tag = int(
            gmsh.model.occ.addRectangle(0.0, 0.0, 0.0, float(length_x_m), float(width_y_m))
        )
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
            point_tags.append(int(gmsh.model.occ.addPoint(float(x_m), float(y_m), 0.0, local_size)))
        for x_m, y_m, local_size_m in tuple(extra_seed_points_m):
            point_tags.append(
                int(
                    gmsh.model.occ.addPoint(
                        float(x_m),
                        float(y_m),
                        0.0,
                        float(local_size_m),
                    )
                )
            )

        gmsh.model.occ.synchronize()
        if point_tags:
            gmsh.model.mesh.embed(0, point_tags, 2, surface_tag)

        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 1.0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0.0)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 1.0)
        gmsh.option.setNumber(
            "Mesh.CharacteristicLengthMin",
            max(
                0.25,
                min(
                    [0.55 * float(base_mesh_size_m)]
                    + [0.75 * float(point[2]) for point in tuple(extra_seed_points_m)]
                ),
            ),
        )
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


def write_gmsh22_triangle_mesh_from_bundle_csv(
    bundle_dir: Path,
    *,
    mesh_filename: str = "mesh_2d.msh",
) -> Path:
    """Write a minimal Gmsh 2.2 triangle mesh from bundle ``nodes``/``cells`` CSV files."""

    bundle_dir = Path(bundle_dir)
    nodes = np.genfromtxt(
        bundle_dir / "nodes.csv",
        delimiter=",",
        names=True,
        dtype=None,
        encoding="utf-8",
    )
    cells = np.genfromtxt(
        bundle_dir / "cells.csv",
        delimiter=",",
        names=True,
        dtype=None,
        encoding="utf-8",
    )

    node_ids = np.asarray(nodes["node_id"], dtype=int).reshape(-1)
    node_x = np.asarray(nodes["x"], dtype=float).reshape(-1)
    node_y = np.asarray(nodes["y"], dtype=float).reshape(-1)
    if node_ids.size == 0:
        raise ValueError(f"Bundle has no nodes: {bundle_dir}")

    node_order = np.argsort(node_ids)
    node_ids = node_ids[node_order]
    node_x = node_x[node_order]
    node_y = node_y[node_order]
    gmsh_id_by_node_id = {
        int(node_id): int(index + 1) for index, node_id in enumerate(node_ids.tolist())
    }

    cell_ids = np.asarray(cells["cell_id"], dtype=int).reshape(-1)
    geom_type = np.asarray(cells["geom_type"]).astype(str).reshape(-1)
    triangle_mask = np.char.lower(geom_type) == "triangle"
    if not np.any(triangle_mask):
        raise ValueError(f"Bundle has no triangle cells: {bundle_dir}")
    cell_order = np.argsort(cell_ids[triangle_mask])
    n0 = np.asarray(cells["n0"], dtype=int).reshape(-1)[triangle_mask][cell_order]
    n1 = np.asarray(cells["n1"], dtype=int).reshape(-1)[triangle_mask][cell_order]
    n2 = np.asarray(cells["n2"], dtype=int).reshape(-1)[triangle_mask][cell_order]

    lines: list[str] = [
        "$MeshFormat",
        "2.2 0 8",
        "$EndMeshFormat",
        "$Nodes",
        str(int(node_ids.size)),
    ]
    for node_id, x_m, y_m in zip(node_ids, node_x, node_y, strict=True):
        lines.append(f"{gmsh_id_by_node_id[int(node_id)]} {float(x_m):.12g} {float(y_m):.12g} 0")
    lines.extend(["$EndNodes", "$Elements", str(int(n0.size))])
    for element_index, (node_0, node_1, node_2) in enumerate(zip(n0, n1, n2, strict=True), start=1):
        lines.append(
            " ".join(
                [
                    str(int(element_index)),
                    "2",
                    "0",
                    str(gmsh_id_by_node_id[int(node_0)]),
                    str(gmsh_id_by_node_id[int(node_1)]),
                    str(gmsh_id_by_node_id[int(node_2)]),
                ]
            )
        )
    lines.append("$EndElements")

    mesh_path = bundle_dir / str(mesh_filename)
    mesh_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return mesh_path


def _collapse_bundle_history_to_x_profile_grids(
    history: np.ndarray,
    *,
    bundle_dir: Path,
    nx: int,
    ny: int,
    x_min_m: float | None = None,
    x_max_m: float | None = None,
) -> np.ndarray:
    """Reduce cell histories to area-weighted x profiles tiled across rows."""

    centroid_x, _centroid_y, cell_area = _load_bundle_cell_centroids_and_areas(bundle_dir)
    if history.shape[1] != centroid_x.size:
        raise ValueError(
            f"History cell count {history.shape[1]} does not match bundle cell count {centroid_x.size}."
        )

    inferred_x_min_m, inferred_x_max_m, _inferred_y_min_m, _inferred_y_max_m = (
        _load_bundle_xy_extents(bundle_dir)
    )
    x_min = inferred_x_min_m if x_min_m is None else float(x_min_m)
    x_max = inferred_x_max_m if x_max_m is None else float(x_max_m)
    x_edges = np.linspace(x_min, x_max, int(nx) + 1, dtype=float)
    profiles = np.full((history.shape[0], int(nx)), np.nan, dtype=float)

    for col_idx in range(int(nx)):
        left = float(x_edges[col_idx])
        right = float(x_edges[col_idx + 1])
        if col_idx == int(nx) - 1:
            mask = (centroid_x >= left) & (centroid_x <= right)
        else:
            mask = (centroid_x >= left) & (centroid_x < right)
        if np.any(mask):
            profiles[:, col_idx] = np.average(
                history[:, mask],
                axis=1,
                weights=cell_area[mask],
            )

    for time_idx in range(profiles.shape[0]):
        profile = profiles[time_idx]
        if not np.isnan(profile).any():
            continue
        valid_idx = np.flatnonzero(~np.isnan(profile))
        if valid_idx.size == 0:
            raise ValueError("Cannot collapse bundle history: no x bin contains a cell centroid.")
        profiles[time_idx] = np.interp(
            np.arange(profile.size, dtype=float),
            valid_idx.astype(float),
            profile[valid_idx],
        )

    return np.repeat(profiles[:, None, :], int(ny), axis=1)


def interpolate_bundle_history_to_structured_grids(
    values: np.ndarray,
    *,
    bundle_dir: Path,
    nx: int,
    ny: int,
    x_min_m: float | None = None,
    x_max_m: float | None = None,
    y_min_m: float | None = None,
    y_max_m: float | None = None,
    collapse_y_to_x_profile: bool = False,
) -> np.ndarray:
    """Project one time-cell history onto a regular ``ny x nx`` validation grid.

    The projection uses nearest-cell assignment from the irregular triangle
    centroids onto the structured cell centers. This is intentionally the same
    light-touch reduction used by the transient sloping-hillslope investigation
    utilities. When ``collapse_y_to_x_profile`` is true, values are first reduced
    to one area-weighted x profile and then tiled across rows for 1D analytical
    comparisons on an unstructured strip.
    """

    history = np.asarray(values, dtype=float)
    if history.ndim == 1:
        history = history.reshape(1, -1)
    if history.ndim != 2:
        raise ValueError("Bundle interpolation expects a time-cell history array.")

    if collapse_y_to_x_profile:
        return _collapse_bundle_history_to_x_profile_grids(
            history,
            bundle_dir=Path(bundle_dir),
            nx=nx,
            ny=ny,
            x_min_m=x_min_m,
            x_max_m=x_max_m,
        )

    centroid_x, centroid_y = _load_bundle_cell_centroids(Path(bundle_dir))
    if history.shape[1] != centroid_x.size:
        raise ValueError(
            f"History cell count {history.shape[1]} does not match bundle cell count {centroid_x.size}."
        )

    inferred_x_min_m, inferred_x_max_m, inferred_y_min_m, inferred_y_max_m = (
        _load_bundle_xy_extents(Path(bundle_dir))
    )
    x_min = inferred_x_min_m if x_min_m is None else float(x_min_m)
    x_max = inferred_x_max_m if x_max_m is None else float(x_max_m)
    y_min = inferred_y_min_m if y_min_m is None else float(y_min_m)
    y_max = inferred_y_max_m if y_max_m is None else float(y_max_m)

    dx = (x_max - x_min) / float(nx)
    dy = (y_max - y_min) / float(ny)
    x_centers = x_min + (np.arange(int(nx), dtype=float) + 0.5) * dx
    y_centers = y_min + (np.arange(int(ny), dtype=float) + 0.5) * dy

    nearest_indices = np.zeros((int(ny), int(nx)), dtype=int)
    for row_idx, y_center in enumerate(y_centers):
        for col_idx, x_center in enumerate(x_centers):
            squared_distance = (centroid_x - float(x_center)) ** 2 + (
                centroid_y - float(y_center)
            ) ** 2
            nearest_indices[row_idx, col_idx] = int(np.argmin(squared_distance))

    return history[:, nearest_indices].reshape(history.shape[0], int(ny), int(nx))


__all__ = [
    "interpolate_bundle_history_to_structured_grids",
    "write_gmsh22_triangle_mesh_from_bundle_csv",
    "write_irregular_strip_bundle",
]
