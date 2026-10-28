"""Zone fractions of a support on the cells of a planar cell mesh.

A vector map gives the exact area of each zone in each cell; the engine zone of
a mesh drawn on the contacts wins when it agrees with the map; any other support
keeps its own sampling.
"""

from __future__ import annotations

import numpy as np
import pytest
import shapely
from rasterio.transform import from_origin

from hydromodpy.core.exceptions import MeshError
from hydromodpy.spatial.domain.spatial_support import GeneratedBandsSupportField
from hydromodpy.spatial.field.geology.geology_field import GeologyField
from hydromodpy.spatial.field.zone_fractions import ZonePolygons, zone_fractions
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from tests._helpers.field_cases import planar_mesh

X0, Y0 = 351_234.5, 6_789_012.25
"""Lambert-93 magnitudes: the overlay must not lose the 1e-9 to them."""

SQUARE = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])


def _mesh(vertices, cells, cell_type: CellType, **kwargs) -> PlanarCellMesh:
    return planar_mesh(np.asarray(vertices, dtype=float) + [X0, Y0], cells, cell_type, **kwargs)


def _square_meshes() -> dict[str, PlanarCellMesh]:
    """Three meshes of the square [0, 10]^2: one quad, two triangles, two polygons."""
    polygon_vertices = np.array(
        [[0.0, 0.0], [10.0, 0.0], [10.0, 7.0], [10.0, 10.0], [5.0, 10.0], [0.0, 10.0], [0.0, 3.0]]
    )
    return {
        "quadrilateral": _mesh(SQUARE, [[0, 1, 2, 3]], CellType.QUADRILATERAL),
        "triangle": _mesh(SQUARE, [[0, 1, 2], [0, 2, 3]], CellType.TRIANGLE),
        "polygon": _mesh(polygon_vertices, [[0, 1, 2, 6], [6, 2, 3, 4, 5]], CellType.POLYGON),
    }


def _shifted(geometry: shapely.Geometry) -> shapely.Geometry:
    return shapely.affinity.translate(geometry, X0, Y0)


class _VectorSupport:
    """A support with vector zones; its sampling must never run."""

    identifier = "geology"

    def __init__(self, zones: dict[str, shapely.Geometry], zone_polygons=None) -> None:
        keys = tuple(zones)
        self.zone_polygons = zone_polygons or ZonePolygons.from_geometries(
            [_shifted(zones[key]) for key in keys], keys, zone_keys=keys
        )

    def on_mesh(self, cell_mesh, *, cell_samples_per_axis: int = 10):
        raise AssertionError("a vector support is never sampled")


def _regular_polygon(n: int, radius: float, center=(5.0, 5.0)) -> shapely.Polygon:
    angles = 2.0 * np.pi * np.arange(n) / n + 0.3
    return shapely.Polygon(
        np.column_stack([center[0] + radius * np.cos(angles), center[1] + radius * np.sin(angles)])
    )


def _regular_polygon_area(n: int, radius: float) -> float:
    return 0.5 * n * radius**2 * np.sin(2.0 * np.pi / n)


def _zone_area(cell_mesh: PlanarCellMesh, support: object, key: str) -> float:
    fractions = zone_fractions(cell_mesh, support)
    column = fractions.zone_keys.index(key)
    return float(np.sum(fractions.values[:, column] * cell_mesh.geometry.areas))


_BOX = shapely.box(0.0, 0.0, 10.0, 10.0)
_TRIANGLE = shapely.Polygon([(2.0, 1.0), (9.0, 2.0), (4.0, 8.0)])
_HEPTAGON = _regular_polygon(7, 4.0)
_RING = _regular_polygon(7, 4.5).difference(_regular_polygon(7, 2.0))

_CLOSED_CASES = {
    "square cut in half": (
        {"west": shapely.box(0.0, 0.0, 5.0, 10.0), "east": shapely.box(5.0, 0.0, 10.0, 10.0)},
        "west",
        50.0,
    ),
    "triangle": (
        {"triangle": _TRIANGLE, "rest": _BOX.difference(_TRIANGLE)},
        "triangle",
        0.5 * abs((9.0 - 2.0) * (8.0 - 1.0) - (4.0 - 2.0) * (2.0 - 1.0)),
    ),
    "seven-sided polygon": (
        {"heptagon": _HEPTAGON, "rest": _BOX.difference(_HEPTAGON)},
        "heptagon",
        _regular_polygon_area(7, 4.0),
    ),
    "ring": (
        {
            "core": _regular_polygon(7, 2.0),
            "ring": _RING,
            "outside": _BOX.difference(_regular_polygon(7, 4.5)),
        },
        "ring",
        _regular_polygon_area(7, 4.5) - _regular_polygon_area(7, 2.0),
    ),
}


