"""A mesh request is frozen data, and its hash names exactly what it asks for."""

from __future__ import annotations

import dataclasses
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

_WKT = 'PROJCS["RGF93 / Lambert-93"]'


def _grid(**overrides: object) -> RasterGridSpec:
    values = dict(
        xmin=1000.0,
        xmax=1100.0,
        ymin=2000.0,
        ymax=2050.0,
        dx=10.0,
        dy=10.0,
        nrow=5,
        ncol=10,
        crs_wkt=_WKT,
    )
    values.update(overrides)
    return RasterGridSpec(**values)


def _triangulation() -> InputTriangulation:
    return InputTriangulation(
        vertices=np.array([[1000.0, 2000.0], [1100.0, 2000.0], [1100.0, 2050.0], [1000.0, 2050.0]]),
        triangles=np.array([[0, 1, 2], [0, 2, 3]]),
        edge_labels={"river::1": np.array([[0, 2]]), "west": np.array([[3, 0]])},
    )


def _request(**overrides: object) -> MeshRequest:
    grid = _grid()
    values: dict[str, object] = dict(
        domain=box(1000.0, 2000.0, 1100.0, 2050.0),
        crs_wkt=_WKT,
        grid=grid,
        lines=(
            LineFamilySpec("rivers", "cell", (LineString([(1000, 2010), (1100, 2040)]),)),
            LineFamilySpec(
                "geology",
                "face",
                (LineString([(1050, 2000), (1050, 2050)]),),
                zone_left=("granite",),
                zone_right=("schist",),
            ),
        ),
        size_field=SizeField(np.full((5, 10), 20.0), grid),
        nominal_size_m=25.0,
        seed=3,
        options={"algorithm": "delaunay", "shape": [5, 10]},
        input_triangulation=_triangulation(),
    )
    values.update(overrides)
    return MeshRequest(**values)


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
    grid = base.grid
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
            crs_wkt=other_wkt,
            grid=_grid(crs_wkt=other_wkt),
            size_field=SizeField(np.full((5, 10), 20.0), _grid(crs_wkt=other_wkt)),
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
        "size field values": _request(size_field=SizeField(field, grid)),
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
    }


@pytest.mark.parametrize("member", sorted(_variants()))
def test_the_hash_moves_with_every_member(member: str) -> None:
    assert _variants()[member].canonical_hash() != _request().canonical_hash()


def test_every_variant_hashes_differently_from_the_others() -> None:
    hashes = [request.canonical_hash() for request in _variants().values()]

    assert len(set(hashes)) == len(hashes)


def test_the_arrays_of_a_request_are_copies_and_read_only() -> None:
    values = np.full((5, 10), 20.0)
    field = SizeField(values, _grid())
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


@pytest.mark.parametrize(
    "options",
    [{"path": object()}, {"tolerance": float("nan")}, {1: "integer key"}],
)
def test_an_option_that_is_not_json_is_refused(options: dict) -> None:
    with pytest.raises(MeshRequestError):
        _request(options=options)


def test_the_request_is_frozen() -> None:
    request = _request()

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.seed = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"dx": 0.0, "ncol": 10},
        {"dx": 11.0},
        {"nrow": 0},
        {"ncol": 2.5},
        {"xmax": 1000.0},
        {"ymin": float("nan")},
        {"crs_wkt": " "},
    ],
)
def test_a_grid_whose_members_disagree_is_refused(overrides: dict) -> None:
    with pytest.raises(MeshRequestError):
        _grid(**overrides)


def test_a_grid_keeps_the_bounds_it_was_given() -> None:
    grid = _grid(ymin=2000.0000000001, ymax=2050.0)

    assert grid.ymin == 2000.0000000001


def test_a_grid_from_a_raster_support_takes_its_exact_bounds() -> None:
    support = SimpleNamespace(
        xmin=0.0, xmax=300.0, ymin=-75.0, ymax=0.0, dx=None, dy=25.0, nrows=3, ncols=4
    )

    grid = RasterGridSpec.from_raster_support(support, crs_wkt=_WKT)

    assert (grid.xmin, grid.xmax, grid.ymin, grid.ymax) == (0.0, 300.0, -75.0, 0.0)
    assert (grid.dx, grid.dy, grid.nrow, grid.ncol) == (75.0, 25.0, 3, 4)


def test_an_incomplete_raster_support_is_refused() -> None:
    support = SimpleNamespace(
        xmin=0.0, xmax=300.0, ymin=None, ymax=0.0, dx=75.0, dy=25.0, nrows=3, ncols=4
    )

    with pytest.raises(MeshRequestError, match="ymin"):
        RasterGridSpec.from_raster_support(support, crs_wkt=_WKT)


def test_a_size_field_of_another_shape_or_with_a_zero_is_refused() -> None:
    with pytest.raises(MeshRequestError):
        SizeField(np.full((10, 5), 20.0), _grid())
    with pytest.raises(MeshRequestError):
        SizeField(np.zeros((5, 10)), _grid())


def test_a_line_family_needs_lines_and_matching_zones() -> None:
    line = LineString([(0, 0), (1, 1)])
    with pytest.raises(MeshRequestError):
        LineFamilySpec("rivers", "node", (line,))  # type: ignore[arg-type]
    with pytest.raises(MeshRequestError):
        LineFamilySpec("", "cell", (line,))
    with pytest.raises(MeshRequestError):
        LineFamilySpec("rivers", "cell", (LineString([(0, 0), (0, 0)]),))
    with pytest.raises(MeshRequestError):
        LineFamilySpec("geology", "face", (line,), zone_left=("a", "b"), zone_right=("c", "d"))
    with pytest.raises(MeshRequestError):
        LineFamilySpec("geology", "face", (line,), zone_left=("a",))


def test_a_triangulation_indexing_outside_its_vertices_is_refused() -> None:
    vertices = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    with pytest.raises(MeshRequestError):
        InputTriangulation(vertices=vertices, triangles=np.array([[0, 1, 3]]), edge_labels={})
    with pytest.raises(MeshRequestError):
        InputTriangulation(
            vertices=vertices,
            triangles=np.array([[0, 1, 2]]),
            edge_labels={"x": np.array([[0, 5]])},
        )
    with pytest.raises(MeshRequestError):
        InputTriangulation(
            vertices=vertices[:, :1], triangles=np.array([[0, 1, 2]]), edge_labels={}
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"domain": Polygon()},
        {"domain": Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])},
        {"crs_wkt": ""},
        {"crs_wkt": 'PROJCS["other"]'},
        {"nominal_size_m": 0.0},
        {"nominal_size_m": float("inf")},
        {"seed": 1.5},
        {"seed": True},
    ],
)
def test_a_malformed_request_is_refused(overrides: dict) -> None:
    with pytest.raises(MeshRequestError):
        _request(**overrides)


def test_two_families_with_one_name_are_refused() -> None:
    line = LineString([(1000, 2010), (1100, 2040)])

    with pytest.raises(MeshRequestError, match="rivers"):
        _request(
            lines=(
                LineFamilySpec("rivers", "cell", (line,)),
                LineFamilySpec("rivers", "face", (line,)),
            )
        )


def test_a_minimal_request_takes_the_defaults() -> None:
    request = MeshRequest(
        domain=box(1000.0, 2000.0, 1100.0, 2050.0), crs_wkt=_WKT, grid=_grid(), nominal_size_m=10.0
    )

    assert request.lines == ()
    assert request.size_field is None
    assert request.seed == 0
    assert dict(request.options) == {}
    assert request.input_triangulation is None
    assert request.family("rivers") is None
