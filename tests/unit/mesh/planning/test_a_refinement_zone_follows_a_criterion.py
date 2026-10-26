"""A refinement zone is a vector layer, or the pixels where a field passes a threshold.

The table reads like the layer one: ``where`` names the field, ``below`` or
``above`` the threshold, ``run`` the earlier run a field of a run comes from.
The planner sizes such a zone like any other, notes the share of the
catchment it covers, and records the runs the mesh depends on.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from pydantic import ValidationError
from shapely.geometry import LineString, box

from hydromodpy.core.exceptions import ConfigValidationError, MeshRequestError
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig, RiverNetworkConfig
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.cache import cache_key
from hydromodpy.spatial.mesh.config.mesh import MeshConfig
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.planning.geographic import prepare_geographic_config_for_mesh
from hydromodpy.spatial.mesh.planning.inputs import PlanningInputs
from hydromodpy.spatial.mesh.planning.plan import plan_mesh_request
from hydromodpy.spatial.mesh.planning.refinement import CriterionInputs, load_refinement_zones
from hydromodpy.spatial.mesh.port import MeshEngineCapabilities
from hydromodpy.spatial.mesh.refinement.refinement_zones import RefinementZoneConfig
from hydromodpy.spatial.mesh.refinement.run_fields import RunFieldEnvelope, cells_on_grid
from hydromodpy.spatial.mesh.request import RasterGridSpec
from hydromodpy.spatial.mesh.sizing.size_field import PixelRegion, sample_size_field

_WKT = 'PROJCS["RGF93 / Lambert-93"]'
_GRID = RasterGridSpec(
    xmin=0.0, xmax=1000.0, ymin=0.0, ymax=1000.0, dx=10.0, dy=10.0, nrow=100, ncol=100, crs_wkt=_WKT
)
_THALWEG_X = 505.0
_STREAM = LineString([(_THALWEG_X, 995.0), (_THALWEG_X, 5.0)])
_NO_FAMILIES = {"rivers": "none", "geology": "none", "lakes": "none", "barriers": "none"}
_HAND = {"where": "height_above_stream", "below": 2.0, "cell_size": 20.0}
_SIM_ID = "0123456789abcdef0123456789abcdef"


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
        "voronoi": SimpleNamespace(capabilities=_capabilities(graded=True)),
    }
    monkeypatch.setattr(registry, "get", lambda engine_id=None: engines[engine_id])


def _valley() -> np.ndarray:
    """A V valley whose thalweg runs north-south at x = 505 m, 0.1 m of rise per metre."""
    x = _GRID.xmin + _GRID.dx * (np.arange(_GRID.ncol) + 0.5)
    y = _GRID.ymax - _GRID.dy * (np.arange(_GRID.nrow) + 0.5)
    return 100.0 + 0.1 * np.abs(x[None, :] - _THALWEG_X) + 0.01 * y[:, None]


def _envelope(sim_id: str = _SIM_ID) -> RunFieldEnvelope:
    """Two cells, west and east halves; the water table came within 0.5 m of the west one."""
    vertices = np.array([[0, 0], [500, 0], [1000, 0], [1000, 1000], [500, 1000], [0, 1000]], float)
    connectivity = np.array([[0, 1, 4, 5], [1, 2, 3, 4]])
    return RunFieldEnvelope(
        sim_id=sim_id,
        run="coarse",
        field="watertable_depth",
        unit="m",
        vertices=vertices,
        connectivity=connectivity,
        minimum=np.array([0.5, 3.0]),
        maximum=np.array([4.0, 6.0]),
    )


def _criteria(*, streams: bool = True, sim_id: str = _SIM_ID) -> CriterionInputs:
    return CriterionInputs(
        grid=_GRID,
        elevation=_valley(),
        stream_lines=(_STREAM,) if streams else None,
        run_fields={("coarse", "watertable_depth"): _envelope(sim_id)},
    )


def _zones(*tables: dict, criteria: CriterionInputs | None) -> tuple:
    return load_refinement_zones(
        [RefinementZoneConfig.model_validate(table) for table in tables],
        config_dir=None,
        data_dir=None,
        crs_wkt="EPSG:2154",
        criteria=criteria,
    )


def _inputs(zones: tuple) -> PlanningInputs:
    return PlanningInputs(
        dem_grid=_GRID,
        crs_wkt=_WKT,
        domain=box(0.0, 0.0, 1000.0, 1000.0),
        river_trace=None,
        watershed=box(100.0, 100.0, 900.0, 900.0),
        lakes=(),
        lake_structures=(),
        geology=None,
        refinement_zones=zones,
        input_triangulation=None,
        synthetic=False,
    )


def _voronoi(*tables: dict) -> MeshConfig:
    return MeshConfig(
        engine="voronoi", cell_size=80.0, families=_NO_FAMILIES, refinement_zone=list(tables)
    )


_RUN_ZONE = {"where": "watertable_depth", "below": 1.0, "run": "coarse", "cell_size": 20.0}


@pytest.mark.parametrize(
    ("table", "words"),
    [
        ({"cell_size": 20.0}, ("either path", "where")),
        ({"path": "z.gpkg", **_HAND}, ("exactly one",)),
        ({**_HAND, "below": 0.0}, ("below", "greater than 0")),
        ({**_HAND, "below": -1.0}, ("greater than 0",)),
        ({"where": "height_above_stream", "above": 1.0, "cell_size": 20.0}, ("give below",)),
        ({**_HAND, "run": "coarse"}, ("reads no run",)),
        ({"where": "seepage", "above": 0.5, "cell_size": 20.0}, ("name it with run",)),
        ({**_RUN_ZONE, "above": 2.0}, ("not both",)),
        ({"where": "watertable_depth", "run": "coarse", "cell_size": 20.0}, ("one threshold",)),
        ({"path": "z.gpkg", "below": 1.0, "cell_size": 20.0}, ("drop below",)),
        ({"where": "slope", "below": 1.0, "cell_size": 20.0}, ("where",)),
        ({**_HAND, "radius": 3.0}, ("radius",)),
    ],
)
def test_a_zone_says_one_field_and_its_threshold_or_is_refused(
    table: dict, words: tuple[str, ...]
) -> None:
    with pytest.raises(ValidationError) as raised:
        RefinementZoneConfig.model_validate(table)
    for word in words:
        assert word in str(raised.value)


def test_a_layer_zone_reads_as_it_did_and_a_zone_dumps_back() -> None:
    layer = RefinementZoneConfig.model_validate({"path": "z.gpkg", "cell_size": 20.0})
    criterion = RefinementZoneConfig.model_validate({**_RUN_ZONE, "where": " WaterTable_Depth "})

    assert layer.where is None and layer.below is None and layer.run is None
    assert criterion.where == "watertable_depth"
    for zone in (layer, criterion):
        assert RefinementZoneConfig.model_validate(zone.model_dump()) == zone
    assert criterion.describe() == "watertable_depth below 1 m in run coarse"
    seepage = RefinementZoneConfig(where="seepage", above=0.5, run="coarse", cell_size=20.0)
    assert seepage.describe() == "seepage above 0.5 mm/d in run coarse"


def test_a_zone_on_the_height_above_the_stream_needs_the_traced_network() -> None:
    hand = _voronoi(_HAND)

    assert hand.requires_river_trace(active_bc=set(), synthetic=False) is True
    assert _voronoi().requires_river_trace(active_bc=set(), synthetic=False) is False
    assert (
        MeshConfig(engine="regular", refinement_zone=[_HAND]).requires_river_trace(
            active_bc=set(), synthetic=False
        )
        is False
    )
    network = RiverNetworkConfig(threshold_area_km2=None)
    geographic = GeographicConfig(source_mode="synthetic", river_network=network).model_copy(
        update={"source_mode": "standard"}
    )
    with pytest.raises(ConfigValidationError, match="where = 'height_above_stream'"):
        prepare_geographic_config_for_mesh(geographic, hand, active_bc=())


def test_the_zone_holds_the_pixels_less_than_the_threshold_above_the_thalweg() -> None:
    (zone,) = _zones(_HAND, criteria=_criteria())

    assert isinstance(zone.region, PixelRegion)
    columns = np.flatnonzero(zone.region.mask.all(axis=0))
    assert columns.tolist() == [49, 50, 51]
    assert zone.region.mask.sum() == 3 * _GRID.nrow
    assert zone.source_run is None
    assert zone.cell_size_m == 20.0 and zone.ramp_m == 40.0


def test_a_zone_on_the_height_above_the_stream_without_a_network_is_refused() -> None:
    with pytest.raises(MeshRequestError, match=r"\[geographic.river_network\]"):
        _zones(_HAND, criteria=_criteria(streams=False))


def test_the_zone_of_a_run_holds_the_cells_where_its_field_passed_the_threshold() -> None:
    (shallow,) = _zones(_RUN_ZONE, criteria=_criteria())
    (deep,) = _zones({**_RUN_ZONE, "below": None, "above": 5.0}, criteria=_criteria())

    assert shallow.source_run == _SIM_ID
    assert shallow.region.mask[:, :50].all() and not shallow.region.mask[:, 50:].any()
    assert deep.region.mask[:, 50:].all() and not deep.region.mask[:, :50].any()


def test_a_zone_of_a_run_the_mesh_step_did_not_read_is_refused() -> None:
    with pytest.raises(MeshRequestError, match="read no such field"):
        _zones({**_RUN_ZONE, "run": "other"}, criteria=_criteria())


def test_the_threshold_is_passed_at_some_time_step_and_never_on_an_undefined_cell() -> None:
    envelope = dataclasses.replace(
        _envelope(), minimum=np.array([np.nan, 0.2]), maximum=np.array([np.nan, 0.9])
    )

    assert envelope.passing(below=0.5, above=None).tolist() == [False, True]
    assert envelope.passing(below=None, above=0.5).tolist() == [False, True]
    with pytest.raises(MeshRequestError):
        envelope.passing(below=0.5, above=0.5)


def test_a_cell_smaller_than_a_pixel_still_marks_the_pixel_under_it() -> None:
    vertices = np.array([[201.0, 201.0], [203.0, 201.0], [203.0, 203.0], [201.0, 203.0]])

    mask = cells_on_grid(vertices, np.array([[0, 1, 2, 3]]), np.array([True]), _GRID)

    assert mask.sum() == 1 and mask[79, 20]


def test_without_a_graded_engine_a_zone_drawn_by_a_threshold_is_left_out(tmp_path: Path) -> None:
    path = tmp_path / "zone.geojson"
    gpd.GeoDataFrame(geometry=[box(600.0, 600.0, 700.0, 700.0)], crs="EPSG:2154").to_file(path)

    zones = _zones(_HAND, {"path": str(path), "cell_size": 15.0}, criteria=None)

    assert len(zones) == 1 and zones[0].label == f"layer {path}"
    request = plan_mesh_request(
        MeshConfig(engine="regular", cell_size=80.0, refinement_zone=[_HAND]), _inputs(zones)
    )
    assert request.size_field is None and request.source_runs == ()
    assert any("ignores refinement_zone" in note for note in request.notes)


def test_the_size_field_refines_the_valley_floor_and_grows_away_from_it() -> None:
    request = plan_mesh_request(_voronoi(_HAND), _inputs(_zones(_HAND, criteria=_criteria())))

    field = request.size_field
    assert field is not None
    sizes = sample_size_field(field, np.array([[505.0, 505.0], [515.0, 505.0], [805.0, 505.0]]))
    assert sizes[0] == pytest.approx(20.0) and sizes[1] == pytest.approx(20.0)
    assert sizes[2] == pytest.approx(80.0)
    assert request.source_runs == ()
    assert any("covers 3.8 % of the catchment, at 20 m" in note for note in request.notes)


def test_the_mesh_depends_on_the_run_it_was_refined_on() -> None:
    def request(sim_id: str):
        zones = _zones(_RUN_ZONE, criteria=_criteria(sim_id=sim_id))
        return plan_mesh_request(_voronoi(_RUN_ZONE), _inputs(zones))

    first, second = request(_SIM_ID), request("f" * 32)
    engine = SimpleNamespace(engine_id="voronoi", engine_version="1.0.0")

    assert first.source_runs == (_SIM_ID,)
    np.testing.assert_array_equal(first.size_field.values, second.size_field.values)
    assert first.canonical_hash() != second.canonical_hash()
    assert cache_key(first, engine) != cache_key(second, engine)
    unbound = dataclasses.replace(first, source_runs=())
    assert unbound.canonical_hash() != first.canonical_hash()
    assert cache_key(unbound, engine) != cache_key(first, engine)


def test_a_threshold_nothing_passes_refines_nothing_and_says_so() -> None:
    nowhere = {**_RUN_ZONE, "below": 0.1}
    request = plan_mesh_request(_voronoi(nowhere), _inputs(_zones(nowhere, criteria=_criteria())))

    assert request.size_field is not None
    assert np.all(request.size_field.values >= 80.0)
    assert request.source_runs == (_SIM_ID,)
    assert any("selects no pixel and refines nothing" in note for note in request.notes)
