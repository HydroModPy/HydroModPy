"""The mesh request: everything a mesh engine reads, as plain frozen data.

An engine reads no file and no config. The planner turns ``[mesh]`` and the
project inputs into one :class:`MeshRequest`; the engine turns that request into
a ``PlanarCellMesh``. ``MeshRequest.canonical_hash`` names the request: two
requests with the same hash ask for the same mesh, which is what the product
store and the run provenance rely on.

Arrays handed to these classes are copied and made read-only, so a request
cannot change after its hash was taken. A request refuses what an engine
cannot mesh: a grid whose steps, shape and bounds disagree, a size that is not
finite and positive, an invalid domain, a catchment that is not one valid
polygon, a family named twice, a line without length, zones that do not match
the lines, an index outside the vertices. It does not check the type of the
other members, which their annotation states: the config refuses what a user
writes, and the planner fills each member.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Protocol

import numpy as np
import shapely
from scipy.ndimage import map_coordinates
from shapely.geometry import LineString, Polygon

from hydromodpy.core.exceptions import MeshRequestError

if TYPE_CHECKING:
    from rasterio.transform import Affine

    from hydromodpy.catchment.raster_support import RasterSupport

__all__ = [
    "BARRIER_FAMILY",
    "FAMILY_NAMES",
    "InputTriangulation",
    "LineFamilySpec",
    "LineIntent",
    "MeshRequest",
    "RasterGridSpec",
    "SizeField",
]

LineIntent = Literal["cell", "face"]

BARRIER_FAMILY = "barriers"
"""The face family of the flow barriers: an engine follows its corners and free ends,
and a staircase engine bars the faces its lines cross."""

FAMILY_NAMES: frozenset[str] = frozenset(
    {"rivers", "geology", "lakes", "barriers", "watershed_boundary"}
)
"""The line families ``[mesh.families]`` names, the only ones an engine may ignore.

