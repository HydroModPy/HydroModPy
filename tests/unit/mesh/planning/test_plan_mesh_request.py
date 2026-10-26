"""The planner turns [mesh] and the project inputs into one request, named by its content."""

from __future__ import annotations

import dataclasses
import logging
import shutil
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon, box

from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.config.mesh import MeshConfig
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.planning.geology import contact_lines
from hydromodpy.spatial.mesh.planning.inputs import PlanningInputs
from hydromodpy.spatial.mesh.planning.plan import plan_mesh_request
from hydromodpy.spatial.mesh.planning.refinement import load_refinement_zones
from hydromodpy.spatial.mesh.port import MeshEngineCapabilities
from hydromodpy.spatial.mesh.refinement.refinement_zones import RefinementZoneConfig
from hydromodpy.spatial.mesh.request import InputTriangulation, RasterGridSpec
from hydromodpy.spatial.mesh.sizing.size_field import sample_size_field

_WKT = 'PROJCS["RGF93 / Lambert-93"]'
_GRID = RasterGridSpec(
    xmin=0.0, xmax=1000.0, ymin=0.0, ymax=1000.0, dx=10.0, dy=10.0, nrow=100, ncol=100, crs_wkt=_WKT
)
_GEOLOGY = (
    ("a", box(-50.0, -50.0, 1050.0, 400.0)),
    ("b", box(-50.0, 400.0, 500.0, 1050.0)),
    ("c", box(500.0, 400.0, 1050.0, 1050.0)),
)
_LAKES = (Point(300.0, 750.0).buffer(60.0), Point(750.0, 200.0).buffer(40.0))


def _capabilities(*, graded: bool) -> MeshEngineCapabilities:
    return MeshEngineCapabilities(
        cell_types=(CellType.TRIANGLE,),
        structured=not graded,
        graded=graded,
        exact_faces=graded,
        cell_families="derived_from_faces",
        deterministic=not graded,
        needs_cache=graded,
    )


@pytest.fixture(autouse=True)
def _engines(monkeypatch: pytest.MonkeyPatch) -> None:
    """Capabilities of the built-in engines, without importing them."""
    engines = {
        "regular": SimpleNamespace(capabilities=_capabilities(graded=False)),
        "triangle": SimpleNamespace(capabilities=_capabilities(graded=True)),
        "voronoi": SimpleNamespace(capabilities=_capabilities(graded=True)),
    }
    monkeypatch.setattr(registry, "get", lambda engine_id=None: engines[engine_id])