@pytest.mark.parametrize("case", list(_CLOSED_CASES))
@pytest.mark.parametrize("cell_kind", ["quadrilateral", "triangle", "polygon"])
def test_a_vector_zone_takes_its_exact_area_in_the_cells(case: str, cell_kind: str) -> None:
    zones, key, analytical_area = _CLOSED_CASES[case]
    cell_mesh = _square_meshes()[cell_kind]
    support = _VectorSupport(zones)

    area = _zone_area(cell_mesh, support, key)

    assert abs(area - analytical_area) / analytical_area < 1e-9
    fractions = zone_fractions(cell_mesh, support)
    assert fractions.source == "vector"
    np.testing.assert_allclose(fractions.values.sum(axis=1), 1.0, rtol=0.0, atol=1e-12)


def test_the_fractions_are_shares_of_the_area_the_map_covers() -> None:
    cell_mesh = _mesh(
        np.array([[0, 0], [10, 0], [20, 0], [30, 0], [30, 10], [20, 10], [10, 10], [0, 10]]),
        [[0, 1, 6, 7], [1, 2, 5, 6], [2, 3, 4, 5]],
        CellType.QUADRILATERAL,
    )
    support = _VectorSupport(
        {"a": shapely.box(0.0, 0.0, 4.0, 10.0), "b": shapely.box(4.0, 0.0, 15.0, 10.0)}
    )

    fractions = zone_fractions(cell_mesh, support)

    # Cell 0 is 40 % a and 60 % b; cell 1 is half outside the map, all b of
    # what the map covers; cell 2 is outside the map and gets no zone.
    np.testing.assert_allclose(fractions.values, [[0.4, 0.6], [0.0, 1.0], [0.0, 0.0]], atol=1e-12)
    assert fractions.n_mixed_cells == 1


def _contact_triangulation(
    cell_zone: np.ndarray | None, *, exact_faces: bool, zone_names: tuple[str, ...]
) -> PlanarCellMesh:
    """A 4 x 2 grid of squares cut into 16 triangles; the contact x = 2 runs on faces."""
    xs, ys = np.meshgrid(np.arange(5.0), np.arange(3.0))
    vertices = np.column_stack([xs.ravel(), ys.ravel()])
    cells = []
    for row in range(2):
        for col in range(4):
            a = row * 5 + col
            cells += [[a, a + 1, a + 6], [a, a + 6, a + 5]]
    return _mesh(
        vertices,
        cells,
        CellType.TRIANGLE,
        exact_faces=exact_faces,
        cell_zone=cell_zone,
        zone_names=zone_names,
    )


def _west_east_zone() -> np.ndarray:
    columns = np.repeat(np.tile(np.arange(4), 2), 2)
    return np.where(columns < 2, 0, 1).astype(np.int32)


def _map_with_contact_at(x: float) -> _VectorSupport:
    return _VectorSupport(
        {"west": shapely.box(0.0, 0.0, x, 2.0), "east": shapely.box(x, 0.0, 4.0, 2.0)}
    )


def test_the_engine_zone_wins_when_the_engine_drew_the_contact() -> None:
    zone_names = ("west", "east")
    support = _map_with_contact_at(2.1)
    drawn = _contact_triangulation(_west_east_zone(), exact_faces=True, zone_names=zone_names)
    not_drawn = _contact_triangulation(_west_east_zone(), exact_faces=False, zone_names=zone_names)

    engine = zone_fractions(drawn, support)
    vector = zone_fractions(not_drawn, support)

    # The map puts its contact 0.1 m east of the faces: the vector fractions mix
    # the cells beside it, the engine gives each cell its zone whole.
    assert vector.n_mixed_cells > 0
    assert engine.n_mixed_cells == 0
    assert engine.n_engine_cells == 16
    expected = np.zeros((16, 2))
    expected[np.arange(16), _west_east_zone()] = 1.0
    np.testing.assert_array_equal(engine.values, expected)


def test_engine_zones_that_contradict_the_map_stop_the_run() -> None:
    swapped = 1 - _west_east_zone()
    cell_mesh = _contact_triangulation(swapped, exact_faces=True, zone_names=("west", "east"))

    with pytest.raises(MeshError, match="spatial support 'geology'"):
        zone_fractions(cell_mesh, _map_with_contact_at(2.0))


def test_engine_zones_of_another_map_are_not_read() -> None:
    cell_mesh = _contact_triangulation(
        _west_east_zone(), exact_faces=True, zone_names=("granite", "schist")
    )

    fractions = zone_fractions(cell_mesh, _map_with_contact_at(2.1))

    assert fractions.n_engine_cells == 0
    assert fractions.n_mixed_cells > 0


def test_a_support_without_polygons_keeps_its_sampling() -> None:
    cell_mesh = _square_meshes()["triangle"]
    bands = GeneratedBandsSupportField(
        identifier="bands",
        axis="x",
        breaks_abs=[X0 + 3.0],
        labels=["low", "high"],
        default_cell_samples_per_axis=6,
    )

    fractions = zone_fractions(cell_mesh, bands)
    sampled = bands.on_mesh(cell_mesh, cell_samples_per_axis=6)

    assert fractions.source == "sampled"
    for key in ("low", "high"):
        np.testing.assert_array_equal(fractions.by_zone()[key], sampled.fractions_by_zone[key])


