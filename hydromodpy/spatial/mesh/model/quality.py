"""Quality report of a planar cell mesh, computed by one routine for every engine.

The non-orthogonality of a connection is the angle between the line of the two
cell centres and the normal of the face they share. The conductance two-point
flux of MODFLOW is exact at 0 degrees on an isotropic medium, and XT3D corrects
the error that grows with the angle. :func:`connection_nonorthogonality_deg`
measures it on any planar ``HydroMesh``, so the MF6 options can decide whether
XT3D is worth its cost. Reference: Provost, Langevin and Hughes (2017),
"Documentation for the 'XT3D' option in the NPF Package of MODFLOW 6", USGS TM
6-A56.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
import shapely
from shapely.strtree import STRtree

from hydromodpy.spatial.mesh.model.geometry import (
    DerivedGeometry,
    cell_polygons,
    derive_geometry_from_rows,
    padded_rows,
)

if TYPE_CHECKING:
    from shapely.geometry import LineString
    from shapely.geometry.base import BaseGeometry

    from hydromodpy.spatial.mesh.model.hydro_mesh import HydroMesh
    from hydromodpy.spatial.mesh.model.planar_cell_mesh import CellChain, FaceFamilyTable

__all__ = [
    "BISECTION_OFFSET_WARNING",
    "DECLARATION_KEYS",
    "MIN_ANGLE_WARNING_DEG",
    "ORTHOGONAL_P95_DEG",
    "SHAPE_KEYS",
    "STRAIGHT_CORNER_DEG",
    "MeshQA",
    "cell_angle_range",
    "cell_corner_angles",
    "cell_edge_max",
    "cell_shape_qa",
    "compute_mesh_qa",
    "connection_nonorthogonality_deg",
    "edge_bisection_offset",
    "edge_nonorthogonality",
    "edge_size_ratio",
    "mixed_cells",
    "nonorthogonality_summary",
    "quality_warnings",
]

DECLARATION_KEYS = frozenset({"graded", "exact_faces", "deterministic", "needs_cache"})
"""Engine statements every QA carries."""

DEGENERATE_FACE_M = 1.0e-6
"""A face shorter than this length [m] is degenerate."""

RELATIVE_FACE_TOLERANCE = 1.0e-3
"""Share of the median face length used as the default face length threshold and
as the distance within which a family face covers its source line."""

MIXED_CELL_TRAVERSAL = 1.0e-6
"""A face line crosses a cell when its length inside the cell exceeds this share of
the cell side (square root of the area)."""

NONORTHOGONALITY_LIMIT_DEG = 30.0
"""Angle [deg] above which a face counts in ``nonorthogonality_deg["share_gt_30"]``."""

STRAIGHT_CORNER_DEG = 0.1
"""A corner within this angle [deg] of 180 is straight, not reflex.

