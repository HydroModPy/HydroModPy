"""A mesh request is frozen data, and its hash names exactly what it asks for.

The hash moves with every member and with the earlier runs the size field
read. A request that reads no run keeps the hash the code gave it before the
runs were hashed, so the meshes cached for every existing project stay valid.
A request refuses what no engine can mesh, with a message that names the
member; the type of a member is its annotation's, not the request's. A size field is sampled bilinearly between its pixel centres.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString, Polygon, box

from hydromodpy.core.exceptions import MeshError, MeshRequestError
from hydromodpy.spatial.mesh.request import (
    InputTriangulation,
    LineFamilySpec,
    MeshRequest,
    RasterGridSpec,
    SizeField,
)
from tests._helpers.mesh_cases import grid_spec, mesh_request, uniform_size_field

_WKT = 'PROJCS["RGF93 / Lambert-93"]'
"""The CRS text the frozen hash was taken with: it enters the hash."""

_GRID = grid_spec(5, 10, 10.0, xmin=1000.0, ymin=2000.0, crs_wkt=_WKT)
_GRID_BOX = box(_GRID.xmin, _GRID.ymin, _GRID.xmax, _GRID.ymax)
_RIVER = LineFamilySpec("rivers", "cell", (LineString([(1000, 2010), (1100, 2040)]),))


def _grid(**overrides: object) -> RasterGridSpec:
    return dataclasses.replace(_GRID, **overrides)


def _triangulation() -> InputTriangulation:
    return InputTriangulation(
        vertices=np.array([[1000.0, 2000.0], [1100.0, 2000.0], [1100.0, 2050.0], [1000.0, 2050.0]]),
        triangles=np.array([[0, 1, 2], [0, 2, 3]]),
        edge_labels={"river::1": np.array([[0, 2]]), "west": np.array([[3, 0]])},
    )


def _request(**overrides: object) -> MeshRequest:
    """A request of every member; a variant of the grid keeps the domain and the CRS."""
    members: dict[str, object] = dict(
        domain=_GRID_BOX,
        lines=(
            _RIVER,
            LineFamilySpec(
                "geology",
                "face",
                (LineString([(1050, 2000), (1050, 2050)]),),
                zone_left=("granite",),
                zone_right=("schist",),
            ),
        ),
        size_field=uniform_size_field(_GRID, 20.0),
        nominal_size_m=25.0,
        seed=3,
        options={"algorithm": "delaunay", "shape": [5, 10]},
        input_triangulation=_triangulation(),
    )
    members.update(overrides)
    return mesh_request(members.pop("grid", _GRID), **members)


HASH_WITHOUT_RUNS = "5e5315bbed593615f48b1fd3fe18637a5afffe674fef6914f0e606274e36a1f6"
"""The hash of :func:`_request_without_runs` computed with the request of 8071ff47f, which hashed no run."""


def _request_without_runs(**overrides: object) -> MeshRequest:
    members: dict[str, object] = {
        "nominal_size_m": 20.0,
        "lines": (_RIVER,),
        "size_field": uniform_size_field(_GRID, 20.0),
        "seed": 3,
        "options": {"seeds": "generated"},
    }
    members.update(overrides)
    return mesh_request(_GRID, **members)


def test_the_request_is_in_the_crs_of_its_grid() -> None:
    other_wkt = 'PROJCS["WGS 84 / UTM zone 30N"]'

    assert _request().crs_wkt == _WKT
    assert mesh_request(grid_spec(4, 4, 10.0, crs_wkt=other_wkt)).crs_wkt == other_wkt


def test_the_grid_transform_puts_row_0_north() -> None:
    grid = _GRID

    assert grid.transform * (0, 0) == (grid.xmin, grid.ymax)
    assert grid.transform * (grid.ncol, grid.nrow) == pytest.approx((grid.xmax, grid.ymin))


def test_the_request_error_is_a_mesh_error() -> None:
    assert issubclass(MeshRequestError, MeshError)


def test_the_hash_is_a_sha256_hex_and_repeats() -> None:
    first = _request().canonical_hash()

    assert len(first) == 64
    assert int(first, 16) >= 0
    assert _request().canonical_hash() == first


def test_the_hash_ignores_the_order_of_the_options() -> None:
    forward = _request(options={"algorithm": "delaunay", "shape": [5, 10], "seeds": "generated"})
    backward = _request(options={"seeds": "generated", "shape": (5, 10), "algorithm": "delaunay"})

    assert forward.canonical_hash() == backward.canonical_hash()


def test_the_hash_ignores_the_order_of_the_families() -> None:
    request = _request()
    reversed_lines = _request(lines=tuple(reversed(request.lines)))

    assert reversed_lines.canonical_hash() == request.canonical_hash()
    assert [family.name for family in request.lines] == ["geology", "rivers"]


def test_the_hash_ignores_where_the_domain_ring_starts() -> None:
    shifted = Polygon([(1100, 2000), (1100, 2050), (1000, 2050), (1000, 2000)])

    assert _request(domain=shifted).canonical_hash() == _request().canonical_hash()


def _variants() -> dict[str, MeshRequest]:
    base = _request()
    rivers = base.family("rivers")
    geology = base.family("geology")
    assert rivers is not None and geology is not None
    other_wkt = 'PROJCS["WGS 84 / UTM zone 30N"]'
    field = np.full((5, 10), 20.0)
    field[0, 0] = 21.0
    triangulation = _triangulation()
    moved = triangulation.vertices.copy()
    moved[2, 0] += 1.0
    return {
        "domain": _request(domain=box(1000.0, 2000.0, 1090.0, 2050.0)),
        "crs_wkt": _request(
            grid=_grid(crs_wkt=other_wkt),
            size_field=uniform_size_field(_grid(crs_wkt=other_wkt), 20.0),
        ),
        "grid.xmin": _request(grid=_grid(xmin=1000.5, xmax=1100.5)),
        "grid.ymin": _request(grid=_grid(ymin=2000.5, ymax=2050.5)),
        "grid.dx": _request(grid=_grid(dx=5.0, ncol=20)),
        "grid.nrow": _request(grid=_grid(dy=5.0, nrow=10)),
        "line geometry": _request(
            lines=(
                dataclasses.replace(rivers, lines=(LineString([(1000, 2010), (1100, 2041)]),)),
                geology,
            )
        ),
        "line orientation": _request(
            lines=(
                dataclasses.replace(rivers, lines=(LineString([(1100, 2040), (1000, 2010)]),)),
                geology,
            )
        ),
        "family name": _request(lines=(dataclasses.replace(rivers, name="streams"), geology)),
        "family intent": _request(lines=(dataclasses.replace(rivers, intent="face"), geology)),
        "family closed": _request(lines=(dataclasses.replace(rivers, closed=True), geology)),
        "zone_left": _request(lines=(rivers, dataclasses.replace(geology, zone_left=("gneiss",)))),
        "zone_right": _request(
            lines=(rivers, dataclasses.replace(geology, zone_right=("gneiss",)))
        ),
        "no families": _request(lines=()),
        "size field values": _request(size_field=SizeField(field, _GRID)),
        "no size field": _request(size_field=None),
        "nominal size": _request(nominal_size_m=25.5),
        "seed": _request(seed=4),
        "option value": _request(options={"algorithm": "frontal", "shape": [5, 10]}),
        "option set": _request(options={"algorithm": "delaunay"}),
        "triangulation vertices": _request(
            input_triangulation=InputTriangulation(
                vertices=moved,
                triangles=triangulation.triangles,
                edge_labels=dict(triangulation.edge_labels),
            )
        ),
        "triangulation labels": _request(
            input_triangulation=InputTriangulation(
                vertices=triangulation.vertices,
                triangles=triangulation.triangles,
                edge_labels={"river::2": np.array([[0, 2]]), "west": np.array([[3, 0]])},
            )
        ),
        "no triangulation": _request(input_triangulation=None),
        "source runs": _request(source_runs=("a" * 32,)),
    }


@pytest.mark.parametrize("member", sorted(_variants()))
def test_the_hash_moves_with_every_member(member: str) -> None:
    assert _variants()[member].canonical_hash() != _request().canonical_hash()


def test_every_variant_hashes_differently_from_the_others() -> None:
    hashes = [request.canonical_hash() for request in _variants().values()]

    assert len(set(hashes)) == len(hashes)


def test_the_notes_are_not_hashed() -> None:
    assert _request(notes=("a note",)).canonical_hash() == _request().canonical_hash()


def test_a_request_that_reads_no_run_keeps_its_hash() -> None:
    assert _request_without_runs().source_runs == ()
    assert _request_without_runs().canonical_hash() == HASH_WITHOUT_RUNS
    assert _request_without_runs(source_runs=[]).canonical_hash() == HASH_WITHOUT_RUNS


def test_the_runs_are_hashed_as_a_sorted_set() -> None:
    request = _request_without_runs(source_runs=("b" * 32, "a" * 32, "b" * 32))

    assert request.source_runs == ("a" * 32, "b" * 32)
    assert (
        request.canonical_hash()
        == _request_without_runs(source_runs=["a" * 32, "b" * 32]).canonical_hash()
    )
    assert request.canonical_hash() != HASH_WITHOUT_RUNS
    assert (
        request.canonical_hash() != _request_without_runs(source_runs=("a" * 32,)).canonical_hash()
    )


def test_the_arrays_of_a_request_are_copies_and_read_only() -> None:
    values = np.full((5, 10), 20.0)
    field = SizeField(values, _GRID)
    values[0, 0] = 99.0

    assert field.values[0, 0] == 20.0
    with pytest.raises(ValueError):
        field.values[0, 0] = 1.0
    triangulation = _triangulation()
    with pytest.raises(ValueError):
        triangulation.vertices[0, 0] = 0.0
    with pytest.raises(ValueError):
        triangulation.edge_labels["west"][0, 0] = 1
    with pytest.raises(TypeError):
        triangulation.edge_labels["new"] = np.array([[0, 1]])  # type: ignore[index]


def test_the_options_are_read_only_json() -> None:
    request = _request(options={"shape": [5, 10], "nested": {"b": 1, "a": np.float64(0.5)}})

    assert request.options["shape"] == (5, 10)
    assert dict(request.options["nested"]) == {"a": 0.5, "b": 1}
    with pytest.raises(TypeError):
        request.options["shape"] = (1, 1)  # type: ignore[index]


def test_the_request_is_frozen() -> None:
    request = _request()

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.seed = 1  # type: ignore[misc]


def test_a_grid_keeps_the_bounds_it_was_given() -> None:
    grid = _grid(ymin=2000.0000000001, ymax=2050.0)

    assert grid.ymin == 2000.0000000001


def test_a_grid_from_a_raster_support_takes_its_exact_bounds_and_the_crs() -> None:
    support = SimpleNamespace(
        xmin=0.0, xmax=300.0, ymin=-75.0, ymax=0.0, dx=None, dy=25.0, nrows=3, ncols=4
    )

    grid = RasterGridSpec.from_raster_support(support, crs_wkt=_WKT)

    assert (grid.xmin, grid.xmax, grid.ymin, grid.ymax) == (0.0, 300.0, -75.0, 0.0)
    assert (grid.dx, grid.dy, grid.nrow, grid.ncol) == (75.0, 25.0, 3, 4)
    assert grid.crs_wkt == _WKT


def test_a_minimal_request_takes_the_defaults() -> None:
    request = MeshRequest(
        domain=box(1000.0, 2000.0, 1100.0, 2050.0), grid=_GRID, nominal_size_m=10.0
    )

    assert request.lines == ()
    assert request.size_field is None
    assert request.seed == 0
    assert dict(request.options) == {}
    assert request.input_triangulation is None
    assert request.family("rivers") is None


_LINE = LineString([(0, 0), (1, 1)])
_THREE = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
_NAN = float("nan")


def _support_without_ymin() -> RasterGridSpec:
    support = SimpleNamespace(
        xmin=0.0, xmax=300.0, ymin=None, ymax=0.0, dx=75.0, dy=25.0, nrows=3, ncols=4
    )
    return RasterGridSpec.from_raster_support(support, crs_wkt=_WKT)


def _triangles(vertices: np.ndarray, triangles: list, **labels: list) -> InputTriangulation:
    return InputTriangulation(
        vertices=vertices,
        triangles=np.array(triangles, dtype=np.int64).reshape(-1, 3),
        edge_labels={name: np.array(edges) for name, edges in labels.items()},
    )


_REFUSALS: dict[str, tuple[Callable[[], object], str]] = {
    "grid step of zero": (lambda: _grid(dx=0.0, ncol=10), r"grid steps must be > 0 m"),
    "grid step off the bounds": (lambda: _grid(dx=11.0), r"10 cells of 11.0 m span"),
    "grid of no row": (lambda: _grid(nrow=0), r"grid y: 0 cells of 10.0 m span 0.0 m"),
    "grid of half a column": (lambda: _grid(ncol=2.5), r"grid x: 2 cells of 10.0 m span"),
    "grid of empty x bounds": (lambda: _grid(xmax=1000.0), r"grid x bounds are empty"),
    "grid bound not finite": (lambda: _grid(ymin=_NAN), r"ymin must be finite"),
    "raster support without ymin": (_support_without_ymin, r"the raster support lacks ymin"),
    "size field of another shape": (
        lambda: SizeField(np.full((10, 5), 20.0), _GRID),
        r"shape \(10, 5\), the grid is \(5, 10\)",
    ),
    "size field with a zero": (
        lambda: SizeField(np.zeros((5, 10)), _GRID),
        r"size field values must be finite and > 0 m",
    ),
    "family with no name": (lambda: LineFamilySpec("", "cell", (_LINE,)), r"non-empty name"),
    "family line of zero length": (
        lambda: LineFamilySpec("rivers", "cell", (LineString([(0, 0), (0, 0)]),)),
        r"every line must be a non-empty LineString",
    ),
    "two zones for one line": (
        lambda: LineFamilySpec(
            "geology", "face", (_LINE,), zone_left=("a", "b"), zone_right=("c", "d")
        ),
        r"zone_left names 2 zones for 1 lines",
    ),
    "zones on one side only": (
        lambda: LineFamilySpec("geology", "face", (_LINE,), zone_left=("a",)),
        r"given together or not at all",
    ),
    "triangle beyond the vertices": (
        lambda: _triangles(_THREE, [[0, 1, 3]]),
        r"triangles index outside the vertices",
    ),
    "edge beyond the vertices": (
        lambda: _triangles(_THREE, [[0, 1, 2]], x=[[0, 5]]),
        r"edge_labels\['x'\] indexes outside the vertices",
    ),
    "vertices of one coordinate": (
        lambda: _triangles(_THREE[:, :1], [[0, 1, 2]]),
        r"vertices must have shape \(n, 2\)",
    ),
    "vertex not finite": (
        lambda: _triangles(np.vstack([_THREE[:2], [[_NAN, 1.0]]]), [[0, 1, 2]]),
        r"vertices must be finite",
    ),
    "triangulation without a triangle": (lambda: _triangles(_THREE, []), r"has no triangle"),
    "empty domain": (lambda: _request(domain=Polygon()), r"non-empty shapely Polygon"),
    "self-crossing domain": (
        lambda: _request(domain=Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])),
        r"valid polygon with an area > 0",
    ),
    "two families of one name": (
        lambda: _request(lines=(_RIVER, dataclasses.replace(_RIVER, intent="face"))),
        r"line families named twice: rivers",
    ),
    "size field in another CRS": (
        lambda: _request(size_field=uniform_size_field(_grid(crs_wkt='PROJCS["other"]'), 20.0)),
        r"the size field and the request name different CRS",
    ),
    "nominal size of zero": (
        lambda: _request(nominal_size_m=0.0),
        r"nominal_size_m must be finite and > 0 m",
    ),
    "infinite nominal size": (
        lambda: _request(nominal_size_m=float("inf")),
        r"nominal_size_m must be finite and > 0 m",
    ),
    "option that is no JSON": (
        lambda: _request(options={"path": object()}),
        r"options\['path'\] must be a JSON value",
    ),
    "option not finite": (
        lambda: _request(options={"tolerance": _NAN}),
        r"options\['tolerance'\] must be finite",
    ),
    "option of an integer key": (
        lambda: _request(options={1: "integer key"}),
        r"options keys must be strings",
    ),
    "empty run": (
        lambda: _request_without_runs(source_runs=("",)),
        r"source_runs must be a sequence of sim ids",
    ),
    "blank run": (
        lambda: _request_without_runs(source_runs=(" ",)),
        r"source_runs must be a sequence of sim ids",
    ),
}


@pytest.mark.parametrize("case", list(_REFUSALS))
def test_a_request_that_cannot_be_meshed_is_refused(case: str) -> None:
    build, message = _REFUSALS[case]

    with pytest.raises(MeshRequestError, match=message):
        build()


def test_bilinear_sampling_is_exact_on_a_plane() -> None:
    grid = grid_spec(8, 12, 10.0, xmin=1000.0, ymin=5000.0)
    rows, cols = np.mgrid[0:8, 0:12]
    x = grid.xmin + (cols + 0.5) * grid.dx
    y = grid.ymax - (rows + 0.5) * grid.dy
    field = SizeField(values=10.0 + 0.01 * (x - 1000.0) + 0.02 * (y - 5000.0), grid=grid)
    points = np.array([[1012.0, 5013.0], [1077.3, 5041.9], [1105.0, 5065.0]])
    expected = 10.0 + 0.01 * (points[:, 0] - 1000.0) + 0.02 * (points[:, 1] - 5000.0)
    np.testing.assert_allclose(field.sample(points), expected, rtol=1e-12)
