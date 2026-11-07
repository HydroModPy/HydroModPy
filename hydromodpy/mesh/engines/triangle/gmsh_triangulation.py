"""Constrained Delaunay triangulation of a mesh request by gmsh.

The driver nodes the family lines with the domain boundary in shapely, hands
gmsh one point per vertex and one straight curve per segment (``geo`` kernel,
no OCC fragment), embeds the interior segments in the plane surface and meshes
it under the size field of the request. Coordinates are shifted to an origin
rounded to the kilometer while gmsh runs, so its tolerances act on small
numbers.

A cell size of the request is the side of the square of the same mean area.
gmsh reads a size as an edge length, so the driver multiplies every size it
hands to gmsh by :data:`MESH_SIZE_PER_CELL_SIZE`: a triangle then has the area
of the square of the cell size. For the same reason it resamples the family
lines of a sized request at that edge length, since the planner cuts them at
one vertex per cell size.

``gmsh`` is imported inside :func:`triangulate`: resolving the engine does not
need the ``mesh`` extra, building with it does.
"""

from __future__ import annotations

import dataclasses
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient
from shapely.strtree import STRtree

from hydromodpy.core.exceptions import MeshError, MeshGenerationError, MeshRequestError
from hydromodpy.mesh.planar.geometry import polygon_rings, vertex_keys
from hydromodpy.mesh.request import BARRIER_FAMILY, LineFamilySpec, SizeField
from hydromodpy.mesh.resample import kink_pieces, resample_families

if TYPE_CHECKING:
    from types import ModuleType

    from hydromodpy.mesh.request import MeshRequest

__all__ = ["ALGORITHMS", "MESH_SIZE_PER_CELL_SIZE", "Triangulation", "require_gmsh", "triangulate"]

ALGORITHMS: dict[str, int] = {"meshadapt": 1, "delaunay": 5, "frontal": 6}
"""gmsh ``Mesh.Algorithm`` number of each ``[mesh.triangle] algorithm`` value."""

MESH_SIZE_PER_CELL_SIZE: dict[str, float] = {"meshadapt": 1.58, "delaunay": 1.62, "frontal": 1.52}
"""gmsh mesh size per cell size of each algorithm [-].

An equilateral triangle of side ``s`` has the area ``(sqrt(3) / 4) s^2``, so the
area ``l^2`` needs ``s = sqrt(4 / sqrt(3)) l = 1.52 l``. Frontal-Delaunay meets
its mesh size. Delaunay and MeshAdapt lay edges about 5 and 3 per cent shorter
than asked, so their factors are measured: on a uniform 10 km square at 100 m
and 200 m, the triangle count is ``A / l^2`` within 3 per cent for each algorithm.
"""

_ORIGIN_STEP_M = 1000.0
"""The shift origin is the domain center rounded to this step [m]."""

_ON_LINE_M = 1.0e-6
"""A noded vertex within this distance [m] of a line splits it."""

_MAX_FIELD_NODES = 2_000_000
"""Largest node count of the structured size field handed to gmsh."""

_GMSH_LINE = 1
_GMSH_TRIANGLE = 2


@dataclass(frozen=True, eq=False)
class Triangulation:
    """A triangulation, the family lines it embeds and the mesh edges of each line.

    ``lines`` are the families of the request with the lines gmsh embedded.
    ``line_edges[(family, index)]`` holds the vertex pairs of the edges along
    line ``index`` of ``family``, in the order and orientation of the line.
    """

    vertices: np.ndarray
    triangles: np.ndarray
    lines: tuple[LineFamilySpec, ...]
    line_edges: dict[tuple[str, int], np.ndarray]


@dataclass
class LineGraph:
    """A noded planar straight-line graph: merged vertices and polylines of vertex ids."""

    vertices: list[tuple[float, float]]
    rings: list[list[int]]
    lines: dict[tuple[str, int], list[int]]


def require_gmsh() -> ModuleType:
    """Import and return ``gmsh``, naming the extra that installs it when it is missing."""
    try:
        import gmsh
    except ModuleNotFoundError as exc:
        raise MeshError(
            "the triangle and voronoi engines need gmsh: install the 'mesh' extra "
            "(pip install 'hydromodpy[mesh]')"
        ) from exc
    return gmsh


def _algorithm(request: MeshRequest) -> str:
    """The ``[mesh.triangle] algorithm`` the request names, ``delaunay`` when it names none."""
    return str(request.options.get("algorithm", "delaunay"))


def _lines_at_edge_length(request: MeshRequest, scale: float) -> tuple[LineFamilySpec, ...]:
    """The family lines resampled on the size field times *scale*, the gmsh edge length.

    The barrier corners stay vertices. A request without a size field keeps its
    lines: gmsh splits each segment at its own mesh size.
    """
    if request.size_field is None or not request.lines:
        return request.lines
    field = request.size_field
    scaled = SizeField(scale * np.asarray(field.values, dtype=float), field.grid)
    corners = [
        piece.coords[0]
        for family in request.lines
        if family.name == BARRIER_FAMILY
        for line in family.lines
        for piece in kink_pieces(line)[1:]
    ]
    resampled = resample_families(
        request.lines,
        domain=request.domain,
        size_field=scaled,
        fixed_points=np.asarray(corners, dtype=float).reshape(-1, 2) if corners else None,
    )
    return resampled.families