The 1 mm merge of the Voronoi vertices bends a straight run of faces by about
0.02 deg next to a 5 m face; stored meshes measured put straight corners within
1e-6 deg of 180."""

MIN_ANGLE_WARNING_DEG = 20.0
"""A triangle with a corner under this angle [deg] is counted in the build warning."""

BISECTION_OFFSET_WARNING = 0.25
"""A cell with a face whose bisection offset exceeds this share is counted in the build warning."""

ORTHOGONAL_P95_DEG = 1.0
"""A mesh whose 95th percentile of non-orthogonality is under this angle is orthogonal."""

SHAPE_KEYS = ("bisection_offset", "min_angle_deg", "max_angle_deg", "n_concave_cells")
"""The QA entries :func:`cell_shape_qa` measures, added after the first cache schema."""


@dataclass(frozen=True)
class MeshQA:
    """Geometric quality and engine statements of one planar cell mesh.

    Lengths in metres, areas in square metres, angles in degrees. Quantile
    dictionaries are keyed ``p5``, ``p50`` ... ``min``, ``max``.
    ``bisection_offset`` holds the quantiles over the measured faces and
    ``n_cells_gt_0_25``, the cells with a face above
    :data:`BISECTION_OFFSET_WARNING`. ``min_angle_deg`` and ``max_angle_deg``
    hold the quantiles over the cells of their smallest and largest corner;
    ``min_angle_deg["n_triangles_lt_20"]`` counts the triangles with a corner
    under :data:`MIN_ANGLE_WARNING_DEG`. ``n_concave_cells`` counts the cells
    with a corner beyond 180 degrees plus :data:`STRAIGHT_CORNER_DEG`.
    ``size_fidelity`` is the cell side over the size asked for at its centre
    (``p5``, ``p50``, ``p95``); it is empty when no target size was given.
    """

    n_cells: int
    area_sum_m2: float
    domain_area_m2: float | None
    area_sum_rel_error: float | None
    area_quantiles_m2: dict[str, float]
    size_quantiles_m: dict[str, float]
    neighbour_ratio: dict[str, float]
    center_offset: dict[str, float]
    nonorthogonality_deg: dict[str, float]
    bisection_offset: dict[str, float]
    min_angle_deg: dict[str, float]
    max_angle_deg: dict[str, float]
    n_concave_cells: int
    min_face_length_m: float
    n_degenerate_faces: int
    n_duplicate_vertices_in_cells: int
    families: dict[str, dict[str, float]]
    declarations: dict[str, bool]
    notes: tuple[str, ...] = ()
    extras: dict[str, float] = field(default_factory=dict)
    size_fidelity: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Check that the engine stated each declaration, and only those."""
        if set(self.declarations) != DECLARATION_KEYS:
            raise ValueError(
                f"declarations must state exactly {sorted(DECLARATION_KEYS)}, "
                f"got {sorted(self.declarations)}"
            )

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-ready dictionary."""
        out = dataclasses.asdict(self)
        out["notes"] = list(self.notes)
        return out


def _stats(values: np.ndarray, keys: Sequence[str]) -> dict[str, float]:
    """Return the named percentiles (``pNN``), ``min`` and ``max`` of ``values``."""
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return {key: float("nan") for key in keys}
    out: dict[str, float] = {}
    for key in keys:
        if key == "min":
            out[key] = float(values.min())
        elif key == "max":
            out[key] = float(values.max())
        else:
            out[key] = float(np.percentile(values, float(key[1:])))
    return out


def _n_duplicate_corners(padded: np.ndarray) -> int:
    """Count the corners that repeat a vertex already in the same cell."""
    rows = np.sort(padded, axis=1)
    repeated = (rows[:, 1:] == rows[:, :-1]) & (rows[:, 1:] >= 0)
    return int(repeated.sum())


def edge_size_ratio(geometry: DerivedGeometry) -> np.ndarray:
    """Return, per mesh edge, the larger over the smaller side of its two cells.

    The side of a cell is the square root of its area. The value is ``NaN`` on a
    boundary edge, which has one cell only.
    """
    size = np.sqrt(geometry.areas)
    interior = geometry.edge_cells[:, 1] >= 0
    pairs = geometry.edge_cells[interior]
    ratio = np.full(geometry.edge_cells.shape[0], np.nan)
    ratio[interior] = np.maximum(size[pairs[:, 0]], size[pairs[:, 1]]) / np.minimum(
        size[pairs[:, 0]], size[pairs[:, 1]]
    )
    return ratio


def edge_nonorthogonality(
    centers: np.ndarray, vertices: np.ndarray, geometry: DerivedGeometry, keep: np.ndarray
) -> np.ndarray:
    """Return, per mesh edge, the angle [deg] between the centre-to-centre vector and the normal.

    ``keep`` selects the edges measured, interior edges with two cells. The value
    is ``NaN`` on every other edge and where the two centres coincide.
    """
    cells = geometry.edge_cells[keep]
    nodes = geometry.edge_nodes[keep]
    tangent = vertices[nodes[:, 1]] - vertices[nodes[:, 0]]
    tangent /= geometry.edge_length[keep][:, None]
    joint = centers[cells[:, 1]] - centers[cells[:, 0]]
    along = np.abs(joint[:, 0] * tangent[:, 0] + joint[:, 1] * tangent[:, 1])
    across = np.abs(joint[:, 0] * tangent[:, 1] - joint[:, 1] * tangent[:, 0])
    seen = (along > 0.0) | (across > 0.0)
    angles = np.full(keep.shape[0], np.nan)
    measured = np.flatnonzero(keep)[seen]
    angles[measured] = np.degrees(np.arctan2(along[seen], across[seen]))
    return angles


def connection_nonorthogonality_deg(
    planar_mesh: HydroMesh, *, centers: np.ndarray | None = None
) -> np.ndarray:
    """Return the non-orthogonality angle [deg] of every interior connection of a planar mesh.

    ``centers`` are the ``(n_cells, 2)`` cell centres, the generator seeds of a
    Voronoi mesh; the mean of the cell vertices when ``None``. A face of zero length and
    two cells on one centre are not measured. The angles follow the edge table
    of the derived geometry. Raises ``ValueError`` when an edge is shared by
    more than two cells.
    """
    if planar_mesh.n_cells == 0:
        return np.empty(0, dtype=float)
    vertices = np.asarray(planar_mesh.vertices, dtype=float)[:, :2]
    geometry = derive_geometry_from_rows(
        vertices, padded_rows(planar_mesh.flat_connectivity, n_nodes=planar_mesh.n_nodes)
    )
    if centers is None:
        centers = np.column_stack(planar_mesh.cell_centroids())
    keep = (geometry.edge_cells[:, 1] >= 0) & (geometry.edge_length > 0.0)
    angles = edge_nonorthogonality(centers, vertices, geometry, keep)
    return angles[~np.isnan(angles)]


def nonorthogonality_summary(
    planar_mesh: HydroMesh, *, centers: np.ndarray | None = None
) -> dict[str, float]:
    """Return the count, median, p95, p99, max and share above 30 deg of the connection angles.

    ``centers`` are read as :func:`connection_nonorthogonality_deg` reads them.
    Every entry is zero on a mesh without a measured connection.
    """
    angles = connection_nonorthogonality_deg(planar_mesh, centers=centers)
    if angles.size == 0:
        return {"n": 0.0, "median": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "frac_gt_30": 0.0}
    return {
        "n": float(angles.size),
        "median": float(np.median(angles)),
        "p95": float(np.percentile(angles, 95)),
        "p99": float(np.percentile(angles, 99)),
        "max": float(angles.max()),
        "frac_gt_30": float(np.mean(angles > NONORTHOGONALITY_LIMIT_DEG)),
    }


def edge_bisection_offset(
    centers: np.ndarray, vertices: np.ndarray, geometry: DerivedGeometry, keep: np.ndarray
) -> np.ndarray:
    """Return, per mesh edge, how far from the face middle the centre-to-centre line crosses it.

    The distance runs along the face, from its middle to the point where the line
    through the two cell centres meets the line of the face, over the face length.
    It is 0 when the line bisects the face and 0.5 when it passes through a face
    end. ``keep`` selects the edges measured, interior edges with two cells. The
    value is ``NaN`` on every other edge and where the line of the centres is
    parallel to the face.
    """
    cells = geometry.edge_cells[keep]
    nodes = geometry.edge_nodes[keep]
    length = geometry.edge_length[keep]
    start = vertices[nodes[:, 0]]
    tangent = (vertices[nodes[:, 1]] - start) / length[:, None]
    first = centers[cells[:, 0]] - start
    second = centers[cells[:, 1]] - start
    side_first = tangent[:, 0] * first[:, 1] - tangent[:, 1] * first[:, 0]
    side_second = tangent[:, 0] * second[:, 1] - tangent[:, 1] * second[:, 0]
    along_first = first[:, 0] * tangent[:, 0] + first[:, 1] * tangent[:, 1]
    along_second = second[:, 0] * tangent[:, 0] + second[:, 1] * tangent[:, 1]
    gap = side_first - side_second
    crossing = gap != 0.0
    along = along_first[crossing] + (along_second[crossing] - along_first[crossing]) * (
        side_first[crossing] / gap[crossing]
    )
    offsets = np.full(keep.shape[0], np.nan)
    offsets[np.flatnonzero(keep)[crossing]] = (
        np.abs(along - 0.5 * length[crossing]) / length[crossing]
    )
    return offsets


def cell_corner_angles(padded: np.ndarray, vertices: np.ndarray) -> np.ndarray:
    """Return the interior angle [deg] at each corner of each cell, in the padded layout.

    The angle at a reflex corner exceeds 180. ``NaN`` on the padding, at a corner
    next to a zero-length edge and in a cell of zero area.
    """
    padded = np.asarray(padded, dtype=np.int64)
    count = (padded >= 0).sum(axis=1)
    column = np.arange(padded.shape[1])[None, :]
    held = column < count[:, None]
    last = np.maximum(count - 1, 0)[:, None]
    before = np.where(held, np.where(column == 0, last, column - 1), 0)
    after = np.where(held, np.where(column == last, 0, column + 1), 0)
    nodes = np.where(padded >= 0, padded, 0)
    corner = vertices[nodes]
    previous = vertices[np.take_along_axis(nodes, before, axis=1)]
    following = vertices[np.take_along_axis(nodes, after, axis=1)]
    # Relative to the first corner: in Lambert-93 the absolute shoelace loses the sign.
    here = corner - corner[:, :1]
    there = following - corner[:, :1]
    shoelace = here[..., 0] * there[..., 1] - there[..., 0] * here[..., 1]
    orientation = np.sign(np.where(held, shoelace, 0.0).sum(axis=1))
    incoming = corner - previous
    outgoing = following - corner
    cross = incoming[..., 0] * outgoing[..., 1] - incoming[..., 1] * outgoing[..., 0]
    dot = incoming[..., 0] * outgoing[..., 0] + incoming[..., 1] * outgoing[..., 1]
    angles = 180.0 - np.degrees(np.arctan2(cross, dot)) * orientation[:, None]
    flat = (np.hypot(incoming[..., 0], incoming[..., 1]) == 0.0) | (
        np.hypot(outgoing[..., 0], outgoing[..., 1]) == 0.0
    )
    return np.where(held & ~flat & (orientation != 0.0)[:, None], angles, np.nan)


def cell_angle_range(padded: np.ndarray, vertices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the smallest and the largest interior angle [deg] of each cell.

    Both are ``NaN`` for a cell without a measured corner (see
    :func:`cell_corner_angles`).
    """
    angles = cell_corner_angles(padded, vertices)
    measured = ~np.isnan(angles)
    smallest = np.where(measured, angles, np.inf).min(axis=1)
    largest = np.where(measured, angles, -np.inf).max(axis=1)
    none = ~measured.any(axis=1)
    smallest[none] = np.nan
    largest[none] = np.nan
    return smallest, largest


