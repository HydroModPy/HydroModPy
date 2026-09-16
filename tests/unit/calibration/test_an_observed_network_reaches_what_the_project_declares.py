"""An observed network resolves from what the output names, or refuses by naming why.

Three sources: the network the data layer loaded and clipped, the network the
DEM pipeline derived, and an explicit file. Four refusals: each in-memory
source can be absent, either can resolve to nothing, and either can resolve to
polygons instead of lines.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config import validate_calib_output
from hydromodpy.calibration.observations.network_source import (
    ObservedNetwork,
    UnresolvedObservedNetwork,
    resolve_observed_network,
    unresolved_observed_networks,
)

gpd = pytest.importorskip("geopandas")
shapely = pytest.importorskip("shapely")

from shapely.geometry import LineString, Polygon  # noqa: E402

CRS = "EPSG:2154"


def _output(**overrides):
    return validate_calib_output({"support": "network", **overrides})


def _network(vector_path=None, crs="EPSG:2154"):
    """A fake `HydrographicNetwork`: reads back whatever `write` last stored."""
    state = {"gdf": None}

    def write(gdf):
        state["gdf"] = gdf

    return SimpleNamespace(
        vector_path=vector_path,
        crs=crs,
        read_vector=lambda: state["gdf"],
        _write=write,
    )


def _run_ctx(*, reference=None, generated=None):
    networks = SimpleNamespace(reference=reference, generated=generated)
    geographic_features = SimpleNamespace(hydrographic_networks=networks)
    setup = SimpleNamespace(geographic_features=geographic_features)
    return SimpleNamespace(state=SimpleNamespace(setup=setup))


def _lines_gdf():
    return gpd.GeoDataFrame(
        geometry=[LineString([(0, 0), (1, 1)]), LineString([(1, 1), (2, 2)])], crs=CRS
    )


def _polygon_gdf():
    return gpd.GeoDataFrame(geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])], crs=CRS)


def _empty_gdf():
    return gpd.GeoDataFrame(geometry=[], crs=CRS)


class TestTheThreeRoutes:
    def test_data_hydrography_reads_the_reference_network_in_memory(self) -> None:
        network = _network(vector_path="/data/streams.shp")
        network._write(_lines_gdf())
        run_ctx = _run_ctx(reference=network)
        output = _output(observed_network="data.hydrography")

        resolved = resolve_observed_network(run_ctx, output)

        assert isinstance(resolved, ObservedNetwork)
        assert resolved.source == "data.hydrography"
        assert resolved.clipped is True
        assert resolved.dem_derived is False
        assert resolved.path == "/data/streams.shp"
        assert resolved.crs == CRS
        assert len(resolved.geometry) == 2

    def test_geographic_river_network_reads_the_generated_network_in_memory(self) -> None:
        network = _network(vector_path="/geo/river_network.shp")
        network._write(_lines_gdf())
        run_ctx = _run_ctx(generated=network)
        output = _output(observed_network="geographic.river_network")

        resolved = resolve_observed_network(run_ctx, output)

        assert resolved.source == "geographic.river_network"
        assert resolved.clipped is True
        assert resolved.dem_derived is True
        assert resolved.path == "/geo/river_network.shp"

    def test_neither_source_reads_the_explicit_file(self, tmp_path) -> None:
        path = tmp_path / "streams.gpkg"
        _lines_gdf().to_file(path, driver="GPKG")
        run_ctx = _run_ctx()
        output = _output(stream_geometry_path=str(path))

        resolved = resolve_observed_network(run_ctx, output)

        assert resolved.source == "path"
        assert resolved.clipped is False
        assert resolved.dem_derived is False
        assert resolved.path == str(path)
        assert len(resolved.geometry) == 2


class TestNothingIsWrittenBack:
    def test_the_output_keeps_its_own_declaration_after_resolving(self) -> None:
        # HydroModelBase sets validate_assignment=True: writing the resolved
        # path back would make the both-declared refusal fire on a second pass.
        network = _network()
        network._write(_lines_gdf())
        run_ctx = _run_ctx(reference=network)
        output = _output(observed_network="data.hydrography")

        resolve_observed_network(run_ctx, output)

        assert output.observed_network == "data.hydrography"
        assert output.stream_geometry_path is None


class TestTheFourRefusals:
    def test_data_hydrography_named_with_no_reference_network(self) -> None:
        run_ctx = _run_ctx(reference=None)
        output = _output(observed_network="data.hydrography")

        with pytest.raises(UnresolvedObservedNetwork, match=r"data\.hydrography\.sources"):
            resolve_observed_network(run_ctx, output)

    def test_geographic_river_network_named_with_nothing_generated(self) -> None:
        run_ctx = _run_ctx(generated=None)
        output = _output(observed_network="geographic.river_network")

        with pytest.raises(UnresolvedObservedNetwork, match="enabled = true"):
            resolve_observed_network(run_ctx, output)

    def test_a_resolved_geometry_with_no_line_is_refused_by_source(self) -> None:
        network = _network()
        network._write(_empty_gdf())
        run_ctx = _run_ctx(generated=network)
        output = _output(observed_network="geographic.river_network")

        with pytest.raises(UnresolvedObservedNetwork) as excinfo:
            resolve_observed_network(run_ctx, output)
        message = str(excinfo.value)
        assert "geographic.river_network" in message
        assert "no line" in message

    def test_a_resolved_polygon_is_refused_by_name(self) -> None:
        network = _network()
        network._write(_polygon_gdf())
        run_ctx = _run_ctx(reference=network)
        output = _output(observed_network="data.hydrography")

        with pytest.raises(UnresolvedObservedNetwork) as excinfo:
            resolve_observed_network(run_ctx, output)
        message = str(excinfo.value)
        assert "data.hydrography" in message
        assert "Polygon" in message


class TestTheReportingTwin:
    def _calibration(self, **outputs):
        # A bare holder of real `CalibOutputNetwork` instances: the function
        # under test reads only `.outputs`, and going through
        # `CalibrationConfig.model_validate` would require pairing every
        # network output with an objective block, which is a different guard.
        return SimpleNamespace(outputs=outputs)

    def _project(self, *, hydrography_sources=None, river_network_enabled=False):
        hydrography = None
        if hydrography_sources is not None:
            hydrography = SimpleNamespace(sources=hydrography_sources)
        return SimpleNamespace(
            data=SimpleNamespace(hydrography=hydrography),
            geographic=SimpleNamespace(
                river_network=SimpleNamespace(enabled=river_network_enabled)
            ),
        )

    def test_a_declared_source_the_project_carries_is_left_alone(self) -> None:
        calibration = self._calibration(net=_output(observed_network="data.hydrography"))
        project = self._project(hydrography_sources=[SimpleNamespace(source="osm")])

        assert unresolved_observed_networks(calibration, project) == {}

    def test_data_hydrography_named_with_no_section_is_reported(self) -> None:
        calibration = self._calibration(net=_output(observed_network="data.hydrography"))
        project = self._project(hydrography_sources=None)

        refused = unresolved_observed_networks(calibration, project)

        assert set(refused) == {"net"}
        assert "data.hydrography.sources" in refused["net"]

    def test_river_network_named_while_disabled_is_reported(self) -> None:
        calibration = self._calibration(net=_output(observed_network="geographic.river_network"))
        project = self._project(river_network_enabled=False)

        refused = unresolved_observed_networks(calibration, project)

        assert set(refused) == {"net"}
        assert "enabled = true" in refused["net"]

    def test_an_explicit_path_output_is_not_this_functions_concern(self) -> None:
        # The path route is a plain file: preflight already checks it exists
        # elsewhere (calibration/preflight.py), not through this reporting path.
        calibration = self._calibration(net=_output(stream_geometry_path="x.gpkg"))
        project = self._project()

        assert unresolved_observed_networks(calibration, project) == {}

    def test_a_calibration_with_no_output_at_all_reports_nothing(self) -> None:
        assert unresolved_observed_networks(self._calibration(), self._project()) == {}