def _origin(domain: Polygon) -> np.ndarray:
    xmin, ymin, xmax, ymax = domain.bounds
    centre = np.array([0.5 * (xmin + xmax), 0.5 * (ymin + ymax)])
    return np.round(centre / _ORIGIN_STEP_M) * _ORIGIN_STEP_M


def _node(request: MeshRequest, origin: np.ndarray) -> LineGraph:
    """Split every ring and line at every crossing, then merge vertices on a mm grid."""
    domain = orient(shapely.transform(request.domain, lambda xy: xy - origin), 1.0)
    rings = polygon_rings(domain)
    lines: dict[tuple[str, int], LineString] = {}
    cover = domain.buffer(_ON_LINE_M)
    for family in request.lines:
        for index, line in enumerate(family.lines):
            shifted = shapely.transform(line, lambda xy: xy - origin)
            if not cover.covers(shifted):
                raise MeshRequestError(
                    f"line {index} of family {family.name!r} leaves the mesh domain"
                )
            lines[(family.name, index)] = shifted
    sources = [*rings, *lines.values()]
    noded = shapely.node(shapely.multilinestrings(sources))
    points = shapely.points(np.unique(shapely.get_coordinates(noded), axis=0))
    tree = STRtree(points)

    keys: dict[int, int] = {}
    vertices: list[tuple[float, float]] = []

    def vertex_ids(source: LineString, *, closed: bool) -> list[int]:
        hits = tree.query(source, predicate="dwithin", distance=_ON_LINE_M)
        along = shapely.line_locate_point(source, points[hits])
        coords = shapely.get_coordinates(points[hits])[np.argsort(along, kind="stable")]
        ids: list[int] = []
        for (x, y), key in zip(coords, vertex_keys(coords).tolist(), strict=True):
            if key not in keys:
                keys[key] = len(vertices)
                vertices.append((float(x), float(y)))
            if not ids or ids[-1] != keys[key]:
                ids.append(keys[key])
        if closed:
            ids = ids[:-1] if len(ids) > 1 and ids[-1] == ids[0] else ids
            ids.append(ids[0])
        return ids

    ring_ids = [vertex_ids(ring, closed=True) for ring in rings]
    line_ids = {key: vertex_ids(line, closed=line.is_closed) for key, line in lines.items()}
    for key, ids in line_ids.items():
        if len(ids) < 2:
            raise MeshRequestError(f"line {key[1]} of family {key[0]!r} is shorter than 1 mm")
    return LineGraph(vertices=vertices, rings=ring_ids, lines=line_ids)


