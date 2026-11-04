"""Tests of `observations.network_source`."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, Polygon

from hydromodpy.calibration.config import validate_calib_output
from hydromodpy.calibration.metrics import solver_extract as _solver_extract
from hydromodpy.calibration.metrics.solver_extract import extract_outputs
from hydromodpy.calibration.observations import network_source
from hydromodpy.calibration.observations import observed_network as observed_module
from hydromodpy.calibration.observations.network_geometry import network_maps_from_run
from hydromodpy.calibration.observations.network_source import (
    ObservedNetwork,
    UnresolvedObservedNetwork,
    cut_to_the_catchment,
    resolve_observed_network,
    unresolved_minimal_observed_networks,
    unresolved_observed_networks,
)
from hydromodpy.calibration.observations.observed_network import observed_network_mask
from hydromodpy.core.contracts.observables import ObservableResult
from tests._helpers.ugrid_meshes import quad_mesh
from tests._helpers.v_valley import (
    AXIS_COL,
    CELL_SIZE,
    FIRST_OBSERVED_ROW,
    N_CELLS,
    N_COLS,
    N_ROWS,
    build_bench,
    simulated_network,
)
from tests.unit.calibration._factories_scoring import adapter_result, make_trial_ctx

# From test_an_observed_network_reaches_what_the_project_declares.py
# An observed network resolves from what the output names, or refuses by naming why.
#
# Three sources: the network the data layer loaded and clipped, the network the
# DEM pipeline derived, and an explicit file. Four refusals: each in-memory
# source can be absent, either can resolve to nothing, and either can resolve to
# polygons instead of lines.


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


class TestTheCutToTheCatchment:
    """A file and the network the data layer loaded draw one map, from one mask."""

    def _with_a_mask(self, tmp_path, *, reference=None):
        mask = tmp_path / "watershed.gpkg"
        square = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        gpd.GeoDataFrame(geometry=[square], crs=CRS).to_file(mask, driver="GPKG")
        run_ctx = _run_ctx(reference=reference)
        run_ctx.state.setup.geographic = SimpleNamespace(watershed_shp=str(mask))
        return run_ctx, square

    def _file(self, tmp_path):
        path = tmp_path / "streams.gpkg"
        line = LineString([(5, 5), (5, 20)])
        gpd.GeoDataFrame(geometry=[line], crs=CRS).to_file(path, driver="GPKG")
        return path

    def test_a_file_is_cut_and_names_the_outline(self, tmp_path) -> None:
        run_ctx, square = self._with_a_mask(tmp_path)
        output = _output(stream_geometry_path=str(self._file(tmp_path)))

        cut = cut_to_the_catchment(run_ctx, resolve_observed_network(run_ctx, output), output)

        assert cut.clipped is True
        assert cut.geometry.total_bounds[3] == pytest.approx(10.0)
        assert cut.cut_outline.equals(square)

    def test_the_two_routes_draw_the_same_map(self, tmp_path) -> None:
        reference = _network(vector_path="/data/streams.shp")
        run_ctx, _ = self._with_a_mask(tmp_path, reference=reference)
        whole = gpd.read_file(self._file(tmp_path))
        output_file = _output(stream_geometry_path=str(self._file(tmp_path)))
        from_file = cut_to_the_catchment(
            run_ctx, resolve_observed_network(run_ctx, output_file), output_file
        )
        reference._write(gpd.clip(whole, Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])))
        output_data = _output(observed_network="data.hydrography")

        from_data = cut_to_the_catchment(
            run_ctx, resolve_observed_network(run_ctx, output_data), output_data
        )

        assert from_file.clipped and from_data.clipped
        assert from_file.geometry.geometry.iloc[0].equals(from_data.geometry.geometry.iloc[0])
        assert from_data.cut_outline.equals(from_file.cut_outline)

    def test_a_line_that_touches_the_outline_keeps_its_lines_and_no_point(self, tmp_path) -> None:
        run_ctx, _ = self._with_a_mask(tmp_path)
        path = tmp_path / "touching.gpkg"
        lines = [LineString([(10, 5), (20, 5)]), LineString([(10, 2), (12, 5), (10, 8), (5, 8)])]
        gpd.GeoDataFrame(geometry=lines, crs=CRS).to_file(path, driver="GPKG")
        output = _output(stream_geometry_path=str(path))

        cut = cut_to_the_catchment(run_ctx, resolve_observed_network(run_ctx, output), output)

        assert set(cut.geometry.geom_type) <= {"LineString", "MultiLineString"}
        assert cut.geometry.geometry.length.sum() == pytest.approx(5.0)

    def test_false_keeps_the_file_whole_and_every_end(self, tmp_path) -> None:
        run_ctx, _ = self._with_a_mask(tmp_path)
        output = _output(
            stream_geometry_path=str(self._file(tmp_path)), clip_map_to_catchment=False
        )

        kept = cut_to_the_catchment(run_ctx, resolve_observed_network(run_ctx, output), output)

        assert kept.clipped is False
        assert kept.cut_outline is None
        assert kept.geometry.total_bounds[3] == pytest.approx(20.0)

    def test_a_run_with_no_mask_keeps_the_map(self, tmp_path) -> None:
        run_ctx = _run_ctx()
        output = _output(stream_geometry_path=str(self._file(tmp_path)))

        kept = cut_to_the_catchment(run_ctx, resolve_observed_network(run_ctx, output), output)

        assert kept.clipped is False
        assert kept.cut_outline is None

    def test_a_map_out_of_the_catchment_is_refused_by_name(self, tmp_path) -> None:
        run_ctx, _ = self._with_a_mask(tmp_path)
        path = tmp_path / "away.gpkg"
        line = LineString([(50, 50), (60, 60)])
        gpd.GeoDataFrame(geometry=[line], crs=CRS).to_file(path, driver="GPKG")
        output = _output(stream_geometry_path=str(path))

        with pytest.raises(UnresolvedObservedNetwork, match="no line inside the catchment"):
            cut_to_the_catchment(run_ctx, resolve_observed_network(run_ctx, output), output)


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


class TestTheMinimalMapsReportingTwin:
    """Same static check, for ``minimal_observed_network`` rather than ``observed_network``.

    A run's ``reference_permanent`` role can only be known once the geographic
    pipeline has read the source, so the reporting twin here still cannot see a
    source that declares no permanence column (a custom file, OSM): it only
    catches a ``minimal_observed_network = "data.hydrography"`` with no
    ``[[data.hydrography.sources]]`` at all, the same parity
    ``unresolved_observed_networks`` gives the maximal map.
    """

    def _calibration(self, **outputs):
        return SimpleNamespace(outputs=outputs)

    def _project(self, *, hydrography_sources=None):
        hydrography = None
        if hydrography_sources is not None:
            hydrography = SimpleNamespace(sources=hydrography_sources)
        return SimpleNamespace(data=SimpleNamespace(hydrography=hydrography))

    def test_a_declared_minimal_source_the_project_carries_is_left_alone(self) -> None:
        calibration = self._calibration(
            net=_output(
                observed_network="data.hydrography", minimal_observed_network="data.hydrography"
            )
        )
        project = self._project(hydrography_sources=[SimpleNamespace(source="bdtopage")])

        assert unresolved_minimal_observed_networks(calibration, project) == {}

    def test_minimal_data_hydrography_named_with_no_section_is_reported(self) -> None:
        calibration = self._calibration(
            net=_output(
                observed_network="data.hydrography", minimal_observed_network="data.hydrography"
            )
        )
        project = self._project(hydrography_sources=None)

        refused = unresolved_minimal_observed_networks(calibration, project)

        assert set(refused) == {"net"}
        assert "minimal_observed_network" in refused["net"]
        assert "data.hydrography.sources" in refused["net"]

    def test_an_output_with_no_minimal_map_is_not_this_functions_concern(self) -> None:
        calibration = self._calibration(net=_output(observed_network="data.hydrography"))
        project = self._project(hydrography_sources=None)

        assert unresolved_minimal_observed_networks(calibration, project) == {}

    def test_a_calibration_with_no_output_at_all_reports_nothing(self) -> None:
        assert unresolved_observed_networks(self._calibration(), self._project()) == {}


# From test_the_criterion_scores_the_network_it_was_given.py
# The network criterion scores the geometry it was handed, never a path.
#
# Three routes feed the same mask projection: the network the data layer already
# loaded (clipped, not DEM-derived), the network the DEM pipeline derived
# (clipped, DEM-derived), and an explicit file (neither). This file checks the
# wiring rather than the resolution logic itself, which
# ``test_observations_network_source.py`` already
# covers: that ``observed_network_mask`` reads an already-resolved
# ``ObservedNetwork`` and never a path, that ``network_maps_from_run`` resolves once
# per trial and threads the same resolution into the mask and into the trial
# diagnostics, and that the DEM-derived warning fires for that one route alone.


NETWORK_SOURCE_LOGGER = network_source.__name__


def _valley_axis_line() -> LineString:
    """The talweg of the V-valley bench, as the mapped network would trace it."""
    return LineString(
        [
            ((AXIS_COL + 0.5) * CELL_SIZE, (row + 0.5) * CELL_SIZE)
            for row in range(FIRST_OBSERVED_ROW, N_ROWS)
        ]
    )


def _maximal_map(run_ctx, output):
    """The geometry, the resolution and the projection of the one map declared."""
    maps = network_maps_from_run(run_ctx, output)
    return maps.maximal, maps.maximal_source, maps.maximal_projection


def _lines_gdf__criterion_scores() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=[_valley_axis_line()], crs=CRS)


def _fake_hydrographic_network(gdf, *, path: str = "/fake/network.gpkg", crs: str = CRS):
    """A `HydrographicNetwork` stand-in: hands back an in-memory GeoDataFrame."""
    return SimpleNamespace(vector_path=path, crs=crs, read_vector=lambda: gdf)


def _fake_run_ctx(bench, *, reference=None, generated=None):
    return make_trial_ctx(bench, networks={"reference": reference, "generated": generated})


def _route(bench, tmp_path, route, **network):
    """A run context and output reading the valley axis through one of the three routes."""
    gdf = _lines_gdf__criterion_scores()
    if route == "path":
        path = tmp_path / "streams.gpkg"
        gdf.to_file(path, driver="GPKG")
        return _fake_run_ctx(bench), _network_output(stream_geometry_path=str(path))
    key = "reference" if route == "data.hydrography" else "generated"
    run_ctx = _fake_run_ctx(bench, **{key: _fake_hydrographic_network(gdf, **network)})
    return run_ctx, _network_output(observed_network=route)


ROUTES = ("data.hydrography", "geographic.river_network", "path")


def _network_output(**overrides):
    return validate_calib_output(
        {
            "support": "network",
            "diagonal_neighbors": True,
            "tau_specific_ratio": 0.0,
            **overrides,
        }
    )


class TestTheMaskIsBuiltFromTheHandedGeometry:
    def test_it_never_reads_the_path_it_carries(self, bench) -> None:
        # A path that does not exist on disk: if the mask projection tried to
        # read it, this would raise before the assertion below runs at all.
        resolved = ObservedNetwork(
            source="data.hydrography",
            geometry=_lines_gdf__criterion_scores(),
            crs=CRS,
            clipped=True,
            dem_derived=False,
            path="/does/not/exist/on/this/machine.gpkg",
        )
        vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
        run_ctx = _fake_run_ctx(bench)
        planar_mesh = SimpleNamespace(vertices=vertices)

        mask = observed_network_mask(run_ctx, resolved, planar_mesh, connectivity).mask

        assert mask.dtype == bool
        assert mask.sum() > 0

    @pytest.mark.parametrize(
        ("geometry", "crs", "match"),
        [
            pytest.param(
                _lines_gdf__criterion_scores().iloc[:0], CRS, "holds no feature", id="empty"
            ),
            pytest.param(
                gpd.GeoDataFrame(geometry=[_valley_axis_line()]),
                None,
                "declares no CRS",
                id="no-crs",
            ),
        ],
    )
    def test_a_resolved_geometry_that_cannot_be_drawn_is_refused(
        self, bench, geometry, crs, match
    ) -> None:
        resolved = ObservedNetwork(
            source="path",
            geometry=geometry,
            crs=crs,
            clipped=False,
            dem_derived=False,
            path="whatever.gpkg",
        )
        vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
        planar_mesh = SimpleNamespace(vertices=vertices)

        with pytest.raises(ValueError, match=match):
            observed_network_mask(_fake_run_ctx(bench), resolved, planar_mesh, connectivity)


class TestGeometryFromRunResolvesOncePerTrial:
    def test_data_hydrography_resolves_once_and_is_clipped_not_dem_derived(
        self, bench, monkeypatch
    ) -> None:
        run_ctx, output = _route(bench, None, "data.hydrography", path="/data/streams.shp")

        calls: list[None] = []

        def spy(ctx: object, out: object) -> ObservedNetwork:
            calls.append(None)
            return resolve_observed_network(ctx, out)

        monkeypatch.setattr(network_source, "resolve_observed_network", spy)

        geometry, resolved, _projection = _maximal_map(run_ctx, output)

        assert len(calls) == 1
        assert resolved.source == "data.hydrography"
        assert resolved.clipped is True
        assert resolved.dem_derived is False
        assert resolved.path == "/data/streams.shp"
        assert geometry.observed.sum() > 0

    @pytest.mark.parametrize(
        ("route", "source", "clipped", "dem_derived"),
        [
            ("geographic.river_network", "geographic.river_network", True, True),
            ("path", "path", False, False),
        ],
    )
    def test_the_other_routes_say_whether_they_are_clipped_and_dem_derived(
        self, bench, tmp_path, route, source, clipped, dem_derived
    ) -> None:
        run_ctx, output = _route(bench, tmp_path, route, path="/geo/river_network.shp")

        _geometry, resolved, _projection = _maximal_map(run_ctx, output)

        assert resolved.source == source
        assert resolved.clipped is clipped
        assert resolved.dem_derived is dem_derived


class _ReleaseAdapter:
    """Returns the bench pattern as a per-cell release flux, for extract_outputs."""

    def __init__(self, threshold: float) -> None:
        self.threshold = threshold

    def extract_observables(self, ctx, store, requests, *, time_index=None):
        del ctx, store, time_index
        pattern = simulated_network(build_bench(), self.threshold)
        return {
            request.id: adapter_result(request.id, np.where(pattern, 1e-06, 0.0), "m3 s-1")
            for request in requests
        }


def _extract_diagnostics(monkeypatch, run_ctx, output) -> dict[str, float]:
    adapter = _ReleaseAdapter(200.0)
    monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda ctx: (adapter, run_ctx))
    extracted = extract_outputs(run_ctx, {"net": output})
    return extracted.diagnostics


class TestTheTwoFlagsReachTheTrialDiagnostics:
    @pytest.mark.parametrize(
        ("route", "clipped", "dem_derived"),
        [
            ("data.hydrography", 1.0, 0.0),
            ("geographic.river_network", 1.0, 1.0),
            ("path", 0.0, 0.0),
        ],
    )
    def test_the_route_reports_which_flags_are_set(
        self, bench, monkeypatch, tmp_path, route, clipped, dem_derived
    ) -> None:
        run_ctx, output = _route(bench, tmp_path, route)

        diagnostics = _extract_diagnostics(monkeypatch, run_ctx, output)

        assert diagnostics["net.observed_network_clipped"] == clipped
        assert diagnostics["net.observed_network_is_dem_derived"] == dem_derived
        # Travels beside alpha_obs_closure, in the same trial record.
        assert "net.alpha_obs_closure" in diagnostics


class TestTheRasterizationReachesTheTrial:
    def test_the_output_rule_and_the_solver_centres_reach_the_projection(
        self, bench, monkeypatch
    ) -> None:
        network = _fake_hydrographic_network(_lines_gdf__criterion_scores())
        run_ctx = _fake_run_ctx(bench, reference=network)
        output = _network_output(
            observed_network="data.hydrography", observed_rasterization="touch"
        )
        seen: dict[str, object] = {}
        real = observed_module.observed_network_mask

        def spy(*args, **kwargs):
            seen.update(kwargs)
            return real(*args, **kwargs)

        monkeypatch.setattr(observed_module, "observed_network_mask", spy)

        _geometry, _resolved, projection = _maximal_map(run_ctx, output)

        assert seen["rasterization"] == "touch"
        assert projection.rasterization == "touch"
        centres = np.asarray(seen["cell_centres"])
        np.testing.assert_array_equal(centres, run_ctx.model.solver_mesh.cell_centers())

    def test_the_default_rule_is_heads(self) -> None:
        assert _network_output(stream_geometry_path="map.gpkg").observed_rasterization == ("heads")

    def test_the_trial_publishes_what_the_rule_drew(self, bench, monkeypatch) -> None:
        run_ctx, output = _route(bench, None, "data.hydrography")
        output = output.model_copy(update={"observed_rasterization": "crossing"})

        diagnostics = _extract_diagnostics(monkeypatch, run_ctx, output)

        assert diagnostics["net.n_observed_cells"] == float(N_ROWS - FIRST_OBSERVED_ROW)
        assert diagnostics["net.n_observed_features_fallback"] == 0.0


class TestTheDemDerivedWarningFiresOnceAndOnlyThere:
    @pytest.fixture(autouse=True)
    def _reset_warned_flag(self, monkeypatch):
        # `_warn_dem_derived_once` is gated by a module-level flag, shared with
        # every other test in the process: reset it so this class's own
        # assertions do not depend on run order.
        monkeypatch.setattr(network_source, "_DEM_DERIVED_WARNED", False)

    @pytest.mark.parametrize(
        ("route", "warns"),
        [("geographic.river_network", True), ("data.hydrography", False), ("path", False)],
    )
    def test_only_the_dem_derived_route_warns_naming_the_reduction(
        self, bench, caplog, tmp_path, route, warns
    ) -> None:
        run_ctx, output = _route(bench, tmp_path, route)

        with caplog.at_level(logging.WARNING, logger=NETWORK_SOURCE_LOGGER):
            _maximal_map(run_ctx, output)

        said = [record for record in caplog.records if "geomorphological" in record.getMessage()]
        assert bool(said) is warns

    def test_it_fires_only_once_across_two_trials(self, bench, caplog) -> None:
        run_ctx, output = _route(bench, None, "geographic.river_network")

        with caplog.at_level(logging.WARNING, logger=NETWORK_SOURCE_LOGGER):
            _maximal_map(run_ctx, output)
            _maximal_map(run_ctx, output)

        fired = [record for record in caplog.records if "geomorphological" in record.getMessage()]
        assert len(fired) == 1