def cell_edge_max(geometry: DerivedGeometry, per_edge: np.ndarray) -> np.ndarray:
    """Return the largest value of ``per_edge`` over the interior edges of each cell.

    ``NaN`` for a cell with no valid edge.
    """
    valid = ~np.isnan(per_edge) & (geometry.edge_cells[:, 1] >= 0)
    cells = geometry.edge_cells[valid]
    values = per_edge[valid]
    largest = np.full(geometry.n_cells, -np.inf)
    np.maximum.at(largest, cells[:, 0], values)
    np.maximum.at(largest, cells[:, 1], values)
    largest[np.isinf(largest)] = np.nan
    return largest


def cell_shape_qa(
    centers: np.ndarray,
    vertices: np.ndarray,
    geometry: DerivedGeometry,
    min_face_length_m: float,
) -> dict[str, Any]:
    """Measure the :data:`SHAPE_KEYS` entries of the QA.

    The bisection offset is measured on the interior faces longer than
    ``min_face_length_m``, the angles on every cell. The mesh cache calls it
    to complete an entry stored before these entries existed.
    """
    interior = geometry.edge_cells[:, 1] >= 0
    offsets = edge_bisection_offset(
        centers, vertices, geometry, interior & (geometry.edge_length > min_face_length_m)
    )
    bisection = _stats(offsets[~np.isnan(offsets)], ("p50", "p95", "p99", "max"))
    bisection["n_cells_gt_0_25"] = float(
        np.count_nonzero(cell_edge_max(geometry, offsets) > BISECTION_OFFSET_WARNING)
    )
    padded = geometry.padded_connectivity
    smallest, largest = cell_angle_range(padded, vertices)
    measured = ~np.isnan(smallest)
    min_angle = _stats(smallest[measured], ("min", "p1", "p5", "p50"))
    triangles = (padded >= 0).sum(axis=1) == 3
    min_angle["n_triangles_lt_20"] = float(
        np.count_nonzero(triangles & measured & (smallest < MIN_ANGLE_WARNING_DEG))
    )
    return {
        "bisection_offset": bisection,
        "min_angle_deg": min_angle,
        "max_angle_deg": _stats(largest[measured], ("p50", "p95", "p99", "max")),
        "n_concave_cells": int(
            np.count_nonzero(measured & (largest - 180.0 > STRAIGHT_CORNER_DEG))
        ),
    }


