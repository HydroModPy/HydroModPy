"""Characterization net of the triangle and Voronoi planar meshes.

The net freezes what the mesh refactor must not move, on a committed mesh
bundle (gmsh is not reproducible, so a triangulation is never generated here):

- the geometry of the two cell sets the engines build from the bundle
  (triangles, and the Voronoi cells around their vertices), as invariant quantiles;
- the heads of a short steady MODFLOW 6 run on each, read back from the store.

Nothing compares connectivity or cell ids. Cell counts are exact, the areas of
a frozen bundle are compared at 1e-9 (they do not depend on Qhull or GEOS
ordering), the quantiles at a platform-independent relative band. Isometries are
caught by probe points: at fixed coordinates the area and the center of the cell
that holds the point, and the head of a run forced by an asymmetric recharge.

Every tolerance is a row of ``tests/TOLERANCES.md`` read through ``tol()``; the
goldens hold values only. This module imports nothing from ``validation_cases``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import shapely

from tests._helpers.tolerances import tol

REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURE_DIR = REPO_ROOT / "tests" / "regression" / "fixtures" / "projects" / "mesh_net"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
BUNDLES_ROOT = REPO_ROOT / "validation_cases" / "shared" / "mesh_bundles"
ISLAND_BUNDLE = "dupuit_circular_island_ocean_irregular_tri_radial_48"
GRADED_BUNDLE = "stream_depletion_glover_balmer_tri_refined_well"

QUANTILE_REL = tol("mesh_characterization_net__geometry_quantiles_relative_band")
HEAD_RANGE_REL = tol("mesh_characterization_net__heads_share_of_the_golden_head_range")
"""Relative band of the quantiles, and of the heads as a share of the golden head range."""
AREA_REL = tol("mesh_characterization_net__cell_areas_and_their_sum_relative")
GEOMETRY_REL_BY_METRIC = {"sum": AREA_REL}
HEADS_REL_BY_METRIC = {"total_area": AREA_REL}
"""Relative tolerance (metric name -> value) of the areas, which are not quantiles."""
EXACT_METRICS = frozenset({"n_cells"})
"""Metrics compared by equality (the cell-count row of ``tests/TOLERANCES.md`` is ``n/a``)."""
ABS_FLOOR = {
    "center_offset_over_side": tol(
        "mesh_characterization_net__center_offset_over_side_absolute_floor"
    ),
    "non_orthogonality_deg": tol("mesh_characterization_net__non_orthogonality_absolute_floor"),
    "size_ratio": tol("mesh_characterization_net__neighbor_size_ratio_absolute_floor"),
    "center_dx": tol("mesh_characterization_net__probe_cell_center_offset_absolute_floor"),
    "center_dy": tol("mesh_characterization_net__probe_cell_center_offset_absolute_floor"),
}
"""Absolute floors (metric name -> value) of the quantities that are (almost) zero or a count."""
FACE_LENGTH_FRACTION = 0.1
"""A face counts for orthogonality when longer than this share of the median cell side."""

# Island center of the bundle (EPSG:2154) and fixed probe points around it, as
# (radius m, azimuth deg). Each probe sits at least 1 m from every triangle edge
# and every Voronoi edge, so the cell under it does not depend on rounding.
ISLAND_CENTER = (265705.0, 6784405.0)
PROBE_POLAR = ((34.0, 32.0), (63.0, 13.0), (101.5, 103.0), (144.0, 208.0), (166.0, 283.0))
GRADED_PROBES = ((178.5, 791.0), (621.5, 401.5), (295.5, 895.5), (718.0, 1313.5), (87.0, 297.5))
"""Probe points (EPSG:2154 local frame) of the graded strip: one beside the well, four spread out."""
PROBE_MIN_MARGIN_M = 1.0


def probe_points() -> np.ndarray:
    """Return the fixed probe coordinates around the island center, shape (5, 2)."""
    out = []
    for radius, azimuth in PROBE_POLAR:
        angle = np.radians(azimuth)
        out.append(
            (
                ISLAND_CENTER[0] + radius * np.cos(angle),
                ISLAND_CENTER[1] + radius * np.sin(angle),
            )
        )
    return np.asarray(out, dtype=float)


def bundle_probes(bundle: str) -> np.ndarray:
    """Return the fixed geometry probes of one bundle, shape (5, 2)."""
    if bundle == ISLAND_BUNDLE:
        return probe_points()
    return np.asarray(GRADED_PROBES, dtype=float)


def cells_under_probes(shapes: np.ndarray, probes: np.ndarray) -> np.ndarray:
    """Return the index of the cell holding each probe, located by coordinate.

    Each probe must fall in exactly one cell and stay ``PROBE_MIN_MARGIN_M`` away
    from its edges, so the cell does not depend on rounding.
    """
    inside = shapely.contains_xy(shapes[None, :], probes[:, 0:1], probes[:, 1:2])
    assert np.all(inside.sum(axis=1) == 1), "each probe must fall in exactly one cell"
    cells = inside.argmax(axis=1)
    margin = [
        float(shapely.distance(shapely.points(*probes[k]), shapely.boundary(shapes[c])))
        for k, c in enumerate(cells)
    ]
    assert min(margin) > PROBE_MIN_MARGIN_M, f"a probe sits too close to a cell edge: {margin}"
    return cells


# ---------------------------------------------------------------------------
# The two cell meshes, from the engine registry
# ---------------------------------------------------------------------------

BUNDLE_CRS_WKT = 'PROJCS["RGF93 v1 / Lambert-93"]'
"""Any non-empty WKT: the engines read the triangulation, they never reproject it."""


def _read_request(bundle: str, **options: Any):
    """Return the request that makes an engine read the committed ``.msh`` of *bundle*."""
    from hydromodpy.spatial.mesh.planning.input_triangulation import (
        domain_polygon_of,
        read_input_triangulation,
    )
    from hydromodpy.spatial.mesh.request import MeshRequest, RasterGridSpec

    triangulation = read_input_triangulation(BUNDLES_ROOT / bundle / "mesh_2d.msh")
    domain = domain_polygon_of(triangulation)
    xmin, ymin, xmax, ymax = domain.bounds
    side = max(xmax - xmin, ymax - ymin) / 10.0
    grid = RasterGridSpec(
        xmin=xmin,
        xmax=xmin + 10 * side,
        ymin=ymin,
        ymax=ymin + 10 * side,
        dx=side,
        dy=side,
        nrow=10,
        ncol=10,
        crs_wkt=BUNDLE_CRS_WKT,
    )
    return MeshRequest(
        domain=domain,
        grid=grid,
        nominal_size_m=side,
        input_triangulation=triangulation,
        options=options,
    )


def triangle_mesh(bundle: str = ISLAND_BUNDLE):
    """Return the triangles of a committed bundle as built by the ``triangle`` engine."""
    from hydromodpy.spatial.mesh import registry

    return registry.create("triangle").build(_read_request(bundle))


def voronoi_mesh(bundle: str = ISLAND_BUNDLE):
    """Return the Voronoi cells around the vertices of a committed bundle, from the engine."""
    from hydromodpy.spatial.mesh import registry

    return registry.create("voronoi").build(_read_request(bundle, seeds="triangulation"))


def polygons_of_mesh(cell_mesh) -> tuple[list[np.ndarray], np.ndarray]:
    """Cell polygons (vertex coordinates) and the cell centers of a ``PlanarCellMesh``."""
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)[:, :2]
    polygons = [vertices[row[row >= 0]] for row in cell_mesh.mesh.flat_connectivity]
    return polygons, np.asarray(cell_mesh.centers, dtype=float)


# ---------------------------------------------------------------------------
# Geometry metrics
# ---------------------------------------------------------------------------


def _quantiles(values: np.ndarray, qs: tuple[int, ...]) -> dict[str, float]:
    values = np.asarray(values, dtype=float)
    return {f"p{q}": float(np.percentile(values, q)) for q in qs}


def shared_faces(
    polygons: list[np.ndarray], connectivity: list[np.ndarray]
) -> list[tuple[int, int, np.ndarray, np.ndarray]]:
    """Faces shared by two cells: ``(cell_a, cell_b, end_a, end_b)``.

    Cells are matched on the vertex ids of their edges, not on coordinates.
    """
    owners: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for cell, ids in enumerate(connectivity):
        n = len(ids)
        for k in range(n):
            i, j = int(ids[k]), int(ids[(k + 1) % n])
            owners.setdefault((min(i, j), max(i, j)), []).append((cell, k))
    faces = []
    for owner in owners.values():
        if len(owner) != 2:
            continue
        (a, k), (b, _) = owner
        poly = polygons[a]
        faces.append((a, b, poly[k], poly[(k + 1) % len(poly)]))
    return faces


def geometry_metrics(mesh, probes: np.ndarray | None = None) -> dict[str, Any]:
    """Geometry of one planar cell mesh: invariant quantiles, plus probe cells.

    - ``n_cells``, area quantiles (p5, p50, p95) and sum;
    - neighbor size ratio of ``sqrt(area)`` over interior faces: p50, p95 and the
      share above 1.5;
    - seed-to-area-centroid distance over ``sqrt(area)``: p50, p95;
    - non-orthogonality, the angle between the center line and the face normal, on
      the faces longer than ``FACE_LENGTH_FRACTION`` of the median cell side: p95, max;
    - with ``probes``, the area and the center offset (cell center minus probe, m) of the
      cell holding each probe. The quantiles are the same for a mirrored or rotated
      mesh, the probe cells are not.
    """
    polygons, centers = polygons_of_mesh(mesh)
    connectivity = [row[row >= 0] for row in mesh.mesh.flat_connectivity]
    shapes = shapely.polygons([shapely.linearrings(p) for p in polygons])
    area = shapely.area(shapes)
    side = np.sqrt(area)
    centroid = shapely.get_coordinates(shapely.centroid(shapes))
    offset = np.hypot(centroid[:, 0] - centers[:, 0], centroid[:, 1] - centers[:, 1]) / side

    ratio, angle, length = [], [], []
    for a, b, p, q in shared_faces(polygons, connectivity):
        ratio.append(max(side[a], side[b]) / min(side[a], side[b]))
        tangent = q - p
        face_length = float(np.hypot(*tangent))
        link = centers[b] - centers[a]
        link_length = float(np.hypot(*link))
        length.append(face_length)
        # sin(angle to the face plane) = |link . t| / |link|, 0 for an orthogonal face.
        sine = abs(float(link @ tangent)) / (face_length * link_length)
        angle.append(np.degrees(np.arcsin(min(1.0, sine))))
    ratio, angle, length = np.asarray(ratio), np.asarray(angle), np.asarray(length)
    long_face = length > FACE_LENGTH_FRACTION * float(np.median(side))

    metrics: dict[str, Any] = {
        "n_cells": int(len(polygons)),
        "area": {**_quantiles(area, (5, 50, 95)), "sum": float(area.sum())},
        "size_ratio": {
            **_quantiles(ratio, (50, 95)),
            "share_gt_1_5": float(np.mean(ratio > 1.5)),
        },
        "center_offset_over_side": _quantiles(offset, (50, 95)),
        "non_orthogonality_deg": {
            "p95": float(np.percentile(angle[long_face], 95)),
            "max": float(angle[long_face].max()),
        },
    }
    if probes is not None:
        cells = cells_under_probes(shapes, probes)
        metrics["probe"] = [
            {
                "area": float(area[cell]),
                "center_dx": float(centers[cell, 0] - probe[0]),
                "center_dy": float(centers[cell, 1] - probe[1]),
            }
            for cell, probe in zip(cells, probes, strict=True)
        ]
    return metrics


# ---------------------------------------------------------------------------
# Pipeline: run through the public CLI, read back from the store
# ---------------------------------------------------------------------------


def run_fixture(config_name: str, out_dir: Path, *, timeout: int = 600) -> None:
    """Run ``hydromodpy run <fixture>`` in a subprocess, as the regression tier does."""
    env = os.environ.copy()
    env["HMP_PROJECT_ROOT"] = str(out_dir)
    env.setdefault("MPLBACKEND", "Agg")
    command = [
        sys.executable,
        "-m",
        "hydromodpy",
        "run",
        str(FIXTURE_DIR / config_name),
    ]
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )
    assert completed.returncode == 0, (
        f"hydromodpy run {config_name} failed (returncode={completed.returncode}).\n"
        f"Stdout:\n{completed.stdout}\nStderr:\n{completed.stderr}"
    )


def read_run(out_dir: Path) -> dict[str, np.ndarray]:
    """Read the cell polygons and the final head of the only run of a workspace."""
    from hydromodpy.results.catalog import Catalog

    store = Catalog(out_dir)
    try:
        sims = store.list_simulations()
        assert len(sims) == 1, f"expected one run, found {len(sims)}"
        zarr_store = store.open_zarr(str(sims.iloc[0]["sim_id"]))
        try:
            root = zarr_store.root
            vertices = np.asarray(root["mesh/vertices"][:], dtype=float)[:, :2]
            connectivity = np.asarray(root["mesh/face_node_connectivity"][:], dtype=int)
            head = np.asarray(root["head"][-1, 0, :], dtype=float)
        finally:
            zarr_store.close()
    finally:
        store.close()
    return {"vertices": vertices, "connectivity": connectivity, "head": head}


def head_metrics(run: dict[str, np.ndarray]) -> dict[str, Any]:
    """Cell count, total area and head statistics of one run, plus the probe heads."""
    vertices, padded, head = run["vertices"], run["connectivity"], run["head"]
    polygons = [vertices[row[row >= 0]] for row in padded]
    shapes = shapely.polygons([shapely.linearrings(p) for p in polygons])
    assert len(polygons) == head.size
    assert np.all(np.isfinite(head)), "the run left cells without a head"

    cell_of_probe = cells_under_probes(shapes, probe_points())

    return {
        "n_cells": int(head.size),
        "total_area": float(shapely.area(shapes).sum()),
        "head": {
            **_quantiles(head, (5, 50, 95)),
            "mean": float(head.mean()),
            "min": float(head.min()),
            "max": float(head.max()),
        },
        "probe_head": [float(head[c]) for c in cell_of_probe],
    }


# ---------------------------------------------------------------------------
# Goldens
# ---------------------------------------------------------------------------


def load_golden(name: str) -> dict[str, Any]:
    with (GOLDEN_DIR / name).open("r", encoding="utf-8") as stream:
        return json.load(stream)


def write_golden(name: str, payload: dict[str, Any]) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    with (GOLDEN_DIR / name).open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _flatten(prefix: str, value: Any, out: dict[str, float]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _flatten(f"{prefix}.{key}" if prefix else key, item, out)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _flatten(f"{prefix}[{index}]", item, out)
    else:
        out[prefix] = float(value)


def assert_within_band(
    actual: dict[str, Any],
    golden: dict[str, Any],
    *,
    band_rel: float,
    rel_by_metric: dict[str, float] | None = None,
    floors: dict[str, float] | None = None,
    scale: float | None = None,
) -> None:
    """Compare ``actual`` to the golden values, key by key.

    A key such as ``triangle.area.sum`` is looked up by the metric names in its path
    (``triangle``, ``area``, ``sum``). A name in ``EXACT_METRICS`` allows no gap. The first
    name found in ``rel_by_metric`` sets a relative tolerance. Otherwise the allowed gap is
    ``band_rel * scale`` when a ``scale`` (the head range) is given, else
    ``max(band_rel * |golden value|, floor)`` with the largest floor of ``floors`` on the path.
    A tolerance or floor naming no metric of the golden is an error: it would be a no-op.
    """
    rel_by_metric = rel_by_metric or {}
    floors = floors or {}
    flat_actual: dict[str, float] = {}
    flat_golden: dict[str, float] = {}
    _flatten("", {key: actual[key] for key in golden["values"]}, flat_actual)
    _flatten("", golden["values"], flat_golden)
    assert flat_actual.keys() == flat_golden.keys(), "the metric set changed"

    names = {part.split("[")[0] for key in flat_golden for part in key.split(".")}
    unused = sorted((set(rel_by_metric) | set(floors) | EXACT_METRICS) - names)
    assert not unused, f"tolerances that name no metric of the golden: {unused}"

    failures = []
    for key, expected in flat_golden.items():
        parts = [part.split("[")[0] for part in key.split(".")]
        rel = next((rel_by_metric[p] for p in parts if p in rel_by_metric), None)
        floor = max((float(floors[p]) for p in parts if p in floors), default=0.0)
        if EXACT_METRICS.intersection(parts):
            allowed = 0.0
        elif rel is not None:
            allowed = float(rel) * abs(expected)
        elif scale is not None:
            allowed = band_rel * scale
        else:
            allowed = max(band_rel * abs(expected), floor)
        if abs(flat_actual[key] - expected) > allowed:
            failures.append(
                f"{key}: got {flat_actual[key]:.6g}, golden {expected:.6g}, allowed +-{allowed:.3g}"
            )
    assert not failures, "outside the band:\n" + "\n".join(failures)
