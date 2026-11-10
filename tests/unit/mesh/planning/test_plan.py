"""The planner turns [mesh] and the project inputs into one request, named by its content.

A graded engine gets a size field and its lines resampled on it, a regular grid
the raw lines, a triangulation read its own outline. A refinement zone refines
the field where it lies, the planner notes the share of the catchment a zone
drawn by a threshold covers, and records the earlier runs the mesh depends on.
A lumped engine gets the catchment outline, and no other engine does.
"""

from __future__ import annotations

import dataclasses
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Point, Polygon, box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.mesh.engines.catchment.engine import CatchmentMeshEngine
from hydromodpy.mesh.engines.triangle.engine import TriangleMeshEngine
from hydromodpy.mesh.mesh_config import MeshConfig, MeshTriangleConfig, MeshVoronoiConfig
from hydromodpy.mesh.planning import size_terms
from hydromodpy.mesh.planning.geology_contacts import contact_lines
from hydromodpy.mesh.planning.inputs import PlanningInputs
from hydromodpy.mesh.planning.lake_structures import LakeStructure
from hydromodpy.mesh.planning.plan import plan_mesh_request
from hydromodpy.mesh.planning.refinement_zones import RefinementZone, load_refinement_zones
from hydromodpy.mesh.planning.size_field import PixelRegion
from hydromodpy.mesh.refinement_config import LakeRefinementConfig, RefinementZoneConfig
from hydromodpy.mesh.request import BARRIER_FAMILY, InputTriangulation
from hydromodpy.workflow.steps.mesh import mesh_product_key
from tests._helpers import reservoir_dam as dam
from tests._helpers.fake_engines import fake_capabilities, fake_engine, registered
from tests._helpers.mesh_cases import LAMBERT93_WKT, grid_over, grid_spec, planning_inputs

pytestmark = pytest.mark.usefixtures("builtin_engines")