def quality_warnings(qa: MeshQA) -> tuple[str, ...]:
    """Return one sentence per quality threshold the mesh crosses.

    The sentences go to the build log. A mesh is never refused for them.
    """
    warnings = []
    sharp = int(qa.min_angle_deg["n_triangles_lt_20"])
    if sharp:
        warnings.append(
            f"{sharp} of {qa.n_cells} cells are triangles with a corner under "
            f"{MIN_ANGLE_WARNING_DEG:g} degrees (smallest {qa.min_angle_deg['min']:.1f})."
        )
    # On an orthogonal mesh the two-point flux stays consistent wherever the line of
    # the centres crosses the face, so the offset alone is no reason to warn. On the
    # generated Voronoi it crosses half the cells or more.
    skewed = int(qa.bisection_offset["n_cells_gt_0_25"])
    orthogonal = qa.nonorthogonality_deg.get("p95", float("inf")) < ORTHOGONAL_P95_DEG
    if skewed and not orthogonal:
        warnings.append(
            f"{skewed} of {qa.n_cells} cells have a face crossed by the line of the two "
            f"centres more than {BISECTION_OFFSET_WARNING:g} of its length from its middle "
            f"(largest {qa.bisection_offset['max']:.2f})."
        )
    if qa.n_concave_cells:
        warnings.append(
            f"{qa.n_concave_cells} of {qa.n_cells} cells are concave "
            f"(largest corner {qa.max_angle_deg['max']:.1f} degrees)."
        )
    return tuple(warnings)


