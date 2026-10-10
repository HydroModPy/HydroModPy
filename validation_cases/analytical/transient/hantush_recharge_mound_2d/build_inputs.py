"""Build the recharge raster and the two mesh bundles of the recharge mound case.

Rebuild them with
``python -m validation_cases.analytical.transient.hantush_recharge_mound_2d.build_inputs``.

The raster has the pixels of the 101 x 101 model grid, 20 m wide, so a model
cell centre reads the pixel it sits in, and the rectangle edges fall on pixel
edges. A mesh cell takes the pixel under its centroid, so a mesh gets the
recharge over exactly the rectangle area only when no cell straddles an edge.
Both bundles are Gmsh triangulations refined under the rectangle, 10 m there
and up to 80 m at the domain sides.

- ``hantush_recharge_mound_tri_conforming``: the rectangle edges are mesh
  lines, so each triangle lies wholly inside or outside. It serves the
  triangle grid of MODFLOW 6 and the Boussinesq runs.
- ``hantush_recharge_mound_voronoi_frames``: two frames of nodes, half a cell
  inside and half a cell outside each edge, face each other node for node. The
  Voronoi edge between two facing nodes is the rectangle edge, so each dual
  cell lies wholly inside or outside. It serves the Voronoi dual. Its band of
  squares split in two would put right triangles on a triangle grid.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from hydromodpy.spatial.mesh.gmsh_grid._deps import require_gmsh
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._gmsh_export import (
    build_runtime_planar_mesh_from_gmsh,
    write_repository_compatible_mesh,
)

CASE_DIR = Path(__file__).resolve().parent
BUNDLES_DIR = CASE_DIR.parents[2] / "shared" / "mesh_bundles"
TRIANGLE_BUNDLE_DIR = BUNDLES_DIR / "hantush_recharge_mound_tri_conforming"
VORONOI_BUNDLE_DIR = BUNDLES_DIR / "hantush_recharge_mound_voronoi_frames"
RASTER_PATH = CASE_DIR / "recharge_zone.tif"

DOMAIN_M = 2020.0
RECTANGLE = (860.0, 1160.0, 920.0, 1100.0)
RECHARGE_MM_DAY = 20.0
PIXEL_M = 20.0
CELL_M = 10.0
FAR_CELL_M = 80.0
GROWTH_DISTANCE_M = 800.0
Z_TOP_M = 60.0
Z_BOTTOM_M = 0.0
HYDRAULIC_CONDUCTIVITY_M_S = 4.0e-5
SPECIFIC_YIELD = 0.15
SEED = 20261010


def build_recharge_raster(path: Path = RASTER_PATH) -> Path:
    """Write the rectangle of recharge, in mm/day, on the pixels of the model grid."""
    import rasterio
    from rasterio.transform import from_origin

    count = int(round(DOMAIN_M / PIXEL_M))
    centres = (np.arange(count) + 0.5) * PIXEL_M
    x, y = np.meshgrid(centres, DOMAIN_M - centres)
    x_min, x_max, y_min, y_max = RECTANGLE
    inside = (x > x_min) & (x < x_max) & (y > y_min) & (y < y_max)
    values = np.where(inside, RECHARGE_MM_DAY, 0.0).astype("float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=count,
        width=count,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=from_origin(0.0, DOMAIN_M, PIXEL_M, PIXEL_M),
        nodata=-9999.0,
        compress="deflate",
    ) as raster:
        raster.write(values, 1)
        raster.update_tags(units="mm/day")
    return path


def _band_geometry(gmsh) -> tuple[int, list[int], list[int]]:
    """Add the band between the frames as structured strips, two triangles a square.

    Returns the domain surface, the band surfaces and the curves of the outer
    frame. Left free, Gmsh puts a node in the middle of each band square, on
    the rectangle edge, which the frames are there to avoid.
    """
    geo = gmsh.model.geo
    x_min, x_max, y_min, y_max = RECTANGLE
    half = 0.5 * CELL_M
    xs = (x_min - half, x_min + half, x_max - half, x_max + half)
    ys = (y_min - half, y_min + half, y_max - half, y_max + half)
    point = {(i, j): geo.addPoint(xs[i], ys[j], 0.0, CELL_M) for i in range(4) for j in range(4)}
    lines: dict[tuple, int] = {}

    def line(a: tuple[int, int], b: tuple[int, int]) -> int:
        if (b, a) in lines:
            return -lines[(b, a)]
        if (a, b) not in lines:
            lines[(a, b)] = geo.addLine(point[a], point[b])
        return lines[(a, b)]

    band: list[int] = []
    for i in range(3):
        for j in range(3):
            if (i, j) == (1, 1):
                continue
            loop = [line((i, j), (i + 1, j)), line((i + 1, j), (i + 1, j + 1))]
            loop += [line((i + 1, j + 1), (i, j + 1)), line((i, j + 1), (i, j))]
            band.append(geo.addPlaneSurface([geo.addCurveLoop(loop)]))
    inner = [line((1, 1), (2, 1)), line((2, 1), (2, 2)), line((2, 2), (1, 2)), line((1, 2), (1, 1))]
    inside = geo.addPlaneSurface([geo.addCurveLoop(inner)])
    outer: list[int] = []
    for a, b in (((0, 0), (3, 0)), ((3, 0), (3, 3)), ((3, 3), (0, 3)), ((0, 3), (0, 0))):
        step = (int(b[0] > a[0]) - int(b[0] < a[0]), int(b[1] > a[1]) - int(b[1] < a[1]))
        node = a
        while node != b:
            following = (node[0] + step[0], node[1] + step[1])
            outer.append(line(node, following))
            node = following

    corners = [(0.0, 0.0), (DOMAIN_M, 0.0), (DOMAIN_M, DOMAIN_M), (0.0, DOMAIN_M)]
    corner_tags = [geo.addPoint(x, y, 0.0, FAR_CELL_M) for x, y in corners]
    border = [geo.addLine(corner_tags[k], corner_tags[(k + 1) % 4]) for k in range(4)]
    outside = geo.addPlaneSurface([geo.addCurveLoop(border), geo.addCurveLoop(outer)])
    geo.synchronize()

    for (a, b), tag in lines.items():
        length = abs(xs[b[0]] - xs[a[0]]) + abs(ys[b[1]] - ys[a[1]])
        gmsh.model.mesh.setTransfiniteCurve(tag, int(round(length / CELL_M)) + 1)
    for surface in band:
        gmsh.model.mesh.setTransfiniteSurface(surface)
    return outside, [inside, *band], [abs(tag) for tag in outer]


def _conforming_geometry(gmsh) -> list[int]:
    """Add the rectangle edges as mesh lines: no triangle straddles them.

    Returns the curves of the rectangle.
    """
    geo = gmsh.model.geo
    x_min, x_max, y_min, y_max = RECTANGLE
    corners = [(x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max)]
    tags = [geo.addPoint(x, y, 0.0, CELL_M) for x, y in corners]
    edges = [geo.addLine(tags[k], tags[(k + 1) % 4]) for k in range(4)]
    loop = geo.addCurveLoop(edges)
    geo.addPlaneSurface([loop])
    domain = [(0.0, 0.0), (DOMAIN_M, 0.0), (DOMAIN_M, DOMAIN_M), (0.0, DOMAIN_M)]
    domain_tags = [geo.addPoint(x, y, 0.0, FAR_CELL_M) for x, y in domain]
    border = [geo.addLine(domain_tags[k], domain_tags[(k + 1) % 4]) for k in range(4)]
    geo.addPlaneSurface([geo.addCurveLoop(border), loop])
    geo.synchronize()
    for edge, (a, b) in zip(
        edges, zip(corners, corners[1:] + corners[:1], strict=True), strict=True
    ):
        length = abs(b[0] - a[0]) + abs(b[1] - a[1])
        gmsh.model.mesh.setTransfiniteCurve(edge, int(round(length / CELL_M)) + 1)
    return edges


def _mesh_with_gmsh(gmsh, mesh_path: Path, *, kind: str):
    if kind == "voronoi_frames":
        frame_lines = _band_geometry(gmsh)[2]
    elif kind == "conforming":
        frame_lines = _conforming_geometry(gmsh)
    else:
        raise ValueError(f"Unknown bundle kind {kind!r}.")

    field = gmsh.model.mesh.field
    distance = field.add("Distance")
    field.setNumbers(distance, "CurvesList", frame_lines)
    field.setNumber(distance, "Sampling", 40)
    threshold = field.add("Threshold")
    field.setNumber(threshold, "InField", distance)
    field.setNumber(threshold, "SizeMin", CELL_M)
    field.setNumber(threshold, "SizeMax", FAR_CELL_M)
    field.setNumber(threshold, "DistMin", CELL_M)
    field.setNumber(threshold, "DistMax", GROWTH_DISTANCE_M)
    x_min, x_max, y_min, y_max = RECTANGLE
    box = field.add("Box")
    field.setNumber(box, "VIn", CELL_M)
    field.setNumber(box, "VOut", FAR_CELL_M)
    field.setNumber(box, "XMin", x_min)
    field.setNumber(box, "XMax", x_max)
    field.setNumber(box, "YMin", y_min)
    field.setNumber(box, "YMax", y_max)
    smallest = field.add("Min")
    field.setNumbers(smallest, "FieldsList", [threshold, box])
    field.setAsBackgroundMesh(smallest)

    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.Algorithm", 6)
    gmsh.option.setNumber("Mesh.RandomSeed", SEED)
    gmsh.model.mesh.generate(2)
    planar_mesh = build_runtime_planar_mesh_from_gmsh(gmsh, source_path=mesh_path)
    write_repository_compatible_mesh(gmsh, mesh_path)
    return planar_mesh


def _polygon_area(vertices: np.ndarray) -> float:
    x, y = vertices[:, 0], vertices[:, 1]
    return float(0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def build_mesh_bundle(bundle_dir: Path, *, kind: str) -> Path:
    """Write one bundle refined under the recharge rectangle.

    ``kind`` is ``"conforming"`` or ``"voronoi_frames"``.
    """
    bundle_dir.mkdir(parents=True, exist_ok=True)
    mesh_path = bundle_dir / "mesh_2d.msh"
    gmsh = require_gmsh()
    try:
        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("hantush_recharge_mound")
        planar_mesh = _mesh_with_gmsh(gmsh, mesh_path, kind=kind)
    finally:
        gmsh.finalize()

    points = np.asarray(planar_mesh.points_xy, dtype=float)
    node_rows = [
        f"{index},{x:.6f},{y:.6f},{Z_TOP_M:.6f},{Z_BOTTOM_M:.6f}"
        for index, (x, y) in enumerate(points)
    ]
    cell_rows: list[str] = []
    geology_rows: list[str] = []
    edges: dict[tuple[int, int], list[int]] = {}
    for cell in planar_mesh.cells:
        nodes = tuple(int(node) for node in cell.node_indices)
        cx, cy = (float(value) for value in cell.centroid)
        area = _polygon_area(np.asarray(cell.vertices, dtype=float))
        cell_rows.append(
            f"{int(cell.index)},{cell.kind},{nodes[0]},{nodes[1]},{nodes[2]},,"
            f"{cx:.6f},{cy:.6f},{area:.6f},{Z_TOP_M:.6f},{Z_TOP_M:.6f},"
            f"{Z_BOTTOM_M:.6f},{Z_BOTTOM_M:.6f},1,zone_1,"
            f"{HYDRAULIC_CONDUCTIVITY_M_S:.12g},{SPECIFIC_YIELD:.12g}"
        )
        geology_rows.append(f"{int(cell.index)},zone_1,1.0")
        for a, b in ((nodes[0], nodes[1]), (nodes[1], nodes[2]), (nodes[2], nodes[0])):
            edges.setdefault((min(a, b), max(a, b)), []).append(int(cell.index))
    edge_rows = []
    for edge_id, ((a, b), owners) in enumerate(edges.items()):
        length = float(np.linalg.norm(points[b] - points[a]))
        other = "" if len(owners) == 1 else str(owners[1])
        edge_kind = "boundary" if len(owners) == 1 else "internal"
        geology_b = "" if len(owners) == 1 else "zone_1"
        edge_rows.append(
            f"{edge_id},{a},{b},{owners[0]},{other},{length:.6f},{edge_kind},false,zone_1,{geology_b}"
        )

    _write_csv(bundle_dir / "nodes.csv", "node_id,x,y,z_top,z_bottom", node_rows)
    _write_csv(
        bundle_dir / "cells.csv",
        "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2,z_top_centroid,"
        "z_top_mean,z_bottom_centroid,z_bottom_mean,geology_code,geology_key,"
        "hydraulic_conductivity_m_s,storage_coefficient",
        cell_rows,
    )
    _write_csv(
        bundle_dir / "cell_geology_fractions.csv", "cell_id,geology_key,fraction", geology_rows
    )
    _write_csv(
        bundle_dir / "edges.csv",
        "edge_id,node_a,node_b,cell_a,cell_b,length_m,edge_kind,is_river,geology_a_key,geology_b_key",
        edge_rows,
    )
    files = {
        "mesh": "mesh_2d.msh",
        "nodes": "nodes.csv",
        "cells": "cells.csv",
        "edges": "edges.csv",
        "cell_geology_fractions": "cell_geology_fractions.csv",
        "metadata": "metadata.json",
        "mesh_summary": "mesh_summary.json",
    }
    (bundle_dir / "metadata.json").write_text(
        json.dumps(
            {
                "bundle_schema_version": "mesh_catchment_bundle_v1",
                "crs": "EPSG:2154",
                "files": files,
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
                "generator": f"hantush_recharge_mound_2d.build_inputs:{kind}",
                "seed": SEED,
                "cell_size_under_rectangle_m": CELL_M,
                "cell_size_far_m": FAR_CELL_M,
                "n_cells": int(planar_mesh.n_cells),
                "n_nodes": int(points.shape[0]),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return bundle_dir


if __name__ == "__main__":
    print(build_recharge_raster())
    print(build_mesh_bundle(TRIANGLE_BUNDLE_DIR, kind="conforming"))
    print(build_mesh_bundle(VORONOI_BUNDLE_DIR, kind="voronoi_frames"))