_GRID = grid_spec(100, 100, 10.0)
_GEOLOGY = (
    ("a", box(-50.0, -50.0, 1050.0, 400.0)),
    ("b", box(-50.0, 400.0, 500.0, 1050.0)),
    ("c", box(500.0, 400.0, 1050.0, 1050.0)),
)
_LAKES = (Point(300.0, 750.0).buffer(60.0), Point(750.0, 200.0).buffer(40.0))
_CATCHMENT = box(100.0, 100.0, 900.0, 900.0)


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
    return planning_inputs(
        _GRID,
        river_trace=SimpleNamespace(lines=(river,)),
        watershed=_CATCHMENT,
        lakes=lakes,
        lake_structures=(
            LakeStructure("voile", "1", LineString([(700.0, 180.0), (800.0, 180.0)]), 12.0, 30.0),
        ),
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
    assert request.options == {"algorithm": MeshTriangleConfig().algorithm}
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
    assert request.options == {
        "seeds": "generated",
        "lloyd_tolerance": MeshVoronoiConfig().lloyd_tolerance,
    }


def test_a_family_whose_lines_all_lie_off_the_domain_is_left_out() -> None:
    far = 5000.0
    inputs = planning_inputs(
        grid_spec(10, 10, 100.0),
        river_trace=SimpleNamespace(lines=(LineString([(far, 0.0), (far + 900.0, 500.0)]),)),
        geology=contact_lines(
            (
                ("a", box(far, 0.0, far + 500.0, 1000.0)),
                ("b", box(far + 500.0, 0.0, far + 1000.0, 1000.0)),
            )
        ),
        lakes=(Point(far + 300.0, 300.0).buffer(60.0),),
        barriers=(LineString([(far, 100.0), (far + 200.0, 100.0)]),),
        watershed=box(far, 0.0, far + 1000.0, 1000.0),
        synthetic=False,
    )
    cfg = MeshConfig(engine="regular", families={"watershed_boundary": "face"})

    assert plan_mesh_request(cfg, inputs).lines == ()


def test_a_voronoi_mesh_follows_no_shore_when_its_lakes_lie_off_the_domain() -> None:
    # The arm, narrower than two cells, would give a note on a lake the mesh follows.
    lake = box(1200.0, 200.0, 1600.0, 600.0).union(box(1600.0, 390.0, 1900.0, 410.0))
    inputs = planning_inputs(
        grid_spec(10, 10, 100.0),
        lakes=(lake,),
        watershed=box(100.0, 100.0, 900.0, 900.0),
        synthetic=False,
    )

    request = plan_mesh_request(MeshConfig(engine="voronoi", cell_size=100.0), inputs)

    assert request.lines == ()
    assert not any("the faces follow lake" in note for note in request.notes)


@pytest.mark.skipif(find_spec("gmsh") is None, reason="gmsh is not installed")
def test_a_family_switched_off_leaves_no_barrier_face() -> None:
    barrier = LineString([(dam.X0 + 210.0, dam.Y0 + 110.0), (dam.X0 + 830.0, dam.Y0 + 590.0)])
    inputs = planning_inputs(
        grid_over(dam.DOMAIN, 10.0, crs_wkt=LAMBERT93_WKT),
        watershed=dam.DOMAIN,
        synthetic=False,
        barriers=(barrier,),
    )
    config = MeshConfig.model_validate(
        {
            "engine": "triangle",
            "cell_size": 60.0,
            "families": {"rivers": "none", "barriers": "none"},
        }
    )
    cell_mesh = TriangleMeshEngine().build(plan_mesh_request(config, inputs))

    assert not cell_mesh.face_rows(BARRIER_FAMILY).any()


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


def test_a_third_party_engine_gets_no_option(
    tmp_path: Path, builtin_engines: dict[str, SimpleNamespace]
) -> None:
    """The DEV options belong to the built-in engines; a plugin reads its own settings."""
    with registered(fake_engine("plan_probe")) as engine:
        builtin_engines["plan_probe"] = SimpleNamespace(capabilities=fake_capabilities())
        request = plan_mesh_request(
            MeshConfig(engine=engine.engine_id, cell_size=80.0), _inputs(tmp_path)
        )

    assert request.options == {}
    assert request.size_field is not None


def test_a_changed_size_changes_the_hash(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    reference = plan_mesh_request(_TRIANGLE, inputs).canonical_hash()
    finer = _TRIANGLE.model_copy(update={"river_cell_size": 15.0})
    assert plan_mesh_request(finer, inputs).canonical_hash() != reference


def test_the_notes_say_what_an_ungraded_engine_does_not_follow(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    plain = plan_mesh_request(MeshConfig(cell_size=50.0), inputs)
    config = MeshConfig(engine="regular", cell_size=50.0, river_cell_size=20.0, river_band=60.0)
    noted = plan_mesh_request(config, inputs)

    assert plain.notes == ()
    (note,) = noted.notes
    for named in (config.engine, "river_cell_size", "river_band"):
        assert named in note
    assert noted.canonical_hash() == plain.canonical_hash()


def test_the_notes_of_the_inputs_travel_with_the_request(tmp_path: Path) -> None:
    inputs = dataclasses.replace(_inputs(tmp_path), notes=("no vector geology",))
    assert plan_mesh_request(MeshConfig(cell_size=50.0), inputs).notes == ("no vector geology",)


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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sized: list[list] = []
    terms_of = size_terms.gap_terms

    def gap_terms(*args: object, **kwargs: object) -> list:
        sized.append(terms_of(*args, **kwargs))
        return sized[-1]

    monkeypatch.setattr(size_terms, "gap_terms", gap_terms)

    def arm(cfg: MeshConfig):
        request = plan_mesh_request(cfg, _inputs(tmp_path, lakes=(_ARM_LAKE,)))
        return float(request.size_field.sample(np.array([[480.0, 300.0]]))[0]), request

    size_on, on = arm(MeshConfig(engine="triangle", cell_size=80.0))
    size_off, off = arm(MeshConfig(engine="triangle", cell_size=80.0, gap_cells=0.0))

    assert size_on <= 20.0
    assert size_off > 20.0
    (terms,) = sized
    chords = sum(len(shapely.get_parts(term.region)) for term in terms)
    assert any(str(chords) in note for note in on.notes)
    assert not any(note.startswith("gaps: ") for note in off.notes)


def test_less_than_one_cell_across_a_gap_is_refused() -> None:
    with pytest.raises(ValueError, match="less than one cell across a gap"):
        MeshConfig(engine="voronoi", gap_cells=0.5)


def test_a_structure_drawn_as_a_polygon_is_refined_on_its_own_area(tmp_path: Path) -> None:
    """A point or a line is widened by its buffer; a polygon already is a zone."""
    sill = box(600.0, 300.0, 700.0, 350.0)
    inputs = dataclasses.replace(
        _inputs(tmp_path), lake_structures=(LakeStructure("sill", "a-b", sill, 12.0, 30.0),)
    )

    request = plan_mesh_request(_TRIANGLE, inputs)

    sizes = request.size_field.sample(np.array([[650.0, 325.0], [650.0, 420.0]]))
    assert sizes[0] == pytest.approx(12.0)
    assert sizes[1] > 12.0


def test_the_interior_size_refines_the_whole_lake(tmp_path: Path) -> None:
    """The shore term alone leaves the center of a lake coarser than the interior size."""
    interior = _TRIANGLE.model_copy(
        update={"lake_refinement": LakeRefinementConfig(cell_size=20.0, interior_size=30.0)}
    )
    centre = np.array([[300.0, 750.0]])

    shore_only = plan_mesh_request(_TRIANGLE, _inputs(tmp_path)).size_field.sample(centre)
    whole_lake = plan_mesh_request(interior, _inputs(tmp_path)).size_field.sample(centre)

    assert whole_lake[0] == pytest.approx(30.0)
    assert shore_only[0] > 30.0


_LABEL = "height_above_stream below 2 m"
_SIM_ID = "0123456789abcdef0123456789abcdef"
_NO_FAMILIES = {"rivers": "none", "geology": "none", "lakes": "none", "barriers": "none"}
_THALWEG_COLUMNS = slice(49, 52)


def _valley_floor(*, empty: bool = False) -> np.ndarray:
    """The pixels of the three columns around a thalweg at x = 505 m, or none."""
    mask = np.zeros((_GRID.nrow, _GRID.ncol), dtype=bool)
    if not empty:
        mask[:, _THALWEG_COLUMNS] = True
    return mask


def _zone_inputs(mask: np.ndarray, *, source_run: str | None = None) -> PlanningInputs:
    zone = RefinementZone(
        region=PixelRegion(mask=mask, grid=_GRID),
        cell_size_m=20.0,
        ramp_m=40.0,
        label=_LABEL,
        source_run=source_run,
    )
    return planning_inputs(_GRID, watershed=_CATCHMENT, refinement_zones=(zone,), synthetic=False)


def _voronoi() -> MeshConfig:
    return MeshConfig(engine="voronoi", cell_size=80.0, families=_NO_FAMILIES)


def _zone_note(request, index: int) -> str:
    """The note of the planner that names refinement zone *index*."""
    (note,) = (note for note in request.notes if f"refinement zone {index} ({_LABEL})" in note)
    return note


def test_the_size_field_refines_a_zone_of_pixels_and_grows_away_from_it() -> None:
    request = plan_mesh_request(_voronoi(), _zone_inputs(_valley_floor()))

    field = request.size_field
    assert field is not None
    sizes = field.sample(np.array([[505.0, 505.0], [515.0, 505.0], [805.0, 505.0]]))
    assert sizes[0] == pytest.approx(20.0) and sizes[1] == pytest.approx(20.0)
    assert sizes[2] == pytest.approx(80.0)
    assert request.source_runs == ()
    # Three columns of the 80 x 80 pixels of the catchment.
    share = 100.0 * 3 / 80
    assert f"{share:.1f} %" in _zone_note(request, 0)


def test_the_mesh_depends_on_the_run_it_was_refined_on() -> None:
    first = plan_mesh_request(_voronoi(), _zone_inputs(_valley_floor(), source_run=_SIM_ID))
    second = plan_mesh_request(_voronoi(), _zone_inputs(_valley_floor(), source_run="f" * 32))
    engine = SimpleNamespace(engine_id="voronoi", engine_version="1.0.0")

    assert first.source_runs == (_SIM_ID,)
    np.testing.assert_array_equal(first.size_field.values, second.size_field.values)
    assert first.canonical_hash() != second.canonical_hash()
    assert mesh_product_key(first, engine) != mesh_product_key(second, engine)
    unbound = dataclasses.replace(first, source_runs=())
    assert unbound.canonical_hash() != first.canonical_hash()
    assert mesh_product_key(unbound, engine) != mesh_product_key(first, engine)


def test_a_zone_that_selects_no_pixel_refines_nothing_and_says_so() -> None:
    request = plan_mesh_request(
        _voronoi(), _zone_inputs(_valley_floor(empty=True), source_run=_SIM_ID)
    )

    assert request.size_field is not None
    assert np.all(request.size_field.values >= 80.0)
    assert request.source_runs == (_SIM_ID,)
    assert _zone_note(request, 0)


def test_an_ungraded_engine_leaves_the_refinement_zones_out() -> None:
    config = MeshConfig(
        engine="regular",
        cell_size=80.0,
        refinement_zone=[{"where": "height_above_stream", "below": 2.0, "cell_size": 20.0}],
    )

    request = plan_mesh_request(config, _zone_inputs(_valley_floor(), source_run=_SIM_ID))

    assert request.size_field is None and request.source_runs == ()
    (note,) = request.notes
    assert config.engine in note and "refinement_zone" in note


def test_a_zone_without_a_catchment_counts_its_share_of_the_domain() -> None:
    inputs = dataclasses.replace(_zone_inputs(_valley_floor()), watershed=None, synthetic=True)

    request = plan_mesh_request(_voronoi(), inputs)

    assert f"{100.0 * 3 / 100:.1f} %" in _zone_note(request, 0)


# A lumped engine meshes the catchment as one cell, so the request carries the
# catchment outline for it, and for no other engine.

_BASE_HASHES = {
    ("regular", False): "454e757c1ad7f453d1cc6e63787fafbbb0fdde61bb320ae883eda2da708998f6",
    ("regular", True): "454e757c1ad7f453d1cc6e63787fafbbb0fdde61bb320ae883eda2da708998f6",
    ("triangle", False): "a6d560cfbc91429bf2e4ffb4806576c1e2e68394870f88a1758ae6f95d01888a",
    ("triangle", True): "13f0012bd8947cb26fdb5e4a7e26839dd4359600ba228ea856cc1a2b5c50daa9",
    ("voronoi", False): "7893f6449937567d1028ca983cc31b0aac8d1e0f1b77e6566b5b3dc66393d882",
    ("voronoi", True): "1648f0a61a9f8650e6b85e2d96a06a2dc5e768521e88c441d5612c1e4929833e",
}
"""Hashes of the planned requests at bcd98022e, before the request had a catchment.

The key is the engine and whether the support is real, with ``_CATCHMENT`` delineated.
"""


def _support(*, real: bool) -> PlanningInputs:
    if real:
        return planning_inputs(_GRID, watershed=_CATCHMENT, synthetic=False)
    return planning_inputs(_GRID)


@pytest.mark.parametrize(("engine", "real"), sorted(_BASE_HASHES))
def test_a_meshed_engine_gets_no_catchment_and_keeps_its_hash(engine: str, real: bool) -> None:
    request = plan_mesh_request(MeshConfig(engine=engine, cell_size=40.0), _support(real=real))

    assert request.catchment is None
    assert request.canonical_hash() == _BASE_HASHES[engine, real]


def test_a_lumped_engine_gets_the_delineated_catchment_and_not_the_domain() -> None:
    request = plan_mesh_request(MeshConfig(engine="catchment"), _support(real=True))

    assert request.catchment is not None
    assert shapely.normalize(request.catchment).equals(shapely.normalize(_CATCHMENT))
    assert request.domain.area > request.catchment.area
    assert request.lines == () and request.size_field is None
    assert CatchmentMeshEngine().build(request).geometry.areas.tolist() == [_CATCHMENT.area]


def test_a_lumped_engine_on_a_synthetic_support_gets_the_domain() -> None:
    inputs = _support(real=False)

    request = plan_mesh_request(MeshConfig(engine="catchment"), inputs)

    assert request.catchment is not None and request.catchment.equals(inputs.domain)


def test_a_lumped_engine_on_a_real_support_without_a_catchment_is_refused() -> None:
    inputs = planning_inputs(_GRID, synthetic=False)

    with pytest.raises(MeshRequestError, match="no delineated catchment polygon"):
        plan_mesh_request(MeshConfig(engine="catchment"), inputs)