def _is_member(sorted_keys: np.ndarray, probe: np.ndarray) -> np.ndarray:
    """Return, element-wise, whether ``probe`` is in the non-empty sorted array ``sorted_keys``."""
    found = np.minimum(np.searchsorted(sorted_keys, probe), sorted_keys.size - 1)
    return sorted_keys[found] == probe


def _chain_qa(
    chains: Sequence[CellChain],
    geometry: DerivedGeometry,
    n_nodes: int,
    centers: np.ndarray,
    lines: Sequence[LineString],
) -> dict[str, float]:
    """Breaks and face-step share of the cell chains of one family."""
    n_cells = geometry.n_cells
    starts = [chain.cell_ids[:-1] for chain in chains]
    stops = [chain.cell_ids[1:] for chain in chains]
    src = np.concatenate(starts) if starts else np.empty(0, dtype=np.int64)
    dst = np.concatenate(stops) if stops else np.empty(0, dtype=np.int64)
    moves = src != dst
    src, dst = src[moves], dst[moves]

    by_face = geometry.edge_between(src, dst) >= 0

    padded = geometry.padded_connectivity.astype(np.int64)
    corner_cell = np.broadcast_to(np.arange(n_cells, dtype=np.int64)[:, None], padded.shape)
    corner_keys = np.sort((corner_cell * n_nodes + padded)[padded >= 0])
    probe = src[:, None] * n_nodes + padded[dst]
    by_vertex = (_is_member(corner_keys, probe) & (padded[dst] >= 0)).any(axis=1)

    cells = np.unique(np.concatenate([chain.cell_ids for chain in chains]))
    out = {
        "chains": float(len(chains)),
        "cells": float(cells.size),
        "breaks": float(np.count_nonzero(~by_face & ~by_vertex)),
        "face_step_share": float(by_face.mean()) if by_face.size else float("nan"),
    }
    if lines and cells.size:
        points = shapely.points(centers[cells])
        out["max_line_offset_m"] = float(
            shapely.distance(points, shapely.multilinestrings(list(lines))).max()
        )
    return out


