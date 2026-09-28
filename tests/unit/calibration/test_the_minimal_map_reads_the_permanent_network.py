"""The minimal map resolves from the run's permanent hydrographic network, or refuses by name.

``minimal_observed_network = "data.hydrography"`` reads the network the
geographic pipeline attached under the ``reference_permanent`` role
(:class:`hydromodpy.spatial.geographic.core.hydrographic_network.HydrographicNetworks`),
never the full ``reference`` one: a source that does not say which reaches are
permanent (a custom file with no permanence column, OSM) leaves that role
``None``, and the output is refused by name rather than silently scored on the
maximal map.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config import validate_calib_output
from hydromodpy.calibration.observations.network_source import UnresolvedObservedNetwork
from hydromodpy.calibration.observations.observed_network import resolve_minimal_network

gpd = pytest.importorskip("geopandas")
shapely = pytest.importorskip("shapely")

from shapely.geometry import LineString  # noqa: E402

CRS = "EPSG:2154"


def _output(**overrides):
    return validate_calib_output(
        {"support": "network", "observed_network": "data.hydrography", **overrides}
    )


def _permanent_network(vector_path="/data/streams_permanent.shp", crs=CRS):
    gdf = gpd.GeoDataFrame(
        geometry=[LineString([(0, 0), (1, 1)]), LineString([(1, 1), (2, 2)])], crs=crs
    )
    return SimpleNamespace(vector_path=vector_path, crs=crs, read_vector=lambda: gdf)


def _run_ctx(*, reference_permanent=None):
    networks = SimpleNamespace(reference_permanent=reference_permanent)
    geographic_features = SimpleNamespace(hydrographic_networks=networks)
    setup = SimpleNamespace(geographic_features=geographic_features)
    return SimpleNamespace(state=SimpleNamespace(setup=setup))


class TestAReferencePermanentNetworkIsScored:
    def test_the_run_s_reference_permanent_network_resolves_the_minimal_map(self) -> None:
        run_ctx = _run_ctx(reference_permanent=_permanent_network())
        output = _output(minimal_observed_network="data.hydrography")

        resolved = resolve_minimal_network(run_ctx, output)

        assert resolved is not None
        assert resolved.source == "data.hydrography"
        assert resolved.clipped is True
        assert resolved.dem_derived is False
        assert resolved.path == "/data/streams_permanent.shp"
        assert resolved.crs == CRS
        assert len(resolved.geometry) == 2

    def test_it_never_reads_the_full_reference_network(self) -> None:
        # A run carrying only the maximal network (no permanence in its source)
        # must not be silently scored on it under the minimal role.
        run_ctx = SimpleNamespace(
            state=SimpleNamespace(
                setup=SimpleNamespace(
                    geographic_features=SimpleNamespace(
                        hydrographic_networks=SimpleNamespace(
                            reference=_permanent_network(vector_path="/data/streams.shp"),
                            reference_permanent=None,
                        )
                    )
                )
            )
        )
        output = _output(minimal_observed_network="data.hydrography")

        with pytest.raises(UnresolvedObservedNetwork):
            resolve_minimal_network(run_ctx, output)


class TestARunWithoutAPermanentNetworkIsRefusedByName:
    def test_a_run_without_reference_permanent_is_refused_by_name(self) -> None:
        run_ctx = _run_ctx(reference_permanent=None)
        output = _output(minimal_observed_network="data.hydrography")

        with pytest.raises(UnresolvedObservedNetwork) as excinfo:
            resolve_minimal_network(run_ctx, output)
        message = str(excinfo.value)
        assert "minimal_observed_network" in message
        assert "data.hydrography" in message
        assert "minimal_stream_geometry_path" in message

    def test_no_minimal_source_declared_resolves_to_none(self) -> None:
        run_ctx = _run_ctx(reference_permanent=_permanent_network())
        output = _output()

        assert resolve_minimal_network(run_ctx, output) is None


class TestTheExplicitFileStillResolves:
    def test_a_declared_file_is_read_regardless_of_the_run_s_permanent_network(
        self, tmp_path
    ) -> None:
        path = tmp_path / "permanent.gpkg"
        gpd.GeoDataFrame(geometry=[LineString([(0, 0), (1, 1)])], crs=CRS).to_file(
            path, driver="GPKG"
        )
        run_ctx = _run_ctx(reference_permanent=None)
        output = _output(minimal_stream_geometry_path=str(path))

        resolved = resolve_minimal_network(run_ctx, output)

        assert resolved is not None
        assert resolved.source == "path"
        assert resolved.clipped is False
        assert resolved.path == str(path)
