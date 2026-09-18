"""The network criterion scores the geometry it was handed, never a path.

Three routes feed the same mask projection: the network the data layer already
loaded (clipped, not DEM-derived), the network the DEM pipeline derived
(clipped, DEM-derived), and an explicit file (neither). This file checks the
wiring rather than the resolution logic itself, which
``test_an_observed_network_reaches_what_the_project_declares.py`` already
covers: that ``observed_network_mask`` reads an already-resolved
``ObservedNetwork`` and never a path, that ``geometry_from_run`` resolves once
per trial and threads the same resolution into the mask and into the trial
diagnostics, and that the DEM-derived warning fires for that one route alone.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.config import validate_calib_output
from hydromodpy.calibration.metrics import solver_extract as _solver_extract
from hydromodpy.calibration.metrics.solver_extract import extract_outputs
from hydromodpy.calibration.observations import network_source
from hydromodpy.calibration.observations.network_geometry import geometry_from_run
from hydromodpy.calibration.observations.network_source import (
    ObservedNetwork,
    resolve_observed_network,
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

gpd = pytest.importorskip("geopandas")
shapely = pytest.importorskip("shapely")

from shapely.geometry import LineString  # noqa: E402

CRS = "EPSG:2154"
NETWORK_SOURCE_LOGGER = network_source.__name__


def _valley_axis_line() -> LineString:
    """The talweg of the V-valley bench, as the mapped network would trace it."""
    return LineString(
        [
            ((AXIS_COL + 0.5) * CELL_SIZE, (row + 0.5) * CELL_SIZE)
            for row in range(FIRST_OBSERVED_ROW, N_ROWS)
        ]
    )


def _lines_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=[_valley_axis_line()], crs=CRS)


def _fake_hydrographic_network(gdf, *, path: str = "/fake/network.gpkg", crs: str = CRS):
    """A `HydrographicNetwork` stand-in: hands back an in-memory GeoDataFrame."""
    return SimpleNamespace(vector_path=path, crs=crs, read_vector=lambda: gdf)


@pytest.fixture(scope="module")
def bench():
    return build_bench()


def _fake_run_ctx(bench, *, reference=None, generated=None):
    """A trial context exposing exactly what geometry_from_run reads."""
    vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
    planar_mesh = SimpleNamespace(
        vertices=vertices, flat_connectivity=connectivity, n_cells=N_CELLS
    )
    rows, cols = np.divmod(np.arange(N_CELLS), N_COLS)
    centroids = np.column_stack([(cols + 0.5) * CELL_SIZE, (rows + 0.5) * CELL_SIZE])
    solver_mesh = SimpleNamespace(
        top=bench.elevation,
        planar_mesh=planar_mesh,
        n_cells=N_CELLS,
        cell_areas=lambda: np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
        cell_centroids=lambda: centroids,
    )
    model = SimpleNamespace(solver_mesh=solver_mesh, recharge=1.0e-8, lake_cell_ids_by_lake={})
    return SimpleNamespace(
        run=SimpleNamespace(id="r1", solver="modflow6"),
        state=SimpleNamespace(
            setup=SimpleNamespace(
                geographic=SimpleNamespace(crs_project=CRS),
                geographic_features=SimpleNamespace(
                    hydrographic_networks=SimpleNamespace(reference=reference, generated=generated)
                ),
            ),
        ),
        model=model,
    )


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
            geometry=_lines_gdf(),
            crs=CRS,
            clipped=True,
            dem_derived=False,
            path="/does/not/exist/on/this/machine.gpkg",
        )
        vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
        run_ctx = _fake_run_ctx(bench)
        planar_mesh = SimpleNamespace(vertices=vertices)

        mask = observed_network_mask(run_ctx, resolved, planar_mesh, connectivity)

        assert mask.dtype == bool
        assert mask.sum() > 0

    def test_an_empty_resolved_geometry_is_refused(self, bench) -> None:
        resolved = ObservedNetwork(
            source="path",
            geometry=_lines_gdf().iloc[:0],
            crs=CRS,
            clipped=False,
            dem_derived=False,
            path="whatever.gpkg",
        )
        vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
        run_ctx = _fake_run_ctx(bench)
        planar_mesh = SimpleNamespace(vertices=vertices)

        with pytest.raises(ValueError, match="holds no feature"):
            observed_network_mask(run_ctx, resolved, planar_mesh, connectivity)

    def test_a_resolved_geometry_with_no_crs_is_refused(self, bench) -> None:
        gdf = gpd.GeoDataFrame(geometry=[_valley_axis_line()])
        resolved = ObservedNetwork(
            source="path",
            geometry=gdf,
            crs=None,
            clipped=False,
            dem_derived=False,
            path="whatever.gpkg",
        )
        vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
        run_ctx = _fake_run_ctx(bench)
        planar_mesh = SimpleNamespace(vertices=vertices)

        with pytest.raises(ValueError, match="declares no CRS"):
            observed_network_mask(run_ctx, resolved, planar_mesh, connectivity)


class TestGeometryFromRunResolvesOncePerTrial:
    def test_data_hydrography_resolves_once_and_is_clipped_not_dem_derived(
        self, bench, monkeypatch
    ) -> None:
        network = _fake_hydrographic_network(_lines_gdf(), path="/data/streams.shp")
        run_ctx = _fake_run_ctx(bench, reference=network)
        output = _network_output(observed_network="data.hydrography")

        calls: list[None] = []

        def spy(ctx: object, out: object) -> ObservedNetwork:
            calls.append(None)
            return resolve_observed_network(ctx, out)

        monkeypatch.setattr(network_source, "resolve_observed_network", spy)

        geometry, resolved = geometry_from_run(run_ctx, output)

        assert len(calls) == 1
        assert resolved.source == "data.hydrography"
        assert resolved.clipped is True
        assert resolved.dem_derived is False
        assert resolved.path == "/data/streams.shp"
        assert geometry.observed.sum() > 0

    def test_geographic_river_network_resolves_once_and_is_dem_derived(self, bench) -> None:
        network = _fake_hydrographic_network(_lines_gdf(), path="/geo/river_network.shp")
        run_ctx = _fake_run_ctx(bench, generated=network)
        output = _network_output(observed_network="geographic.river_network")

        _geometry, resolved = geometry_from_run(run_ctx, output)

        assert resolved.source == "geographic.river_network"
        assert resolved.clipped is True
        assert resolved.dem_derived is True

    def test_the_explicit_path_is_neither_clipped_nor_dem_derived(self, bench, tmp_path) -> None:
        path = tmp_path / "streams.gpkg"
        _lines_gdf().to_file(path, driver="GPKG")
        run_ctx = _fake_run_ctx(bench)
        output = _network_output(stream_geometry_path=str(path))

        _geometry, resolved = geometry_from_run(run_ctx, output)

        assert resolved.source == "path"
        assert resolved.clipped is False
        assert resolved.dem_derived is False


class _ReleaseAdapter:
    """Returns the bench pattern as a per-cell release flux, for extract_outputs."""

    def __init__(self, threshold: float) -> None:
        self.threshold = threshold

    def extract_observables(self, ctx, store, requests, *, time_index=None):
        del ctx, store, time_index
        pattern = simulated_network(build_bench(), self.threshold)
        return {
            request.id: ObservableResult(
                request_id=request.id,
                values=np.where(pattern, 1.0e-6, 0.0),
                units="m3 s-1",
            )
            for request in requests
        }


def _extract_diagnostics(monkeypatch, run_ctx, output) -> dict[str, float]:
    adapter = _ReleaseAdapter(200.0)
    monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda ctx: (adapter, run_ctx))
    extracted = extract_outputs(run_ctx, {"net": output})
    return extracted.diagnostics


class TestTheTwoFlagsReachTheTrialDiagnostics:
    def test_data_hydrography_reports_clipped_and_not_dem_derived(self, bench, monkeypatch) -> None:
        network = _fake_hydrographic_network(_lines_gdf())
        run_ctx = _fake_run_ctx(bench, reference=network)
        output = _network_output(observed_network="data.hydrography")

        diagnostics = _extract_diagnostics(monkeypatch, run_ctx, output)

        assert diagnostics["net.observed_network_clipped"] == 1.0
        assert diagnostics["net.observed_network_is_dem_derived"] == 0.0
        # Travels beside alpha_obs_closure, in the same trial record.
        assert "net.alpha_obs_closure" in diagnostics

    def test_geographic_river_network_reports_both_flags_set(self, bench, monkeypatch) -> None:
        network = _fake_hydrographic_network(_lines_gdf())
        run_ctx = _fake_run_ctx(bench, generated=network)
        output = _network_output(observed_network="geographic.river_network")

        diagnostics = _extract_diagnostics(monkeypatch, run_ctx, output)

        assert diagnostics["net.observed_network_clipped"] == 1.0
        assert diagnostics["net.observed_network_is_dem_derived"] == 1.0

    def test_the_explicit_path_reports_neither_flag_set(self, bench, monkeypatch, tmp_path) -> None:
        path = tmp_path / "streams.gpkg"
        _lines_gdf().to_file(path, driver="GPKG")
        run_ctx = _fake_run_ctx(bench)
        output = _network_output(stream_geometry_path=str(path))

        diagnostics = _extract_diagnostics(monkeypatch, run_ctx, output)

        assert diagnostics["net.observed_network_clipped"] == 0.0
        assert diagnostics["net.observed_network_is_dem_derived"] == 0.0


class TestTheDemDerivedWarningFiresOnceAndOnlyThere:
    @pytest.fixture(autouse=True)
    def _reset_warned_flag(self, monkeypatch):
        # `_warn_dem_derived_once` is gated by a module-level flag, shared with
        # every other test in the process: reset it so this class's own
        # assertions do not depend on run order.
        monkeypatch.setattr(network_source, "_DEM_DERIVED_WARNED", False)

    def test_geographic_river_network_warns_naming_the_reduction(self, bench, caplog) -> None:
        network = _fake_hydrographic_network(_lines_gdf())
        run_ctx = _fake_run_ctx(bench, generated=network)
        output = _network_output(observed_network="geographic.river_network")

        with caplog.at_level(logging.WARNING, logger=NETWORK_SOURCE_LOGGER):
            geometry_from_run(run_ctx, output)

        messages = [record.getMessage() for record in caplog.records]
        assert any("geomorphological" in message for message in messages)

    def test_data_hydrography_does_not_warn(self, bench, caplog) -> None:
        network = _fake_hydrographic_network(_lines_gdf())
        run_ctx = _fake_run_ctx(bench, reference=network)
        output = _network_output(observed_network="data.hydrography")

        with caplog.at_level(logging.WARNING, logger=NETWORK_SOURCE_LOGGER):
            geometry_from_run(run_ctx, output)

        assert not any("geomorphological" in record.getMessage() for record in caplog.records)

    def test_the_explicit_path_does_not_warn(self, bench, caplog, tmp_path) -> None:
        path = tmp_path / "streams.gpkg"
        _lines_gdf().to_file(path, driver="GPKG")
        run_ctx = _fake_run_ctx(bench)
        output = _network_output(stream_geometry_path=str(path))

        with caplog.at_level(logging.WARNING, logger=NETWORK_SOURCE_LOGGER):
            geometry_from_run(run_ctx, output)

        assert not any("geomorphological" in record.getMessage() for record in caplog.records)

    def test_it_fires_only_once_across_two_trials(self, bench, caplog) -> None:
        network = _fake_hydrographic_network(_lines_gdf())
        run_ctx = _fake_run_ctx(bench, generated=network)
        output = _network_output(observed_network="geographic.river_network")

        with caplog.at_level(logging.WARNING, logger=NETWORK_SOURCE_LOGGER):
            geometry_from_run(run_ctx, output)
            geometry_from_run(run_ctx, output)

        fired = [record for record in caplog.records if "geomorphological" in record.getMessage()]
        assert len(fired) == 1