def mixed_cells(
    source: BaseGeometry, geometry: DerivedGeometry, vertices: np.ndarray, tolerance_m: float
) -> np.ndarray:
    """Return the ids of the cells whose interior the lines of ``source`` cross.

    Each cell is shrunk by ``tolerance_m`` first, so a line that follows a cell
    edge within the tolerance (a conformal face) is not a crossing. A cell is
    crossed when the length of ``source`` inside it exceeds
    :data:`MIXED_CELL_TRAVERSAL` of its side. The cells measured are those whose
    bounding box meets ``source``. A degenerate or invalid cell is never crossed.
    """
    padded = geometry.padded_connectivity.astype(np.int64)
    valid = padded >= 0
    x = vertices[np.where(valid, padded, 0), 0]
    y = vertices[np.where(valid, padded, 0), 1]
    boxes = shapely.box(
        np.where(valid, x, np.inf).min(axis=1),
        np.where(valid, y, np.inf).min(axis=1),
        np.where(valid, x, -np.inf).max(axis=1),
        np.where(valid, y, -np.inf).max(axis=1),
    )
    near = np.unique(STRtree(boxes).query(source, predicate="intersects"))
    if near.size == 0:
        return near
    polygons = shapely.buffer(cell_polygons(vertices, padded[near]), -tolerance_m)
    inside = shapely.length(shapely.intersection(polygons, source))
    return near[inside > MIXED_CELL_TRAVERSAL * np.sqrt(geometry.areas[near])]


def _face_family_qa(
    rows: np.ndarray,
    face_families: FaceFamilyTable,
    geometry: DerivedGeometry,
    vertices: np.ndarray,
    lines: Sequence[LineString],
    tolerance_m: float,
) -> dict[str, float]:
    """Face count and length of one face family, and its fit to the source lines."""
    start = vertices[face_families.node_a[rows]]
    stop = vertices[face_families.node_b[rows]]
    length = np.hypot(*(stop - start).T)
    out = {"faces": float(rows.size), "length_m": float(length.sum())}
    if lines and rows.size:
        faces = shapely.multilinestrings(shapely.linestrings(np.stack([start, stop], axis=1)))
        source = shapely.multilinestrings(list(lines))
        covered = shapely.intersection(source, shapely.buffer(faces, tolerance_m))
        out["covered_length_rel"] = float(shapely.length(covered) / shapely.length(source))
        out["hausdorff_m"] = float(shapely.hausdorff_distance(source, faces, densify=0.25))
    if lines:
        source = shapely.union_all(list(lines))
        out["mixed_cells"] = float(mixed_cells(source, geometry, vertices, tolerance_m).size)
    return out


