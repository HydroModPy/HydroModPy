"""Triangle mesh of the stream depletion case, refined around the well.

Gmsh meshes the 800 x 1610 m rectangle with its Frontal-Delaunay algorithm, so
the triangles are near equilateral: a two-point flux between cell centres stays
consistent on them. The well is a node of the mesh, so the Voronoi dual has a
cell centred on it. The edge length grows linearly with the distance to the
well, from 4 m within 8 m of it to 60 m beyond 700 m, and with the distance to
the stream face, from 10 m on it to 60 m beyond 600 m; the smaller size wins.
Every stream cell is then about 10 m long, so the stream cells hold the stream
head on a straight line about 3 m inside the face, all along it.

Run as a module to rewrite the committed bundle.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from validation_cases.shared.gmsh_irregular_strip import write_gmsh22_triangle_mesh_from_bundle_csv

LENGTH_X_M = 800.0
LENGTH_Y_M = 1610.0
WELL_XY_M = (105.0, 805.0)
SIZE_AT_WELL_M = 4.0
SIZE_FAR_M = 60.0
REFINED_RADIUS_M = 8.0
GRADED_RADIUS_M = 700.0
SIZE_AT_STREAM_M = 10.0
STREAM_GRADED_DISTANCE_M = 600.0
Z_TOP_M = 40.0
Z_BOTTOM_M = 0.0
HYDRAULIC_CONDUCTIVITY_M_S = 1.0e-4
STORAGE_COEFFICIENT = 0.1
BUNDLE_DIR = (
    Path(__file__).resolve().parents[3]
    / "shared"
    / "mesh_bundles"
    / "stream_depletion_glover_balmer_tri_refined_well"
)


def graded_nodes_and_triangles() -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """Mesh the rectangle with Gmsh and return the node coordinates and the triangles."""
    import gmsh

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("stream_depletion")
        surface = gmsh.model.occ.addRectangle(0.0, 0.0, 0.0, LENGTH_X_M, LENGTH_Y_M)
        well = gmsh.model.occ.addPoint(WELL_XY_M[0], WELL_XY_M[1], 0.0)
        gmsh.model.occ.synchronize()
        gmsh.model.mesh.embed(0, [well], 2, surface)
        stream_face = [
            tag
            for dim, tag in gmsh.model.getBoundary([(2, surface)], oriented=False)
            if np.allclose(gmsh.model.getBoundingBox(dim, tag)[0:4:3], 0.0, atol=1e-3)
        ]

        distance = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(distance, "PointsList", [well])
        threshold = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(threshold, "InField", distance)
        gmsh.model.mesh.field.setNumber(threshold, "SizeMin", SIZE_AT_WELL_M)
        gmsh.model.mesh.field.setNumber(threshold, "SizeMax", SIZE_FAR_M)
        gmsh.model.mesh.field.setNumber(threshold, "DistMin", REFINED_RADIUS_M)
        gmsh.model.mesh.field.setNumber(threshold, "DistMax", GRADED_RADIUS_M)
        stream_distance = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(stream_distance, "CurvesList", stream_face)
        gmsh.model.mesh.field.setNumber(stream_distance, "Sampling", 400)
        stream_threshold = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(stream_threshold, "InField", stream_distance)
        gmsh.model.mesh.field.setNumber(stream_threshold, "SizeMin", SIZE_AT_STREAM_M)
        gmsh.model.mesh.field.setNumber(stream_threshold, "SizeMax", SIZE_FAR_M)
        gmsh.model.mesh.field.setNumber(stream_threshold, "DistMin", 0.0)
        gmsh.model.mesh.field.setNumber(stream_threshold, "DistMax", STREAM_GRADED_DISTANCE_M)
        smallest = gmsh.model.mesh.field.add("Min")
        gmsh.model.mesh.field.setNumbers(smallest, "FieldsList", [threshold, stream_threshold])
        gmsh.model.mesh.field.setAsBackgroundMesh(smallest)

        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.option.setNumber("Mesh.RandomFactor", 1e-9)
        gmsh.model.mesh.generate(2)

        tags, coords, _ = gmsh.model.mesh.getNodes()
        _, element_tags, element_nodes = gmsh.model.mesh.getElements(2)
    finally:
        gmsh.finalize()

    xyz = np.asarray(coords, dtype=float).reshape(-1, 3)
    index_of_tag = {int(tag): index for index, tag in enumerate(np.asarray(tags, dtype=int))}
    triangle_tags = np.asarray(element_nodes[0], dtype=int).reshape(-1, 3)
    used = np.unique(triangle_tags)
    new_index = {int(tag): position for position, tag in enumerate(used)}
    nodes = np.asarray([xyz[index_of_tag[int(tag)], :2] for tag in used], dtype=float)
    triangles = [tuple(new_index[int(tag)] for tag in row) for row in triangle_tags]
    del element_tags
    return nodes, triangles


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def write_graded_bundle(bundle_dir: Path = BUNDLE_DIR) -> Path:
    """Write the mesh bundle of the case and return its folder."""
    bundle_dir = Path(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    nodes, triangles = graded_nodes_and_triangles()
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
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "mesh_summary.json").write_text(
        json.dumps(
            {
                "constraints_mode": "geology_only",
                "generator": "gmsh_frontal_delaunay_graded_from_well_and_stream",
                "n_cells": len(triangles),
                "n_nodes": int(nodes.shape[0]),
                "size_at_well_m": SIZE_AT_WELL_M,
                "size_at_stream_m": SIZE_AT_STREAM_M,
                "size_far_m": SIZE_FAR_M,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_csv(
        bundle_dir / "nodes.csv",
        "node_id,x,y,z_top,z_bottom",
        [
            f"{node_id},{x_m:.6f},{y_m:.6f},{Z_TOP_M:.6f},{Z_BOTTOM_M:.6f}"
            for node_id, (x_m, y_m) in enumerate(nodes)
        ],
    )
    cell_rows: list[str] = []
    edges: dict[tuple[int, int], list[int]] = {}
    for cell_id, triangle in enumerate(triangles):
        points = nodes[list(triangle)]
        centroid = points.mean(axis=0)
        area = 0.5 * abs(
            (points[1, 0] - points[0, 0]) * (points[2, 1] - points[0, 1])
            - (points[2, 0] - points[0, 0]) * (points[1, 1] - points[0, 1])
        )
        cell_rows.append(
            f"{cell_id},triangle,{triangle[0]},{triangle[1]},{triangle[2]},,"
            f"{centroid[0]:.6f},{centroid[1]:.6f},{area:.6f},"
            f"{Z_TOP_M:.6f},{Z_TOP_M:.6f},{Z_BOTTOM_M:.6f},{Z_BOTTOM_M:.6f},1,zone_1,"
            f"{HYDRAULIC_CONDUCTIVITY_M_S:.12g},{STORAGE_COEFFICIENT:.12g}"
        )
        for a, b in ((0, 1), (1, 2), (2, 0)):
            key = tuple(sorted((triangle[a], triangle[b])))
            edges.setdefault(key, []).append(cell_id)
    _write_csv(
        bundle_dir / "cells.csv",
        "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2,z_top_centroid,"
        "z_top_mean,z_bottom_centroid,z_bottom_mean,geology_code,geology_key,"
        "hydraulic_conductivity_m_s,storage_coefficient",
        cell_rows,
    )
    _write_csv(
        bundle_dir / "cell_geology_fractions.csv",
        "cell_id,geology_key,fraction",
        [f"{cell_id},zone_1,1.0" for cell_id in range(len(triangles))],
    )
    edge_rows = []
    for edge_id, ((node_a, node_b), owners) in enumerate(edges.items()):
        length_m = float(np.linalg.norm(nodes[node_b] - nodes[node_a]))
        cell_b = "" if len(owners) == 1 else str(owners[1])
        kind = "boundary" if len(owners) == 1 else "internal"
        geology_b = "" if len(owners) == 1 else "zone_1"
        edge_rows.append(
            f"{edge_id},{node_a},{node_b},{owners[0]},{cell_b},{length_m:.6f},{kind},false,"
            f"zone_1,{geology_b}"
        )
    _write_csv(
        bundle_dir / "edges.csv",
        "edge_id,node_a,node_b,cell_a,cell_b,length_m,edge_kind,is_river,"
        "geology_a_key,geology_b_key",
        edge_rows,
    )
    write_gmsh22_triangle_mesh_from_bundle_csv(bundle_dir)
    return bundle_dir


if __name__ == "__main__":
    print(write_graded_bundle())