def _zone_file(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "zones.geojson"
    gpd.GeoDataFrame(
        geometry=[box(600.0, 600.0, 700.0, 700.0), LineString([(100.0, 100.0), (200.0, 300.0)])],
        crs="EPSG:2154",
    ).to_file(path, driver="GeoJSON")
    return path


def _inputs(
    tmp_path: Path,
    *,
    zones_dir: str = "a",
    geology=_GEOLOGY,
    lakes=_LAKES,
    triangulation: InputTriangulation | None = None,
) -> PlanningInputs:
    zone_path = _zone_file(tmp_path / zones_dir)
    zones = load_refinement_zones(
        [RefinementZoneConfig(path=zone_path, cell_size=15.0)],
        config_dir=None,
        data_dir=None,
        crs_wkt="EPSG:2154",
    )
    river = LineString([(-100.0, 520.0), (480.0, 500.0), (1100.0, 560.0)])
    return PlanningInputs(
        dem_grid=_GRID,
        crs_wkt=_WKT,
        domain=box(0.0, 0.0, 1000.0, 1000.0),
        river_trace=SimpleNamespace(lines=(river,)),
        watershed=box(100.0, 100.0, 900.0, 900.0),
        lakes=lakes,
        lake_structures=(("voile:1", LineString([(700.0, 180.0), (800.0, 180.0)]), 12.0, 30.0),),
        geology=contact_lines(geology),
        refinement_zones=zones,
        input_triangulation=triangulation,
        synthetic=False,
    )


_TRIANGLE = MeshConfig(
    engine="triangle",
    cell_size=80.0,
    river_cell_size=20.0,
    lake_refinement={"cell_size": 20.0},
    families={"watershed_boundary": "face"},
)


def test_the_hash_ignores_the_polygon_order_and_the_file_paths(tmp_path: Path) -> None:
    first = plan_mesh_request(_TRIANGLE, _inputs(tmp_path))
    second = plan_mesh_request(
        _TRIANGLE,
        _inputs(
            tmp_path,
            zones_dir="elsewhere/deeper",
            geology=tuple(reversed(_GEOLOGY)),
            lakes=tuple(reversed(_LAKES)),
        ),
    )
    assert first.canonical_hash() == second.canonical_hash()


def test_a_graded_engine_gets_a_size_field_and_resampled_lines(tmp_path: Path) -> None:
    request = plan_mesh_request(_TRIANGLE, _inputs(tmp_path))
    assert [family.name for family in request.lines] == [
        "geology",
        "lakes",
        "rivers",
        "watershed_boundary",
    ]
    assert request.options == {"algorithm": "delaunay"}
    assert request.nominal_size_m == 80.0
    field = request.size_field
    assert field is not None
    assert field.values.min() == pytest.approx(12.0)
    assert field.values.max() <= 2.0 * 80.0
    rivers = request.family("rivers")
    assert rivers.intent == "cell"
    river = rivers.lines[0]
    assert river.coords[0] == (0.0, pytest.approx(516.551724137931))
    assert river.coords[-1][0] == pytest.approx(1000.0)
    assert len(river.coords) > 10
    geology = request.family("geology")
    assert set(zip(geology.zone_left, geology.zone_right)) == {("a", "b"), ("a", "c"), ("b", "c")}
    assert request.family("lakes").closed is True


def test_the_regular_engine_gets_raw_lines_and_no_size_field(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    request = plan_mesh_request(MeshConfig(engine="regular", regular={"shape": [60, 40]}), inputs)
    assert request.size_field is None
    assert request.options == {"shape": (60, 40)}
    assert request.nominal_size_m == 10.0
    river = request.family("rivers").lines[0]
    assert len(river.coords) == 3
    plain = plan_mesh_request(MeshConfig(cell_size=50.0), inputs)
    assert plain.options == {} and plain.nominal_size_m == 50.0


def test_a_regular_mesh_with_no_size_and_no_shape_is_the_dem_grid(tmp_path: Path) -> None:
    request = plan_mesh_request(MeshConfig(), _inputs(tmp_path))
    assert request.options == {"shape": (_GRID.nrow, _GRID.ncol)}


def test_a_family_set_to_none_is_left_out(tmp_path: Path) -> None:
    cfg = MeshConfig(engine="voronoi", families={"rivers": "none", "geology": "none"})
    request = plan_mesh_request(cfg, _inputs(tmp_path))
    assert [family.name for family in request.lines] == ["lakes"]
    assert request.options == {"seeds": "generated", "lloyd_tolerance": 0.01}


def test_a_triangulation_read_is_meshed_as_it_is(tmp_path: Path) -> None:
    triangulation = InputTriangulation(
        vertices=np.array([[0.0, 0.0], [800.0, 0.0], [800.0, 900.0], [0.0, 900.0]]),
        triangles=np.array([[0, 1, 2], [0, 2, 3]]),
        edge_labels={},
    )
    cfg = MeshConfig(engine="voronoi", triangle={"path": "m.msh"})
    request = plan_mesh_request(cfg, _inputs(tmp_path, triangulation=triangulation))
    assert request.size_field is None
    assert request.domain.equals(box(0.0, 0.0, 800.0, 900.0))
    assert request.input_triangulation is triangulation
    assert request.options == {"seeds": "triangulation"}
    assert request.family("rivers").lines[0].coords[-1][0] == pytest.approx(800.0)


def test_a_changed_size_changes_the_hash(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    reference = plan_mesh_request(_TRIANGLE, inputs).canonical_hash()
    finer = _TRIANGLE.model_copy(update={"river_cell_size": 15.0})
    assert plan_mesh_request(finer, inputs).canonical_hash() != reference


def test_the_zone_file_is_read_wherever_it_lies(tmp_path: Path) -> None:
    source = _zone_file(tmp_path / "data" / "refinement_zone")
    shutil.copy(source, tmp_path / "copy.geojson")
    by_data_dir = load_refinement_zones(
        [RefinementZoneConfig(path="zones.geojson", cell_size=15.0)],
        config_dir=tmp_path,
        data_dir=tmp_path / "data",
        crs_wkt="EPSG:2154",
    )
    by_config_dir = load_refinement_zones(
        [RefinementZoneConfig(path="copy.geojson", cell_size=15.0)],
        config_dir=tmp_path,
        data_dir=None,
        crs_wkt="EPSG:2154",
    )
    assert by_data_dir[0].region.equals(by_config_dir[0].region)
    assert by_data_dir[0].ramp_m == 30.0


def test_the_notes_say_what_an_ungraded_engine_does_not_follow(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    plain = plan_mesh_request(MeshConfig(cell_size=50.0), inputs)
    noted = plan_mesh_request(
        MeshConfig(engine="regular", cell_size=50.0, river_cell_size=20.0, river_band=60.0),
        inputs,
    )
    assert plain.notes == ()
    assert noted.notes == (
        "regular ignores river_cell_size and river_band: it does not grade its cells",
    )
    assert noted.canonical_hash() == plain.canonical_hash()


def test_the_notes_of_the_inputs_travel_with_the_request(tmp_path: Path) -> None:
    inputs = dataclasses.replace(_inputs(tmp_path), notes=("no vector geology",))
    assert plan_mesh_request(MeshConfig(cell_size=50.0), inputs).notes == ("no vector geology",)


def _holed(outer: Polygon, *holes: Polygon) -> Polygon:
    return Polygon(outer.exterior.coords, [hole.exterior.coords for hole in holes])


_TINY = 0.5
"""Radius [m] of a hole of 0.8 m2, as the pixels of a polygonised bathymetry leave."""
_WIDE = 25.0
"""Radius [m] of a hole of 1960 m2, larger than one 40 m cell squared."""


def _with_holes(tmp_path: Path, **kwargs) -> PlanningInputs:
    """The inputs with a tiny hole in the domain, a lake and the catchment, and a wide one in a lake."""
    lake = _holed(
        Point(300.0, 750.0).buffer(60.0),
        Point(280.0, 750.0).buffer(_TINY),
        Point(320.0, 750.0).buffer(_WIDE),
    )
    return dataclasses.replace(
        _inputs(tmp_path, lakes=(lake, Point(750.0, 200.0).buffer(40.0))),
        domain=_holed(box(0.0, 0.0, 1000.0, 1000.0), Point(50.0, 50.0).buffer(_TINY)),
        watershed=_holed(box(100.0, 100.0, 900.0, 900.0), Point(200.0, 200.0).buffer(_TINY)),
        **kwargs,
    )


@pytest.mark.parametrize(
    "mesh_cfg",
    [
        MeshConfig(engine="triangle", cell_size=40.0, families={"watershed_boundary": "face"}),
        MeshConfig(engine="regular", cell_size=40.0, families={"watershed_boundary": "face"}),
    ],
    ids=["graded", "regular"],
)
def test_a_hole_under_one_cell_squared_is_dropped_for_every_engine(
    tmp_path: Path, mesh_cfg: MeshConfig, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        request = plan_mesh_request(mesh_cfg, _with_holes(tmp_path))

    assert len(request.domain.interiors) == 0
    assert len(request.family("lakes").lines) == 3  # the lake, its wide hole, the second lake
    assert len(request.family("watershed_boundary").lines) == 1
    assert any("3 holes of the domain, the lakes and the catchment" in n for n in request.notes)
    assert [r.message for r in caplog.records if "Dropped" in r.message] == [
        "Dropped 3 holes smaller than one local cell squared."
    ]


def test_without_a_small_hole_the_request_is_the_one_of_the_inputs(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    request = plan_mesh_request(_TRIANGLE, inputs)

    assert all("holes" not in note for note in request.notes)
    assert request.domain.equals(inputs.domain)


def test_a_triangulation_read_keeps_every_hole(tmp_path: Path) -> None:
    triangulation = InputTriangulation(
        vertices=np.array([[0.0, 0.0], [800.0, 0.0], [800.0, 900.0], [0.0, 900.0]]),
        triangles=np.array([[0, 1, 2], [0, 2, 3]]),
        edge_labels={},
    )
    cfg = MeshConfig(engine="voronoi", triangle={"path": "m.msh"})
    request = plan_mesh_request(cfg, _with_holes(tmp_path, input_triangulation=triangulation))

    assert len(request.family("lakes").lines) == 4
    assert all("holes" not in note for note in request.notes)


def test_the_lloyd_tolerance_reaches_the_generated_voronoi_engine_only(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    generated = MeshConfig(engine="voronoi", voronoi={"lloyd_tolerance": 0.05})

    assert plan_mesh_request(generated, inputs).options == {
        "seeds": "generated",
        "lloyd_tolerance": 0.05,
    }


_ARM_LAKE = Polygon(
    [(100, 100), (900, 100), (900, 500), (500, 500), (500, 140), (460, 140), (460, 500), (100, 500)]
)


def test_the_size_holds_two_cells_across_a_narrow_lake_arm_unless_gap_cells_is_zero(
    tmp_path: Path,
) -> None:
    def arm_size(cfg: MeshConfig) -> tuple[float, tuple[str, ...]]:
        request = plan_mesh_request(cfg, _inputs(tmp_path, lakes=(_ARM_LAKE,)))
        return float(sample_size_field(request.size_field, np.array([[480.0, 300.0]]))[0]), (
            request.notes
        )

    on = MeshConfig(engine="triangle", cell_size=80.0)
    off = MeshConfig(engine="triangle", cell_size=80.0, gap_cells=0.0)
    size_on, notes_on = arm_size(on)
    size_off, notes_off = arm_size(off)
    assert size_on <= 20.0
    assert size_off > 20.0
    assert any(note.startswith("gaps: ") for note in notes_on)
    assert not any(note.startswith("gaps: ") for note in notes_off)


def test_less_than_one_cell_across_a_gap_is_refused() -> None:
    with pytest.raises(ValueError, match="less than one cell across a gap"):
        MeshConfig(engine="voronoi", gap_cells=0.5)