def test_a_geology_field_reads_its_polygons_rather_than_its_raster() -> None:
    cell_mesh = _square_meshes()["quadrilateral"]
    zone_polygons = ZonePolygons.from_geometries(
        [_shifted(shapely.box(0.0, 0.0, 3.0, 10.0)), _shifted(shapely.box(3.0, 0.0, 10.0, 10.0))],
        ["granite", "schist"],
        zone_keys=("granite", "schist"),
    )
    # The raster puts the contact at x = 5; the polygons, at x = 3.
    field = GeologyField(
        identifier="geology",
        encoded_codes=np.array([[1, 2]], dtype=np.int32),
        encoded_to_zone={1: "granite", 2: "schist"},
        transform=from_origin(X0, Y0 + 10.0, 5.0, 10.0),
        source_kind="vector",
        zone_polygons=zone_polygons,
    )

    fractions = zone_fractions(cell_mesh, field)

    np.testing.assert_allclose(fractions.values, [[0.3, 0.7]], rtol=1e-12)


def test_zone_polygons_split_multi_parts_and_cut_to_a_box() -> None:
    two_squares = shapely.MultiPolygon(
        [shapely.box(0.0, 0.0, 1.0, 1.0), shapely.box(5.0, 0.0, 6.0, 1.0)]
    )
    zones = ZonePolygons.from_geometries(
        [two_squares, shapely.box(0.0, 2.0, 6.0, 3.0)], ["a", "b"], zone_keys=("a", "b")
    )

    clipped = zones.clip_by_rect(0.5, 0.0, 5.5, 2.5)

    assert zones.geometries.size == 3
    np.testing.assert_array_equal(zones.zone_index, [0, 0, 1])
    np.testing.assert_allclose(shapely.area(clipped.geometries), [0.5, 0.5, 2.5])
    np.testing.assert_array_equal(clipped.zone_index, [0, 0, 1])


_UNIT = shapely.box(0.0, 0.0, 1.0, 1.0)


@pytest.mark.parametrize(
    ("build", "match"),
    [
        (lambda: ZonePolygons.from_geometries([_UNIT], ["c"], zone_keys=("a", "b")), r"\['c'\]"),
        (lambda: ZonePolygons([_UNIT, _UNIT], [0], ("a",)), r"2 polygon\(s\) for 1 zone index"),
        (lambda: ZonePolygons([_UNIT], [1], ("a",)), "names a zone outside zone_keys"),
        (lambda: ZonePolygons([shapely.MultiPolygon([_UNIT])], [0], ("a",)), "split multi-parts"),
    ],
    ids=["unknown-key", "index-count", "index-out-of-range", "multi-part"],
)
def test_zone_polygons_refuse_parts_they_cannot_key(build, match) -> None:
    with pytest.raises(ValueError, match=match):
        build()


def test_a_collection_keeps_its_polygons_and_drops_its_lines() -> None:
    collection = shapely.GeometryCollection(
        [
            shapely.MultiPolygon([_UNIT, shapely.box(2.0, 0.0, 3.0, 1.0)]),
            shapely.LineString([(0, 0), (5, 5)]),
        ]
    )

    zones = ZonePolygons.from_geometries([collection], ["a"], zone_keys=("a",))

    np.testing.assert_allclose(shapely.area(zones.geometries), [1.0, 1.0])
    np.testing.assert_array_equal(zones.zone_index, [0, 0])


def test_an_empty_map_gives_no_zone_to_any_cell() -> None:
    empty = ZonePolygons.from_geometries([], [], zone_keys=("a",))
    fractions = zone_fractions(
        _square_meshes()["triangle"], _VectorSupport({}, zone_polygons=empty)
    )

    assert empty.clip_by_rect(0.0, 0.0, 1.0, 1.0) is empty
    np.testing.assert_array_equal(fractions.values, [[0.0], [0.0]])


def test_a_polygon_that_crosses_itself_keeps_its_area_and_does_not_stop_the_cut() -> None:
    """A bow tie is two triangles of 25 m2; the exact cut reads both."""
    bow_tie = shapely.Polygon([(0.0, 0.0), (10.0, 10.0), (10.0, 0.0), (0.0, 10.0)])
    assert not bow_tie.is_valid
    rest = _BOX.difference(shapely.make_valid(bow_tie))
    support = _VectorSupport({"bow tie": bow_tie, "rest": rest})
    for cell_mesh in _square_meshes().values():
        assert _zone_area(cell_mesh, support, "bow tie") == pytest.approx(50.0, abs=1e-9)
        assert _zone_area(cell_mesh, support, "rest") == pytest.approx(50.0, abs=1e-9)
