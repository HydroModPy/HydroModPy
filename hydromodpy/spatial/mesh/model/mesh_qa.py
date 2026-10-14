"""Quality report of a planar cell mesh, computed by one routine for every engine."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
import shapely

from hydromodpy.spatial.mesh.model.derived_geometry import DerivedGeometry

if TYPE_CHECKING:
    from shapely.geometry import LineString

    from hydromodpy.spatial.mesh.model.hydro_mesh import HydroMesh
    from hydromodpy.spatial.mesh.model.planar_cell_mesh import CellChain, FaceFamilyTable

__all__ = [
    "DECLARATION_KEYS",
    "MeshQA",
    "compute_mesh_qa",
    "edge_nonorthogonality",
    "edge_size_ratio",
]

DECLARATION_KEYS = frozenset({"graded", "exact_faces", "deterministic", "needs_cache"})
"""Engine statements every QA carries."""

DEGENERATE_FACE_M = 1.0e-6
"""A face shorter than this length [m] is degenerate."""

RELATIVE_FACE_TOLERANCE = 1.0e-3
"""Share of the median face length used as the default face length threshold and
as the distance within which a family face covers its source line."""


@dataclass(frozen=True)
class MeshQA:
    """Geometric quality and engine statements of one planar cell mesh.

    Lengths in metres, areas in square metres, angles in degrees. Quantile
    dictionaries are keyed ``p5``, ``p50`` ... ``min``, ``max``.
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
    min_face_length_m: float
    n_degenerate_faces: int
    n_duplicate_vertices_in_cells: int
    families: dict[str, dict[str, float]]
    declarations: dict[str, bool]
    notes: tuple[str, ...] = ()
    extras: dict[str, float] = field(default_factory=dict)

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


def _is_member(sorted_keys: np.ndarray, probe: np.ndarray) -> np.ndarray:
    """Return, element-wise, whether ``probe`` is in the sorted array ``sorted_keys``."""
    if sorted_keys.size == 0:
        return np.zeros(probe.shape, dtype=bool)
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

    indptr = geometry.adjacency_indptr
    rows = np.repeat(np.arange(n_cells, dtype=np.int64), np.diff(indptr))
    face_keys = rows * n_cells + geometry.adjacency_indices
    by_face = _is_member(face_keys, src * n_cells + dst)

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


def _face_family_qa(
    rows: np.ndarray,
    face_families: FaceFamilyTable,
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
    notes: Sequence[str] = (),
    extras: Mapping[str, float] | None = None,
) -> MeshQA:
    """Measure the quality of one planar cell mesh.

    ``lines`` maps a family name to its source lines; a face family with lines
    gets its covered length share and Hausdorff distance, a cell family the
    largest distance of its cells to them. Non-orthogonality counts the interior
    faces longer than ``min_face_length_m`` (default: ``1e-3`` of the median face
    length).
    """
    lines = dict(lines or {})
    centers = np.asarray(centers, dtype=float)
    if centers.shape != (geometry.n_cells, 2):
        raise ValueError(f"centers must have shape ({geometry.n_cells}, 2), got {centers.shape}")
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
                _face_family_qa(rows, face_families, vertices, lines.get(name, ()), face_tolerance)
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
        nonorthogonality_deg=_stats(angles, ("p50", "p95", "p99", "max")),
        min_face_length_m=threshold,
        n_degenerate_faces=int(np.count_nonzero(geometry.edge_length < DEGENERATE_FACE_M)),
        n_duplicate_vertices_in_cells=_n_duplicate_corners(geometry.padded_connectivity),
        families=families,
        declarations={key: bool(value) for key, value in declarations.items()},
        notes=tuple(notes),
        extras={key: float(value) for key, value in (extras or {}).items()},
    )
