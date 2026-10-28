"""The request lines in the local frame, the families in priority order.

A face family comes before another by ``FACE_PRIORITY``. The parts of a line
along the domain boundary are dropped. A stretch of a face line that runs on an
earlier face line (a cutoff wall along a lake shore) is left to that line and
kept as a shared stretch.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from hydromodpy.spatial.mesh.engines.voronoi.local_coords import LocalFrame
from hydromodpy.spatial.mesh.model.geometry import vertex_keys
from hydromodpy.spatial.mesh.request import LineFamilySpec

__all__ = [
    "FACE_PRIORITY",
    "CanonicalLine",
    "SharedStretch",
    "canonical_lines",
    "family_sort_key",
]

FACE_PRIORITY = ("lakes", "barriers", "geology", "watershed_boundary")
"""Face families from the highest priority to the lowest; a family
not named here comes after them, by name. A river wins over the others,
except a barrier or a lake shore (``RIVER_PROOF_FAMILIES``). A barrier outranks
a geology contact: a barrier segment that yields leaves a cell across the
barrier."""


def family_sort_key(spec: LineFamilySpec) -> tuple[int, int, str]:
    """Cell families first, by name; face families by priority, then by name."""
    if spec.intent == "cell":
        return (0, 0, spec.name)
    if spec.name in FACE_PRIORITY:
        return (1, FACE_PRIORITY.index(spec.name), "")
    return (1, len(FACE_PRIORITY), spec.name)


@dataclass
class CanonicalLine:
    """One canonical line of the request, in the local frame."""

    gid: int
    family: int
    coords: np.ndarray
    closed: bool
    zone_left: int
    zone_right: int
    source: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))

    def __post_init__(self) -> None:
        """Keep the coordinates as given: a crossing rewrites ``coords``, not ``source``."""
        if not len(self.source):
            self.source = self.coords.copy()


@dataclass(frozen=True)
class SharedStretch:
    """A stretch of a face line of family ``family`` that runs on line ``owner``."""

    family: int
    owner: int
    coords: np.ndarray


def _line_key(coords: np.ndarray) -> tuple[float, ...]:
    """Sort key of a line: first vertex, last vertex, length, then every coordinate."""
    length = float(np.hypot(*np.diff(coords, axis=0).T).sum())
    head = np.round([*coords[0], *coords[-1], length], 6).tolist()
    return (*head, *coords.ravel().tolist())


def canonical_lines(
    specs: Sequence[LineFamilySpec],
    frame: LocalFrame,
    domain: Polygon,
    tol: float,
    zone_names: tuple[str, ...],
) -> tuple[list[CanonicalLine], list[SharedStretch], tuple[str, ...]]:
    """Every line in the local frame, families in priority order, lines sorted in each.

    A part of a face line that runs along the domain boundary is removed: the
    boundary already bounds the cells there. A part that runs on the segments
    of an earlier face line is removed too and returned as a shared stretch.
    """
    boundary = domain.boundary
    lines: list[CanonicalLine] = []
    shared: list[SharedStretch] = []
    segment_owner: dict[tuple[int, int], int] = {}
    notes: list[str] = []
    for index, spec in enumerate(specs):
        entries = []
        for k, line in enumerate(spec.lines):
            coords = shapely.get_coordinates(frame.to_local(line))
            left = zone_names.index(spec.zone_left[k]) if spec.zone_left else -1
            right = zone_names.index(spec.zone_right[k]) if spec.zone_right else -1
            closed = bool(spec.closed and np.array_equal(coords[0], coords[-1]))
            entries.append((_line_key(coords), coords, closed, left, right))
        entries.sort(key=lambda entry: entry[0])
        removed = 0.0
        for _, coords, closed, left, right in entries:
            pieces = [(coords, closed)]
            if spec.intent == "face":
                pieces, gone = _off_boundary(coords, closed, boundary, tol)
                removed += gone
            for piece, piece_closed in pieces:
                if spec.intent == "cell":
                    lines.append(CanonicalLine(len(lines), index, piece, piece_closed, left, right))
                    continue
                for owner, run, run_closed in _own_runs(piece, piece_closed, segment_owner):
                    if owner >= 0:
                        shared.append(SharedStretch(index, owner, run))
                        continue
                    lines.append(CanonicalLine(len(lines), index, run, run_closed, left, right))
                    _claim_segments(segment_owner, run, len(lines) - 1)
        if removed > 0.0:
            notes.append(
                f"{spec.name}: {removed:.1f} m of face line along the domain boundary "
                "left to the boundary"
            )
    return lines, shared, tuple(notes)


def _segment_keys(coords: np.ndarray) -> list[tuple[int, int]]:
    """The node keys of each segment, smaller first: one key pair per undirected segment."""
    keys = vertex_keys(coords).tolist()
    return [(min(a, b), max(a, b)) for a, b in zip(keys[:-1], keys[1:], strict=True)]


def _claim_segments(
    segment_owner: dict[tuple[int, int], int], coords: np.ndarray, gid: int
) -> None:
    """Record the segments of line *gid*, so a later face line leaves them to it."""
    for pair in _segment_keys(coords):
        segment_owner.setdefault(pair, gid)


def _own_runs(
    coords: np.ndarray, closed: bool, segment_owner: dict[tuple[int, int], int]
) -> list[tuple[int, np.ndarray, bool]]:
    """The runs of a face line: ``(owner, coords, closed)``, owner ``-1`` where it is its own.

    A run whose segments an earlier line already holds carries that line as
    its owner. A ring with no such segment stays one closed run.
    """
    owner = np.asarray(
        [segment_owner.get(pair, -1) for pair in _segment_keys(coords)], dtype=np.int64
    )
    if (owner < 0).all():
        return [(-1, coords, closed)]
    count = owner.size
    order = np.arange(count)
    if closed:
        starts = np.flatnonzero(owner != np.roll(owner, 1))
        order = np.roll(order, -int(starts[0])) if starts.size else order
    runs: list[tuple[int, list[int]]] = []
    for k in order.tolist():
        if runs and runs[-1][0] == owner[k]:
            runs[-1][1].append(k)
        else:
            runs.append((int(owner[k]), [k]))
    return [(gid, np.vstack([coords[run], coords[run[-1] + 1]]), False) for gid, run in runs]


def _off_boundary(
    coords: np.ndarray, closed: bool, boundary: BaseGeometry, tol: float
) -> tuple[list[tuple[np.ndarray, bool]], float]:
    """The runs of a line off the domain boundary, and the length removed."""
    start, stop = coords[:-1], coords[1:]
    probe = np.vstack([start, stop, 0.5 * (start + stop)])
    near = shapely.distance(shapely.points(probe), boundary) <= tol
    count = len(start)
    on = near[:count] & near[count : 2 * count] & near[2 * count :]
    if not on.any():
        return [(coords, closed)], 0.0
    removed = float(np.hypot(*(stop - start)[on].T).sum())
    order = np.arange(count)
    if closed:
        order = np.roll(order, -(int(np.argmax(on)) + 1))
    runs: list[tuple[np.ndarray, bool]] = []
    current: list[int] = []
    for segment in [*order.tolist(), -1]:
        if segment >= 0 and not on[segment]:
            current.append(segment)
            continue
        if current:
            runs.append((np.vstack([coords[current], coords[current[-1] + 1]]), False))
        current = []
    return runs, removed