The keys of ``MeshFamiliesConfig`` are these names, and a test holds the two equal.
"""

_EMPTY_OPTIONS: Mapping[str, object] = MappingProxyType({})

_GRID_SPACING_RTOL = 1.0e-6
"""Largest relative gap between ``n * step`` and the extent of a grid."""


class _Digest(Protocol):
    def update(self, data: bytes, /) -> None: ...


def _frozen_array(values: object, dtype: str, shape_tail: tuple[int, ...], name: str) -> np.ndarray:
    """Copy *values* to a C-contiguous little-endian read-only array of fixed trailing shape."""
    array = np.array(values, dtype=dtype, copy=True, order="C")
    if array.ndim != 1 + len(shape_tail) or array.shape[1:] != shape_tail:
        raise MeshRequestError(
            f"{name} must have shape (n, {', '.join(map(str, shape_tail))}), got {array.shape}"
        )
    array.setflags(write=False)
    return array


def _wkb(geometry: object) -> bytes:
    """Little-endian 2D WKB, the byte form the hash reads."""
    return shapely.to_wkb(geometry, hex=False, output_dimension=2, byte_order=1)


@dataclass(frozen=True, kw_only=True)
class RasterGridSpec:
    """The DEM grid a request lives on: row 0 north, cells ``dx`` by ``dy`` meters.

    ``xmin``, ``xmax``, ``ymin``, ``ymax`` are the exact bounds of the raster
    support. They are carried as given and not recomputed from the steps:
    ``ymax - nrow * dy`` is not ``ymin`` in floating point, and the regular
    engine places its vertices from ``ymin``.
    """

    xmin: float
    xmax: float
    ymin: float
    ymax: float
    dx: float
    dy: float
    nrow: int
    ncol: int
    crs_wkt: str

    def __post_init__(self) -> None:
        """Refuse a grid whose steps, shape and bounds disagree.

        A count below one cell spans no bound, so the spacing check refuses it.
        """
        for name in ("xmin", "xmax", "ymin", "ymax", "dx", "dy"):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise MeshRequestError(f"RasterGridSpec.{name} must be finite, got {value!r}")
            object.__setattr__(self, name, value)
        for name in ("nrow", "ncol"):
            object.__setattr__(self, name, int(getattr(self, name)))
        if self.dx <= 0.0 or self.dy <= 0.0:
            raise MeshRequestError(f"grid steps must be > 0 m, got dx={self.dx}, dy={self.dy}")
        for axis, low, high, step, count in (
            ("x", self.xmin, self.xmax, self.dx, self.ncol),
            ("y", self.ymin, self.ymax, self.dy, self.nrow),
        ):
            extent = high - low
            if extent <= 0.0:
                raise MeshRequestError(f"grid {axis} bounds are empty: [{low}, {high}]")
            if abs(count * step - extent) > _GRID_SPACING_RTOL * extent:
                raise MeshRequestError(
                    f"grid {axis}: {count} cells of {step} m span {count * step} m, "
                    f"the bounds span {extent} m"
                )

    @property
    def transform(self) -> Affine:
        """The affine transform of the grid, row 0 north, as rasterio reads it."""
        from rasterio.transform import Affine

        return Affine(self.dx, 0.0, self.xmin, 0.0, -self.dy, self.ymax)

    @classmethod
    def from_raster_support(cls, support: RasterSupport, *, crs_wkt: str) -> RasterGridSpec:
        """The grid of a complete raster support; a missing step is extent / count."""
        missing = [
            key
            for key in ("xmin", "xmax", "ymin", "ymax", "nrows", "ncols")
            if getattr(support, key) is None
        ]
        if missing:
            raise MeshRequestError(f"the raster support lacks {', '.join(missing)}")
        ncol = int(support.ncols)
        nrow = int(support.nrows)
        return cls(
            xmin=support.xmin,
            xmax=support.xmax,
            ymin=support.ymin,
            ymax=support.ymax,
            dx=support.dx or (support.xmax - support.xmin) / ncol,
            dy=support.dy or (support.ymax - support.ymin) / nrow,
            nrow=nrow,
            ncol=ncol,
            crs_wkt=crs_wkt,
        )

    def hash_bytes(self) -> bytes:
        """Fixed-width bytes of every member, the form the request hash reads."""
        head = struct.pack(
            "<6d2q",
            self.xmin,
            self.xmax,
            self.ymin,
            self.ymax,
            self.dx,
            self.dy,
            self.nrow,
            self.ncol,
        )
        return head + self.crs_wkt.encode("utf-8")


@dataclass(frozen=True, eq=False)
class SizeField:
    """Target cell size ``h(x)`` in meters on a grid, row 0 north."""

    values: np.ndarray
    grid: RasterGridSpec

    def __post_init__(self) -> None:
        """Freeze the values and refuse a shape, a NaN or a size <= 0."""
        values = np.array(self.values, dtype="<f8", copy=True, order="C")
        if values.shape != (self.grid.nrow, self.grid.ncol):
            raise MeshRequestError(
                f"size field values have shape {values.shape}, "
                f"the grid is {(self.grid.nrow, self.grid.ncol)}"
            )
        if not np.all(np.isfinite(values)) or np.any(values <= 0.0):
            raise MeshRequestError("size field values must be finite and > 0 m")
        values.setflags(write=False)
        object.__setattr__(self, "values", values)

    def sample(self, xy: np.ndarray) -> np.ndarray:
        """Bilinear ``h`` at points ``(n, 2)`` from the pixel centers, held constant past the edge."""
        points = np.asarray(xy, dtype=float).reshape(-1, 2)
        grid = self.grid
        cols = (points[:, 0] - grid.xmin) / grid.dx - 0.5
        rows = (grid.ymax - points[:, 1]) / grid.dy - 0.5
        return map_coordinates(self.values, [rows, cols], order=1, mode="nearest")


@dataclass(frozen=True)
class LineFamilySpec:
    """One family of lines and the intent the engine honors on them.

    ``intent = "cell"``: the cells along a line form ordered chains (rivers).
    ``intent = "face"``: mesh faces follow the line (contacts, lake shores).
    ``zone_left`` and ``zone_right`` name the zone on each side of each oriented
    line; both are empty when the family separates no zones. ``closed`` states
    that the lines are rings (lake shores, catchment boundary).
    """

    name: str
    intent: LineIntent
    lines: tuple[LineString, ...]
    zone_left: tuple[str, ...] = ()
    zone_right: tuple[str, ...] = ()
    closed: bool = False

    def __post_init__(self) -> None:
        """Refuse an unnamed family, a line without length or a zone count mismatch."""
        if not self.name.strip():
            raise MeshRequestError("a line family needs a non-empty name")
        lines = tuple(self.lines)
        for line in lines:
            if line.is_empty or line.length <= 0.0:
                raise MeshRequestError(
                    f"line family {self.name!r}: every line must be a non-empty LineString"
                )
        object.__setattr__(self, "lines", lines)
        for side in ("zone_left", "zone_right"):
            zones = tuple(str(zone) for zone in getattr(self, side))
            if zones and len(zones) != len(lines):
                raise MeshRequestError(
                    f"line family {self.name!r}: {side} names {len(zones)} zones "
                    f"for {len(lines)} lines"
                )
            object.__setattr__(self, side, zones)
        if bool(self.zone_left) != bool(self.zone_right):
            raise MeshRequestError(
                f"line family {self.name!r}: zone_left and zone_right are given together or not at all"
            )
        object.__setattr__(self, "closed", bool(self.closed))

    def hash_bytes(self) -> bytes:
        """Name, intent, closure, then each line as WKB with its two zones."""
        digest = hashlib.sha256()
        _feed(digest, self.name.encode("utf-8"))
        _feed(digest, self.intent.encode("utf-8"))
        _feed(digest, b"1" if self.closed else b"0")
        for index, line in enumerate(self.lines):
            _feed(digest, _wkb(line))
            _feed(digest, self.zone_left[index].encode("utf-8") if self.zone_left else b"")
            _feed(digest, self.zone_right[index].encode("utf-8") if self.zone_right else b"")
        return digest.digest()


@dataclass(frozen=True, eq=False)
class InputTriangulation:
    """A triangulation read from a ``.msh`` file, used instead of a generated one.

    ``edge_labels`` maps a physical line group name (``river::<id>``,
    ``interface::<a>::<b>``, a side name) to its edges as vertex index pairs.
    """

    vertices: np.ndarray
    triangles: np.ndarray
    edge_labels: Mapping[str, np.ndarray]

    def __post_init__(self) -> None:
        """Freeze the arrays and refuse an index outside the vertices."""
        vertices = _frozen_array(self.vertices, "<f8", (2,), "InputTriangulation.vertices")
        triangles = _frozen_array(self.triangles, "<i8", (3,), "InputTriangulation.triangles")
        if not np.all(np.isfinite(vertices)):
            raise MeshRequestError("InputTriangulation.vertices must be finite")
        if len(triangles) == 0:
            raise MeshRequestError("InputTriangulation has no triangle")
        n_vertices = len(vertices)
        if triangles.min() < 0 or triangles.max() >= n_vertices:
            raise MeshRequestError("InputTriangulation.triangles index outside the vertices")
        labels: dict[str, np.ndarray] = {}
        for name in sorted(self.edge_labels):
            edges = _frozen_array(
                self.edge_labels[name], "<i8", (2,), f"InputTriangulation.edge_labels[{name!r}]"
            )
            if len(edges) and (edges.min() < 0 or edges.max() >= n_vertices):
                raise MeshRequestError(
                    f"InputTriangulation.edge_labels[{name!r}] indexes outside the vertices"
                )
            labels[str(name)] = edges
        object.__setattr__(self, "vertices", vertices)
        object.__setattr__(self, "triangles", triangles)
        object.__setattr__(self, "edge_labels", MappingProxyType(labels))

    def hash_bytes(self) -> bytes:
        """Vertex and triangle bytes, then each label and its edges in name order."""
        digest = hashlib.sha256()
        _feed(digest, self.vertices.tobytes())
        _feed(digest, self.triangles.tobytes())
        for name, edges in self.edge_labels.items():
            _feed(digest, name.encode("utf-8"))
            _feed(digest, edges.tobytes())
        return digest.digest()


@dataclass(frozen=True, eq=False, kw_only=True)
class MeshRequest:
    """What to mesh, how fine, and with which lines; the only input of an engine.

    ``lines`` is stored sorted by family name, so the order a planner assembled
    the families in never reaches the hash. ``options`` carries the DEV options
    of the engine (``algorithm``, ``seeds``, ``shape``, ...) as a read-only
    mapping of JSON values. ``notes`` are the planner's statements about what it
    left out or kept whole; they travel to the QA of the mesh and are not hashed.
    ``source_runs`` holds the ``sim_id`` of each earlier run whose result shaped
    the size field, sorted: the mesh depends on those runs, so they are hashed,
    and another run gives another request even where the sizes agree.
    ``catchment`` is the outline of the catchment the outlet closes. The planner
    fills it for an engine that meshes the catchment as one cell (a lumped
    engine) and leaves it None for every other engine, so their hash does not
    read it.
    """

    domain: Polygon
    grid: RasterGridSpec
    nominal_size_m: float
    lines: tuple[LineFamilySpec, ...] = ()
    size_field: SizeField | None = None
    seed: int = 0
    options: Mapping[str, object] = field(default_factory=lambda: _EMPTY_OPTIONS)
    input_triangulation: InputTriangulation | None = None
    notes: tuple[str, ...] = ()
    source_runs: tuple[str, ...] = ()
    catchment: Polygon | None = None

    def __post_init__(self) -> None:
        """Refuse what no engine can mesh, then sort the lines and freeze the options."""
        if self.domain.is_empty:
            raise MeshRequestError("the mesh domain must be a non-empty shapely Polygon")
        if not self.domain.is_valid or self.domain.area <= 0.0:
            raise MeshRequestError("the mesh domain must be a valid polygon with an area > 0")
        lines = tuple(sorted(self.lines, key=lambda family: family.name))
        names = [family.name for family in lines]
        duplicated = sorted({name for name in names if names.count(name) > 1})
        if duplicated:
            raise MeshRequestError(f"line families named twice: {', '.join(duplicated)}")
        object.__setattr__(self, "lines", lines)
        if self.size_field is not None and self.size_field.grid.crs_wkt != self.crs_wkt:
            raise MeshRequestError("the size field and the request name different CRS")
        size = float(self.nominal_size_m)
        if not math.isfinite(size) or size <= 0.0:
            raise MeshRequestError(f"nominal_size_m must be finite and > 0 m, got {size!r}")
        object.__setattr__(self, "nominal_size_m", size)
        object.__setattr__(self, "seed", int(self.seed))
        object.__setattr__(self, "options", _freeze_options(self.options, "options"))
        object.__setattr__(self, "notes", tuple(self.notes))
        if not all(run.strip() for run in self.source_runs):
            raise MeshRequestError("MeshRequest.source_runs must be a sequence of sim ids")
        object.__setattr__(self, "source_runs", tuple(sorted(set(self.source_runs))))
        if self.catchment is not None:
            _check_catchment(self.catchment)

    @property
    def crs_wkt(self) -> str:
        """The CRS of the request, the one of its DEM grid."""
        return self.grid.crs_wkt

    def family(self, name: str) -> LineFamilySpec | None:
        """The line family named *name*, or ``None``."""
        return next((family for family in self.lines if family.name == name), None)

    def canonical_hash(self) -> str:
        """sha256 hex of every member, each framed by its length.

        The domain enters in its normalized form (ring start and orientation do
        not change the area to mesh); lines keep their orientation and order,
        since both decide which cell sits left of a line and how a chain runs.
        The source runs enter only when there are some, so the hash of a
        request that reads no run does not depend on them, and the meshes
        cached for such requests stay valid. The catchment enters the same way,
        only when there is one, in its normalized form.
        """
        digest = hashlib.sha256()
        _feed(digest, b"hydromodpy.mesh.request/1")
        _feed(digest, _wkb(shapely.normalize(self.domain)))
        _feed(digest, self.crs_wkt.encode("utf-8"))
        _feed(digest, self.grid.hash_bytes())
        _feed(digest, struct.pack("<q", len(self.lines)))
        for family in self.lines:
            _feed(digest, family.hash_bytes())
        if self.size_field is None:
            _feed(digest, b"")
        else:
            _feed(digest, self.size_field.grid.hash_bytes())
            _feed(digest, self.size_field.values.tobytes())
        _feed(digest, struct.pack("<d", self.nominal_size_m))
        _feed(digest, struct.pack("<q", self.seed))
        _feed(digest, _options_json(self.options).encode("utf-8"))
        if self.input_triangulation is None:
            _feed(digest, b"")
        else:
            _feed(digest, self.input_triangulation.hash_bytes())
        if self.source_runs:
            _feed(digest, b"source_runs")
            _feed(digest, struct.pack("<q", len(self.source_runs)))
            for run in self.source_runs:
                _feed(digest, run.encode("utf-8"))
        if self.catchment is not None:
            _feed(digest, b"catchment")
            _feed(digest, _wkb(shapely.normalize(self.catchment)))
        return digest.hexdigest()


def _check_catchment(catchment: object) -> None:
    """Refuse a catchment outline that is not one valid polygon with an area."""
    if not isinstance(catchment, Polygon) or catchment.is_empty:
        raise MeshRequestError("MeshRequest.catchment must be one non-empty shapely Polygon")
    if not catchment.is_valid or catchment.area <= 0.0:
        raise MeshRequestError("MeshRequest.catchment must be a valid polygon with an area > 0")


def _feed(digest: _Digest, chunk: bytes) -> None:
    """Feed one length-prefixed chunk, so two members never run into each other."""
    digest.update(struct.pack("<Q", len(chunk)))
    digest.update(chunk)


def _freeze_value(value: object, where: str) -> object:
    """A JSON value as an immutable one: tuples for arrays, read-only mappings for objects."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        if not math.isfinite(float(value)):
            raise MeshRequestError(f"{where} must be finite, got {value!r}")
        return float(value)
    if isinstance(value, Mapping):
        return _freeze_options(value, where)
    if isinstance(value, (Sequence, np.ndarray)) and not isinstance(value, (bytes, bytearray)):
        return tuple(_freeze_value(item, f"{where}[{index}]") for index, item in enumerate(value))
    raise MeshRequestError(f"{where} must be a JSON value, got {type(value).__name__}")


def _freeze_options(options: Mapping[str, object], where: str) -> Mapping[str, object]:
    frozen: dict[str, object] = {}
    for key in sorted(options, key=str):
        if not isinstance(key, str):
            raise MeshRequestError(f"{where} keys must be strings, got {key!r}")
        frozen[key] = _freeze_value(options[key], f"{where}[{key!r}]")
    return MappingProxyType(frozen)


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _options_json(options: Mapping[str, object]) -> str:
    return json.dumps(_thaw(options), sort_keys=True, separators=(",", ":"), allow_nan=False)
