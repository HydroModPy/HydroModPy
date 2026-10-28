"""``CatchmentDelineation``: the runtime object the domain, the solver and the reports read.

The Whitebox backend is replaced by its double, so the delineation runs on a
10 x 10 ramp of 100 m cells in a few milliseconds.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from rasterio.errors import RasterioIOError

from hydromodpy.spatial.geographic.catchment_delineation import (
    CatchmentDelineation,
    DEM_correcflow_analysis,
)
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.terrain import registry
from tests._helpers.geographic_cases import (
    LAMBERT,
    OUTLET_CATCHMENT,
    assert_delineation_golden,
    delineate_on_fake_backend,
    delineation_signature,
    polygon_catchment,
)
from tests._helpers.geotiffs import write_geotiff
from tests._helpers.whitebox_double import FakeWhiteboxBackend


@pytest.fixture
def outlet(tmp_path, monkeypatch) -> CatchmentDelineation:
    return delineate_on_fake_backend(tmp_path, monkeypatch, OUTLET_CATCHMENT)


def test_a_missing_dem_stops_the_delineation_early(tmp_path: Path) -> None:
    config = GeographicConfig(
        catchment={**polygon_catchment(tmp_path), "dem_init_path": tmp_path / "missing_dem.tif"},
        crs_project=LAMBERT,
        dem_correc_type="breach",
    )

    with pytest.raises(RasterioIOError):
        CatchmentDelineation(
            config=config, initializing=SimpleNamespace(project_root=str(tmp_path))
        )


def test_an_outlet_delineation_writes_the_outlet_its_snap_and_the_watershed(outlet) -> None:
    for path in (
        Path(outlet.geographic_path) / "outlet.shp",
        Path(outlet.geographic_path) / "outlet_snap.shp",
        Path(outlet.watershed),
        Path(outlet.watershed_shp),
    ):
        assert path.exists(), path
    assert float(outlet.catch_area) > 0.0
    assert outlet.catch_def == "from_outlet_coord"


def test_a_polygon_delineation_hands_the_domain_its_supports(tmp_path, monkeypatch) -> None:
    geo = delineate_on_fake_backend(tmp_path, monkeypatch, polygon_catchment(tmp_path))

    for name in (
        "watershed_shp",
        "watershed_box_shp",
        "box_buff",
        "watershed_box_buff_dem",
        "watershed_dem",
        "watershed_contour_tif",
    ):
        assert Path(getattr(geo, name)).exists(), name
    georef = geo.build_georeferencing()
    assert set(georef) == {"crs", "dx", "dy", "xmin", "xmax", "ymin", "ymax"}
    assert georef["crs"] == LAMBERT
    assert (float(georef["dx"]), float(georef["dy"])) == pytest.approx((100.0, 100.0))
    context = geo.get_domain_geographic_context()
    assert (context.catch_def, context.zone_kind) == ("from_polyg_shp", "catchment")
    assert context.watershed_shp == geo.watershed_shp
    assert context.watershed_box_buff_dem == geo.watershed_box_buff_dem
    assert context.box_buff_shp == geo.box_buff
    assert float(context.catchment_area_km2) == pytest.approx(float(geo.catch_area))
    assert context.surface_topo.support is not None
    features = geo.get_geographic_derived_features()
    assert (features.catch_def, features.zone_kind) == ("from_polyg_shp", "catchment")
    assert features.boundaries.watershed_shp == geo.watershed_shp
    assert features.boundaries.box_buff_shp == geo.box_buff
    assert features.rivers.river_mesh_trace is None
    assert float(features.catchment_area_km2) == pytest.approx(float(geo.catch_area))


def test_the_dem_metadata_is_read_once_and_handed_back_on_a_second_call(outlet) -> None:
    georef = outlet.build_georeferencing()
    outlet.dx = None

    outlet.info_dem()

    assert outlet.dx == georef["dx"]
    del outlet._dem_metadata
    assert outlet.build_georeferencing() == georef


def test_a_runtime_without_its_buffered_box_is_refused_and_a_bare_network_path_is_read(
    outlet, tmp_path
) -> None:
    outlet._river_network_products = None
    outlet.hydrographic_network_generated_shp = ""
    assert outlet.get_geographic_derived_features().rivers.enabled is False

    outlet.box_buff = None
    with pytest.raises(ValueError, match="box-buffer shapefile"):
        outlet.get_geographic_derived_features()


@pytest.mark.parametrize(
    ("buff_area", "distance", "increase", "label"),
    [
        ("10%", 150.0, 0.106, "10% (150 m, +10.6% area)"),
        ("150.0 m", None, None, "150.0 m"),
        (None, None, None, "&mdash;"),
    ],
)
def test_the_notebook_view_names_the_declared_margin_and_what_it_drew(
    outlet, buff_area, distance, increase, label
) -> None:
    outlet.buff_area = buff_area
    outlet.buffer_distance_m = distance
    outlet.buffer_area_increase = increase
    outlet.x_outlet = None

    html = outlet._repr_html_()

    assert html.startswith("<div><b>CatchmentDelineation</b>")
    assert f"<th style='text-align:left;padding-right:8px'>buff_area</th><td>{label}</td>" in html
    assert "<td>&mdash;</td>" in html  # the outlet, unset


def test_the_three_regional_flow_rasters_are_built_on_the_backend_given(tmp_path) -> None:
    dem = write_geotiff(tmp_path / "dem.tif", [[3.0, 2.0], [2.0, 1.0]], nodata=-9999.0)

    products = DEM_correcflow_analysis(
        str(dem), str(tmp_path / "flow"), "fill", backend=FakeWhiteboxBackend()
    )

    assert sorted(products) == ["acc", "correc", "direc"]
    assert all(Path(path).is_file() for path in products.values())


def test_the_runtime_object_carries_the_engine_the_document_named(tmp_path, monkeypatch) -> None:
    """A solver reads the engine off the runtime object, not off the configuration.

    The object copies an explicit list of configuration attributes onto itself;
    an engine missing from that list is an engine the solver silently replaces
    with the build default.
    """
    monkeypatch.setattr(CatchmentDelineation, "processing", lambda self: None)
    engine_id = registry.builtin_engine_ids()[0]
    config = GeographicConfig.model_validate(
        {
            "catchment": {"catch_def": "dem", "dem_init_path": __file__},
            "terrain_engine": engine_id,
        }
    )

    delineation = CatchmentDelineation(config, SimpleNamespace(project_root=str(tmp_path)))

    assert delineation.terrain_engine == engine_id


# The two goldens below are regenerated by tools/spatial/update_geographic_goldens.py,
# which names this file.
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


def test_catchment_delineation_from_outlet_golden(update_goldens, tmp_path, monkeypatch) -> None:
    geo = delineate_on_fake_backend(tmp_path, monkeypatch, OUTLET_CATCHMENT)

    assert_delineation_golden(
        delineation_signature(geo),
        GOLDEN_DIR / "catchment_delineation_outlet_contract_golden.json",
        update_goldens,
    )


def test_catchment_delineation_from_polygon_golden(update_goldens, tmp_path, monkeypatch) -> None:
    geo = delineate_on_fake_backend(tmp_path, monkeypatch, polygon_catchment(tmp_path))

    assert_delineation_golden(
        delineation_signature(geo),
        GOLDEN_DIR / "catchment_delineation_polygon_contract_golden.json",
        update_goldens,
    )