def compute_mesh_qa(
    mesh: HydroMesh,
    centers: np.ndarray,
    geometry: DerivedGeometry,
    *,
    declarations: Mapping[str, bool],
    domain_area_m2: float | None = None,
    lines: Mapping[str, Sequence[LineString]] | None = None,
    cell_chains: Sequence[CellChain] = (),
    face_families: FaceFamilyTable | None = None,
    min_face_length_m: float | None = None,
    target_size: np.ndarray | None = None,
    notes: Sequence[str] = (),
    extras: Mapping[str, float] | None = None,
) -> MeshQA:
    """Measure the quality of one planar cell mesh.

    ``lines`` maps a family name to its source lines; a face family with lines
    gets its covered length share and Hausdorff distance, a cell family the
    largest distance of its cells to them. Non-orthogonality counts the interior
    faces longer than ``min_face_length_m`` (default: ``1e-3`` of the median face
    length), and so does the bisection offset (:func:`cell_shape_qa`). A face family with lines also gets ``mixed_cells``, the cells its
    lines cross. ``target_size`` is the size [m] asked for at each cell centre; it
    gives ``size_fidelity``.
    """
    lines = dict(lines or {})
    centers = np.asarray(centers, dtype=float)
    if centers.shape != (geometry.n_cells, 2):
        raise ValueError(f"centers must have shape ({geometry.n_cells}, 2), got {centers.shape}")
    if target_size is not None:
        target_size = np.asarray(target_size, dtype=float)
        if target_size.shape != (geometry.n_cells,) or not np.all(target_size > 0.0):
            raise ValueError(
                f"target_size must be positive with shape ({geometry.n_cells},), "
                f"got shape {target_size.shape}"
            )
    vertices = np.asarray(mesh.vertices, dtype=float)[:, :2]
    areas = geometry.areas
    size = np.sqrt(areas)
    face_tolerance = RELATIVE_FACE_TOLERANCE * float(np.median(geometry.edge_length))
    threshold = face_tolerance if min_face_length_m is None else float(min_face_length_m)

    interior = geometry.edge_cells[:, 1] >= 0
    ratio = edge_size_ratio(geometry)[interior]
    offset = np.hypot(*(centers - geometry.area_centroids).T) / size
    angles = edge_nonorthogonality(
        centers, vertices, geometry, interior & (geometry.edge_length > threshold)
    )
    angles = angles[~np.isnan(angles)]

    neighbour = _stats(ratio, ("p50", "p95", "p99", "max"))
    neighbour["share_gt_1_5"] = float((ratio > 1.5).mean()) if ratio.size else float("nan")
    nonorthogonality = _stats(angles, ("p50", "p95", "p99", "max"))
    nonorthogonality["share_gt_30"] = (
        float((angles > NONORTHOGONALITY_LIMIT_DEG).mean()) if angles.size else float("nan")
    )

    families: dict[str, dict[str, float]] = {}
    for name in dict.fromkeys(chain.family for chain in cell_chains):
        family_chains = [chain for chain in cell_chains if chain.family == name]
        families[name] = _chain_qa(
            family_chains, geometry, mesh.n_nodes, centers, lines.get(name, ())
        )
    if face_families is not None:
        for index, name in enumerate(face_families.names):
            rows = np.flatnonzero(face_families.family == index)
            families.setdefault(name, {}).update(
                _face_family_qa(
                    rows, face_families, geometry, vertices, lines.get(name, ()), face_tolerance
                )
            )

    area_sum = float(areas.sum())
    return MeshQA(
        n_cells=int(areas.size),
        area_sum_m2=area_sum,
        domain_area_m2=None if domain_area_m2 is None else float(domain_area_m2),
        area_sum_rel_error=(
            None
            if domain_area_m2 is None
            else abs(area_sum - float(domain_area_m2)) / float(domain_area_m2)
        ),
        area_quantiles_m2=_stats(areas, ("p5", "p50", "p95", "min", "max")),
        size_quantiles_m=_stats(size, ("p5", "p50", "p95")),
        neighbour_ratio=neighbour,
        center_offset=_stats(offset, ("p50", "p95", "max")),
        nonorthogonality_deg=nonorthogonality,
        **cell_shape_qa(centers, vertices, geometry, threshold),
        min_face_length_m=threshold,
        n_degenerate_faces=int(np.count_nonzero(geometry.edge_length < DEGENERATE_FACE_M)),
        n_duplicate_vertices_in_cells=_n_duplicate_corners(geometry.padded_connectivity),
        families=families,
        declarations={key: bool(value) for key, value in declarations.items()},
        notes=tuple(notes),
        extras={key: float(value) for key, value in (extras or {}).items()},
        size_fidelity={}
        if target_size is None
        else _stats(size / target_size, ("p5", "p50", "p95")),
    )
