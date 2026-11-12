"""Resolution of an observed stream network: from the data layer or from a file.

A network output names its map either as the network the data layer loaded and
clipped (`data.hydrography`) or as a file. The map is cut to the catchment outline
(m) and refused, with its source named, when it holds no line or only polygons.
"""

from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, Polygon

from hydromodpy.calibration.config_network import CalibOutputNetwork
from hydromodpy.calibration.config_outputs import validate_calib_output
from hydromodpy.calibration.observations.network_source import (
    ObservedNetwork,
    UnresolvedObservedNetwork,
    cut_to_the_catchment,
    resolve_observed_network,
    unresolved_observed_networks,
)
from hydromodpy.calibration.observations.observed_network import observed_network_mask
from tests._helpers.ugrid_meshes import quad_mesh
from tests._helpers.v_valley import (
    AXIS_COL,
    CELL_SIZE,
    FIRST_OBSERVED_ROW,
    N_COLS,
    N_ROWS,
)
from tests.unit.calibration._factories_scoring import make_trial_ctx

CRS = "EPSG:2154"
SQUARE = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])


def network_output(**overrides):
    return validate_calib_output({"support": "network", **overrides})


def data_network(vector_path=None):
    """A fake `HydrographicNetwork`: reads back whatever `write` last stored."""
    state = {"gdf": None}

    def write(gdf):
        state["gdf"] = gdf

    return SimpleNamespace(
        vector_path=vector_path, crs=CRS, read_vector=lambda: state["gdf"], _write=write
    )


def run_ctx_with(*, reference=None):
    networks = SimpleNamespace(reference=reference)
    geographic_features = SimpleNamespace(hydrographic_networks=networks)
    setup = SimpleNamespace(geographic_features=geographic_features)
    return SimpleNamespace(state=SimpleNamespace(setup=setup))


def write_lines(path, *lines):
    gpd.GeoDataFrame(geometry=list(lines), crs=CRS).to_file(path, driver="GPKG")
    return path


def catchment_ctx(tmp_path, *, reference=None):
    """A run whose delineated catchment is the square of 10 m."""
    mask = write_lines(tmp_path / "watershed.gpkg", SQUARE)
    run_ctx = run_ctx_with(reference=reference)
    run_ctx.state.setup.geographic = SimpleNamespace(watershed_shp=str(mask))
    return run_ctx


def streams_file(tmp_path):
    return write_lines(tmp_path / "streams.gpkg", LineString([(5, 5), (5, 20)]))


def cut(run_ctx, output):
    return cut_to_the_catchment(run_ctx, resolve_observed_network(run_ctx, output), output)


def test_file_is_cut_and_names_the_outline(tmp_path):
    run_ctx = catchment_ctx(tmp_path)
    output = network_output(map={"complete": str(streams_file(tmp_path))})

    result = cut(run_ctx, output)

    assert result.clipped is True
    assert result.geometry.total_bounds[3] == pytest.approx(10.0)
    assert result.cut_outline.equals(SQUARE)


def test_file_and_data_layer_draw_the_same_map(tmp_path):
    reference = data_network(vector_path="/data/streams.shp")
    run_ctx = catchment_ctx(tmp_path, reference=reference)
    path = streams_file(tmp_path)
    from_file = cut(run_ctx, network_output(map={"complete": str(path)}))
    reference._write(gpd.clip(gpd.read_file(path), SQUARE))

    from_data = cut(run_ctx, network_output(map={"complete": "data.hydrography"}))

    assert from_file.clipped and from_data.clipped
    assert from_file.geometry.geometry.iloc[0].equals(from_data.geometry.geometry.iloc[0])
    assert from_data.cut_outline.equals(from_file.cut_outline)


def test_line_touching_the_outline_keeps_its_lines_and_no_point(tmp_path):
    run_ctx = catchment_ctx(tmp_path)
    path = write_lines(
        tmp_path / "touching.gpkg",
        LineString([(10, 5), (20, 5)]),
        LineString([(10, 2), (12, 5), (10, 8), (5, 8)]),
    )

    result = cut(run_ctx, network_output(map={"complete": str(path)}))

    assert set(result.geometry.geom_type) <= {"LineString", "MultiLineString"}
    assert result.geometry.geometry.length.sum() == pytest.approx(5.0)