def _write_size_field(
    gmsh: ModuleType, size_field: SizeField, scale: float, origin: np.ndarray, scratch: Path
) -> None:
    """Hand the size field times *scale* to gmsh as a ``Structured`` background field.

    The nodes are the pixel centers. A field above :data:`_MAX_FIELD_NODES`
    nodes is coarsened by an integer factor, keeping the minimum of each block.
    """
    grid = size_field.grid
    values = scale * np.asarray(size_field.values, dtype=float)
    factor = max(1, int(np.ceil(np.sqrt(values.size / _MAX_FIELD_NODES))))
    if factor > 1:
        nrow = -(-values.shape[0] // factor)
        ncol = -(-values.shape[1] // factor)
        padded = np.full((nrow * factor, ncol * factor), np.inf)
        padded[: values.shape[0], : values.shape[1]] = values
        values = padded.reshape(nrow, factor, ncol, factor).min(axis=(1, 3))
    dx = grid.dx * factor
    dy = grid.dy * factor
    nrow, ncol = values.shape
    x0 = float(grid.xmin + 0.5 * dx - origin[0])
    y0 = float(grid.ymax - (nrow - 0.5) * dy - origin[1])
    path = scratch / "size_field.txt"
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"{x0!r} {y0!r} 0\n{dx!r} {dy!r} 1\n{ncol} {nrow} 1\n")
        # gmsh reads x outermost, then y from south to north.
        np.savetxt(handle, values[::-1, :].T, fmt="%.17g")
    field_api = gmsh.model.mesh.field
    tag = field_api.add("Structured")
    field_api.setString(tag, "FileName", str(path))
    field_api.setNumber(tag, "TextFormat", 1)
    field_api.setAsBackgroundMesh(tag)


def _mesh_with_gmsh(
    gmsh: ModuleType, request: MeshRequest, graph: LineGraph, origin: np.ndarray, scratch: Path
) -> Triangulation:
    algorithm = _algorithm(request)
    gmsh.option.setNumber("General.Terminal", 0)
    # One thread: gmsh meshes differ from run to run when multi-threaded.
    gmsh.option.setNumber("General.NumThreads", 1)
    gmsh.option.setNumber("Mesh.Algorithm", ALGORITHMS[algorithm])
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.RandomSeed", request.seed)
    gmsh.model.add("hydromodpy_cdt")
    geo = gmsh.model.geo
    for index, (x, y) in enumerate(graph.vertices):
        geo.addPoint(x, y, 0.0, tag=index + 1)

    curves: dict[tuple[int, int], int] = {}

    def curve(a: int, b: int) -> int:
        """Signed tag of the curve from vertex ``a`` to vertex ``b``, created once."""
        if (a, b) in curves:
            return curves[(a, b)]
        if (b, a) in curves:
            return -curves[(b, a)]
        curves[(a, b)] = geo.addLine(a + 1, b + 1)
        return curves[(a, b)]

    loops = [
        geo.addCurveLoop([curve(a, b) for a, b in zip(ring[:-1], ring[1:], strict=True)])
        for ring in graph.rings
    ]
    on_boundary = set(curves.values())
    line_curves = {
        key: [curve(a, b) for a, b in zip(ids[:-1], ids[1:], strict=True)]
        for key, ids in graph.lines.items()
    }
    surface = geo.addPlaneSurface(loops)
    geo.synchronize()
    embedded = sorted({abs(tag) for tags in line_curves.values() for tag in tags} - on_boundary)
    if embedded:
        gmsh.model.mesh.embed(1, embedded, 2, surface)
    scale = MESH_SIZE_PER_CELL_SIZE[algorithm]
    if request.size_field is not None:
        _write_size_field(gmsh, request.size_field, scale, origin, scratch)
    else:
        gmsh.option.setNumber("Mesh.MeshSizeMin", scale * request.nominal_size_m)
        gmsh.option.setNumber("Mesh.MeshSizeMax", scale * request.nominal_size_m)
    gmsh.model.mesh.generate(2)

    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    order = np.argsort(node_tags)
    node_tags = np.asarray(node_tags, dtype=np.int64)[order]
    xy = np.asarray(coords, dtype=float).reshape(-1, 3)[order, :2]
    _, triangle_nodes = gmsh.model.mesh.getElementsByType(_GMSH_TRIANGLE, surface)
    triangles = np.searchsorted(node_tags, np.asarray(triangle_nodes, dtype=np.int64)).reshape(
        -1, 3
    )
    if triangles.size == 0:
        raise MeshGenerationError("gmsh returned no triangle for the mesh request")
    used, triangles = np.unique(triangles, return_inverse=True)
    triangles = triangles.reshape(-1, 3).astype(np.int64)
    index_of_tag = np.full(int(node_tags.max()) + 1, -1, dtype=np.int64)
    index_of_tag[node_tags[used]] = np.arange(used.size)

    line_edges: dict[tuple[str, int], np.ndarray] = {}
    vertices = np.asarray(graph.vertices, dtype=float)
    for key, tags in line_curves.items():
        ids = graph.lines[key]
        parts = []
        for a, b, signed in zip(ids[:-1], ids[1:], tags, strict=True):
            types, _, nodes = gmsh.model.mesh.getElements(1, abs(signed))
            pairs = np.asarray(nodes[list(types).index(_GMSH_LINE)], dtype=np.int64)
            pairs = index_of_tag[pairs.reshape(-1, 2)]
            parts.append(_ordered_along(pairs, xy[used], vertices[b] - vertices[a]))
        line_edges[key] = np.concatenate(parts)
    if any(np.any(edges < 0) for edges in line_edges.values()):
        raise MeshGenerationError("a family line edge has a vertex outside the triangulation")
    return Triangulation(
        vertices=xy[used] + origin,
        triangles=triangles,
        lines=request.lines,
        line_edges=line_edges,
    )


def _ordered_along(pairs: np.ndarray, xy: np.ndarray, direction: np.ndarray) -> np.ndarray:
    """Orient and order the mesh edges of one straight segment along ``direction``."""
    flip = ((xy[pairs[:, 1]] - xy[pairs[:, 0]]) @ direction) < 0.0
    pairs = np.where(flip[:, None], pairs[:, ::-1], pairs)
    along = xy[pairs].mean(axis=1) @ direction
    return pairs[np.argsort(along, kind="stable")]


def triangulate(request: MeshRequest) -> Triangulation:
    """Triangulate the request domain with every family line embedded as mesh edges."""
    gmsh = require_gmsh()
    scale = MESH_SIZE_PER_CELL_SIZE[_algorithm(request)]
    request = dataclasses.replace(request, lines=_lines_at_edge_length(request, scale))
    origin = _origin(request.domain)
    graph = _node(request, origin)
    gmsh.initialize(interruptible=False)
    try:
        with tempfile.TemporaryDirectory(prefix="hmp_cdt_") as scratch:
            result = _mesh_with_gmsh(gmsh, request, graph, origin, Path(scratch))
    finally:
        gmsh.finalize()
    return result