def test_clip_off_keeps_the_file_whole(tmp_path):
    run_ctx = catchment_ctx(tmp_path)
    output = network_output(
        map={"complete": str(streams_file(tmp_path)), "clip_to_catchment": False}
    )

    kept = cut(run_ctx, output)

    assert kept.clipped is False
    assert kept.cut_outline is None
    assert kept.geometry.total_bounds[3] == pytest.approx(20.0)


def sealed_output():
    return CalibOutputNetwork.model_validate(
        {"support": "network", "map": {"permanent": "p.gpkg", "calibrate_on": "permanent"}},
        context={"validation_context": "snapshot"},
    )


def data_hydrography_output():
    return network_output(map={"complete": "data.hydrography"})


def empty_data_ctx():
    network = data_network()
    network._write(gpd.GeoDataFrame(geometry=[], crs=CRS))
    return run_ctx_with(reference=network)


def polygon_data_ctx():
    network = data_network()
    network._write(gpd.GeoDataFrame(geometry=[SQUARE], crs=CRS))
    return run_ctx_with(reference=network)


REFUSALS = [
    pytest.param(
        run_ctx_with(reference=None),
        data_hydrography_output(),
        ["data.hydrography.sources"],
        id="no reference network",
    ),
    pytest.param(
        run_ctx_with(), sealed_output(), ["no complete map"], id="sealed output without a map"
    ),
    pytest.param(
        empty_data_ctx(),
        data_hydrography_output(),
        ["data.hydrography", "no line"],
        id="geometry with no line",
    ),
    pytest.param(
        polygon_data_ctx(),
        data_hydrography_output(),
        ["data.hydrography", "Polygon"],
        id="polygons",
    ),
]


@pytest.mark.parametrize(("run_ctx", "output", "fragments"), REFUSALS)
def test_refusals(run_ctx, output, fragments):
    with pytest.raises(UnresolvedObservedNetwork) as excinfo:
        resolve_observed_network(run_ctx, output)

    for fragment in fragments:
        assert fragment in str(excinfo.value)


def test_map_out_of_the_catchment_is_refused(tmp_path):
    run_ctx = catchment_ctx(tmp_path)
    path = write_lines(tmp_path / "away.gpkg", LineString([(50, 50), (60, 60)]))

    with pytest.raises(UnresolvedObservedNetwork, match="no line inside the catchment"):
        cut(run_ctx, network_output(map={"complete": str(path)}))


def reporting_inputs(hydrography_sources=None):
    # `unresolved_observed_networks` reads only `.outputs`, so a bare holder of real
    # outputs is enough. A full config would need an objective block for each one.
    calibration = SimpleNamespace(outputs={"net": data_hydrography_output()})
    hydrography = None
    if hydrography_sources is not None:
        hydrography = SimpleNamespace(sources=hydrography_sources)
    project = SimpleNamespace(data=SimpleNamespace(hydrography=hydrography))
    return calibration, project


def test_declared_source_the_project_carries_is_left_alone():
    calibration, project = reporting_inputs([SimpleNamespace(source="osm")])

    assert unresolved_observed_networks(calibration, project) == {}


def test_data_hydrography_with_no_section_is_reported():
    refused = unresolved_observed_networks(*reporting_inputs(None))

    assert set(refused) == {"net"}
    assert "data.hydrography.sources" in refused["net"]


# The mask is built from the geometry handed over, never from a path.

AXIS_LINE = LineString(
    [
        ((AXIS_COL + 0.5) * CELL_SIZE, (row + 0.5) * CELL_SIZE)
        for row in range(FIRST_OBSERVED_ROW, N_ROWS)
    ]
)

UNDRAWABLE = [
    pytest.param(
        gpd.GeoDataFrame(geometry=[AXIS_LINE], crs=CRS).iloc[:0],
        CRS,
        "holds no feature",
        id="empty",
    ),
    pytest.param(gpd.GeoDataFrame(geometry=[AXIS_LINE]), None, "declares no CRS", id="no crs"),
]


@pytest.mark.parametrize(("geometry", "crs", "message"), UNDRAWABLE)
def test_geometry_that_cannot_be_drawn_is_refused(bench, geometry, crs, message):
    resolved = ObservedNetwork(
        source="path", geometry=geometry, crs=crs, clipped=False, path="whatever.gpkg"
    )
    vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
    run_ctx = make_trial_ctx(bench, networks={"reference": None})

    with pytest.raises(ValueError, match=message):
        observed_network_mask(run_ctx, resolved, SimpleNamespace(vertices=vertices), connectivity)
