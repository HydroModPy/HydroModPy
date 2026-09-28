"""A network output scored against a minimal and a maximal map, in one state or two bounds.

The trial context is faked and everything it feeds is real: the V-valley mesh,
mapped networks read off disk and projected by the package, and a transient
release stack whose head of network moves up and down the valley over the
year. The components checked here are the contract a root search and the
figures read.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibrationConfig, validate_calib_output
from hydromodpy.calibration.criteria import criterion_for
from hydromodpy.calibration.metrics import solver_extract as _solver_extract
from hydromodpy.calibration.metrics.solver_extract import (
    extract_outputs,
    observable_request_for_output,
)
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.core.exceptions import ObjectiveError
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

CRS = "EPSG:2154"
MINIMAL_FIRST_ROW = 36
"""The permanent reaches start lower down the valley than the complete ones."""


@pytest.fixture(scope="module")
def bench():
    return build_bench()


def _axis_file(directory, name: str, first_row: int, *, extra_col: int | None = None):
    from shapely.geometry import LineString

    lines = [
        LineString(
            [
                ((AXIS_COL + 0.5) * CELL_SIZE, (row + 0.5) * CELL_SIZE)
                for row in range(first_row, N_ROWS)
            ]
        )
    ]
    if extra_col is not None:
        lines.append(
            LineString(
                [((extra_col + 0.5) * CELL_SIZE, (row + 0.5) * CELL_SIZE) for row in (50, 55)]
            )
        )
    path = directory / name
    gpd.GeoDataFrame(geometry=lines, crs=CRS).to_file(path, driver="GPKG")
    return path


@pytest.fixture(scope="module")
def maps(tmp_path_factory):
    directory = tmp_path_factory.mktemp("maps")
    return SimpleNamespace(
        maximal=_axis_file(directory, "complete.gpkg", FIRST_OBSERVED_ROW),
        minimal=_axis_file(directory, "permanent.gpkg", MINIMAL_FIRST_ROW),
        straying=_axis_file(directory, "straying.gpkg", MINIMAL_FIRST_ROW, extra_col=AXIS_COL - 6),
    )


def _monthly_bounds(first_year: int, n_years: int) -> list[pd.Timestamp]:
    return list(pd.date_range(f"{first_year}-01-01", periods=12 * n_years + 1, freq="MS"))


def _seasonal_thresholds(n_years: int) -> np.ndarray:
    month = np.arange(12)
    season = 0.5 * (1.0 + np.cos(2.0 * np.pi * (month - 1) / 12.0))
    year = np.exp(np.log(900.0) + season * (np.log(8.0) - np.log(900.0)))
    return np.tile(year, n_years)


def _stack(bench, thresholds) -> np.ndarray:
    return np.vstack(
        [np.where(simulated_network(bench, float(value)), 1.0e-6, 0.0) for value in thresholds]
    )


def _fake_ctx(bench, bounds):
    vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
    planar_mesh = SimpleNamespace(
        vertices=vertices, flat_connectivity=connectivity, n_cells=N_CELLS
    )
    rows, cols = np.divmod(np.arange(N_CELLS), N_COLS)
    centroids = np.column_stack([(cols + 0.5) * CELL_SIZE, (rows + 0.5) * CELL_SIZE])
    solver_mesh = SimpleNamespace(
        top=bench.elevation,
        botm=np.zeros((1, N_CELLS)),
        inactive_mask=np.zeros((1, N_CELLS), dtype=bool),
        planar_mesh=planar_mesh,
        n_cells=N_CELLS,
        cell_areas=lambda: np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
        cell_centroids=lambda: centroids,
    )
    return SimpleNamespace(
        run=SimpleNamespace(id="r1", solver="modflow6"),
        state=SimpleNamespace(setup=SimpleNamespace(geographic=SimpleNamespace(crs_project=CRS))),
        setup=SimpleNamespace(time_grid=SimpleNamespace(boundaries=bounds)),
        model=SimpleNamespace(solver_mesh=solver_mesh, recharge=1.0e-8),
    )


class _StackAdapter:
    """Serves a release stack, whole or at its last row, as the request asks."""

    def __init__(self, stack: np.ndarray) -> None:
        self.stack = stack
        self.requests: list = []

    def extract_observables(self, ctx, store, requests, *, time_index=None):
        del ctx, store
        self.requests.extend(requests)
        served = {}
        for request in requests:
            values = self.stack if request.times == "all" else self.stack[-1]
            times = time_index if request.times == "all" else None
            served[request.id] = ObservableResult(
                request_id=request.id, values=values, units="m3 s-1", times=times
            )
        return served


def _output(maps, **fields):
    return validate_calib_output(
        {
            "support": "network",
            "stream_geometry_path": str(maps.maximal),
            "diagonal_neighbors": True,
            "tau_specific_ratio": 0.0,
            **fields,
        }
    )


def _extract(monkeypatch, bench, output, stack, bounds):
    adapter = _StackAdapter(stack)
    ctx = _fake_ctx(bench, bounds)
    monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, ctx))
    extracted = extract_outputs(ctx, {"net": output})
    return extracted.values["net"], extracted.diagnostics, adapter


class TestTheSchema:
    def test_the_extent_table_takes_its_defaults(self, maps) -> None:
        extent = _output(maps, extent={}).extent
        assert (extent.maximal_flowing_steps, extent.minimal_dry_steps) == (1, 1)
        assert extent.year_quorum == 0.5
        assert extent.visible_flow == "1 L/s"
        assert (extent.weights.minimal, extent.weights.maximal) == (0.5, 0.5)

    def test_without_it_the_output_reads_one_state(self, maps) -> None:
        output = _output(maps)
        assert output.extent is None
        assert observable_request_for_output("net", output, None).times == "last"

    def test_with_it_every_timestep_is_requested(self, maps) -> None:
        output = _output(maps, extent={})
        assert observable_request_for_output("net", output, None).times == "all"

    def test_a_single_state_named_beside_it_is_refused(self, maps) -> None:
        with pytest.raises(ValidationError, match="drop 'time'"):
            _output(maps, extent={}, time="first")

    def test_weights_without_a_minimal_map_are_refused(self, maps) -> None:
        with pytest.raises(ValidationError, match="only the maximal bound"):
            _output(maps, extent={"weights": {"minimal": 1.0, "maximal": 0.0}})

    def test_weights_must_sum_to_one(self, maps) -> None:
        with pytest.raises(ValidationError, match="sum to one"):
            _output(
                maps,
                minimal_stream_geometry_path=str(maps.minimal),
                extent={"weights": {"minimal": 0.5, "maximal": 0.7}},
            )

    def test_an_unreadable_visible_flow_is_refused_at_load(self, maps) -> None:
        with pytest.raises(ValidationError, match="no unit"):
            _output(maps, extent={"visible_flow": "2"})

    @pytest.mark.parametrize(
        "extent",
        [{"maximal_flowing_steps": 0}, {"minimal_dry_steps": -1}, {"year_quorum": 0.0}],
    )
    def test_rules_out_of_range_are_refused_at_load(self, maps, extent) -> None:
        with pytest.raises(ValidationError):
            _output(maps, extent=extent)

    def test_two_sources_for_the_minimal_map_are_refused(self, maps) -> None:
        with pytest.raises(ValidationError, match="at most one"):
            _output(
                maps,
                minimal_stream_geometry_path=str(maps.minimal),
                minimal_observed_network="data.hydrography",
            )

    def test_a_config_round_trips_through_its_dump(self, maps) -> None:
        output = _output(
            maps,
            minimal_stream_geometry_path=str(maps.minimal),
            extent={"visible_flow": "1%", "weights": {"minimal": 1.0, "maximal": 0.0}},
        )
        cfg = CalibrationConfig.model_validate(
            {
                "method": "grid",
                "outputs": {"net": output.model_dump()},
                "objective_blocks": [
                    {"name": "network", "metric": "distance_gap", "uses_outputs": ["net"]}
                ],
            }
        )
        assert cfg.outputs["net"].extent.weights.minimal == 1.0


class TestOneState:
    def test_one_map_publishes_the_bound_under_both_names(self, monkeypatch, bench, maps) -> None:
        stack = _stack(bench, [200.0])
        pair, diagnostics, _ = _extract(monkeypatch, bench, _output(maps), stack, None)
        assert len(pair) == 2
        assert diagnostics["net.n_bounds_scored"] == 1.0
        assert diagnostics["net.J_signed"] == diagnostics["net.J_signed_maximal"]
        assert "net.J_signed_minimal" not in diagnostics
        assert "net.frac_minimal_outside_maximal" not in diagnostics

    def test_with_both_maps_the_state_is_scored_on_the_permanent_one(
        self, monkeypatch, bench, maps
    ) -> None:
        stack = _stack(bench, [200.0])
        output = _output(maps, minimal_stream_geometry_path=str(maps.minimal))
        pair, diagnostics, _ = _extract(monkeypatch, bench, output, stack, None)
        _, alone, _ = _extract(
            monkeypatch,
            bench,
            _output(maps, stream_geometry_path=str(maps.minimal)),
            stack,
            None,
        )

        assert diagnostics["net.J_signed"] == pytest.approx(alone["net.J_signed"])
        assert diagnostics["net.J_signed_minimal"] == diagnostics["net.J_signed"]
        assert pair[0] - pair[1] == pytest.approx(diagnostics["net.J_signed"])
        # The complete map is scored beside the cost, under a name no search reads.
        assert "net.J_signed_maximal" not in diagnostics
        assert "net.J_signed_maximal_validation" in diagnostics
        assert diagnostics["net.J_signed_maximal_validation"] != diagnostics["net.J_signed"]
        assert diagnostics["net.frac_minimal_outside_maximal"] == 0.0

    def test_a_minimal_map_outside_the_maximal_one_is_scored_on_their_union(
        self, monkeypatch, bench, maps
    ) -> None:
        stack = _stack(bench, [200.0])
        output = _output(maps, minimal_stream_geometry_path=str(maps.straying))
        _, diagnostics, _ = _extract(monkeypatch, bench, output, stack, None)
        _, alone, _ = _extract(monkeypatch, bench, _output(maps), stack, None)

        assert diagnostics["net.frac_minimal_outside_maximal"] > 0.0
        assert diagnostics["net.n_network_obs_maximal_validation"] > alone["net.n_network_obs"]
        # The cells counted beside the maximal bound are the union it was scored on.
        added = diagnostics["net.n_network_obs_maximal_validation"] - alone["net.n_network_obs"]
        assert (
            diagnostics["net.n_observed_cells_maximal_validation"]
            == alone["net.n_observed_cells"] + added
        )


class TestTwoBounds:
    BOUNDS = _monthly_bounds(2001, 3)

    def _run(self, monkeypatch, bench, output, *, thresholds=None):
        thresholds = _seasonal_thresholds(3) if thresholds is None else thresholds
        return _extract(monkeypatch, bench, output, _stack(bench, thresholds), self.BOUNDS)

    def test_the_maximal_map_alone_is_one_bound_under_the_usual_names(
        self, monkeypatch, bench, maps
    ) -> None:
        output = _output(maps, extent={"visible_flow": "0 L/s"})
        pair, diagnostics, adapter = self._run(monkeypatch, bench, output)

        assert [request.times for request in adapter.requests][0] == "all"
        assert len(pair) == 2
        assert diagnostics["net.n_bounds_scored"] == 1.0
        assert diagnostics["net.J_signed"] == diagnostics["net.J_signed_maximal"]
        assert pair[0] - pair[1] == pytest.approx(diagnostics["net.J_signed"])
        assert "net.J_signed_minimal" not in diagnostics
        assert diagnostics["net.n_years_scored"] == 3.0
        assert diagnostics["net.n_years_required"] == 2.0
        for year in (2001, 2002, 2003):
            assert f"net.J_signed_maximal_y{year}" in diagnostics

    def test_two_maps_are_two_bounds_and_no_single_residual(self, monkeypatch, bench, maps) -> None:
        output = _output(
            maps,
            minimal_stream_geometry_path=str(maps.minimal),
            extent={"visible_flow": "0 L/s", "weights": {"minimal": 0.25, "maximal": 0.75}},
        )
        pair, diagnostics, _ = self._run(monkeypatch, bench, output)

        assert diagnostics["net.n_bounds_scored"] == 2.0
        # A single-root search must not silently close on one of the two.
        assert "net.J_signed" not in diagnostics
        assert "net.roptim" not in diagnostics
        for key in ("J_signed", "J", "D_so", "D_os", "Doptim", "roptim"):
            assert f"net.{key}_minimal" in diagnostics
            assert f"net.{key}_maximal" in diagnostics
        assert diagnostics["net.J_minimal"] == pytest.approx(
            abs(diagnostics["net.J_signed_minimal"])
        )
        assert (diagnostics["net.weight_minimal"], diagnostics["net.weight_maximal"]) == (
            0.25,
            0.75,
        )
        assert len(pair) == 4
        assert pair[0] - pair[1] == pytest.approx(0.25 * diagnostics["net.J_signed_minimal"])
        assert pair[2] - pair[3] == pytest.approx(0.75 * diagnostics["net.J_signed_maximal"])
        # The permanent mask is the smaller one, year by year.
        for year in (2001, 2002, 2003):
            assert (
                diagnostics[f"net.n_network_sim_minimal_y{year}"]
                <= diagnostics[f"net.n_network_sim_maximal_y{year}"]
            )
        assert diagnostics["net.n_network_sim_minimal"] < diagnostics["net.n_network_sim_maximal"]

    def test_a_minimiser_scores_the_weighted_sum_of_the_two_gaps(
        self, monkeypatch, bench, maps
    ) -> None:
        output = _output(
            maps,
            minimal_stream_geometry_path=str(maps.minimal),
            extent={"visible_flow": "0 L/s", "weights": {"minimal": 0.25, "maximal": 0.75}},
        )
        pair, diagnostics, _ = self._run(monkeypatch, bench, output)
        scored = criterion_for("distance_gap").score(pair)
        expected = 0.25 * diagnostics["net.J_minimal"] + 0.75 * diagnostics["net.J_maximal"]
        assert scored.cost == pytest.approx(expected)
        assert scored.signed_residual is None

    def test_a_constant_run_scores_what_one_state_scores(self, monkeypatch, bench, maps) -> None:
        # Every cell flows all year or never: both masks are the state itself.
        constant = np.full(36, 200.0)
        output = _output(
            maps,
            minimal_stream_geometry_path=str(maps.maximal),
            extent={"visible_flow": "0 L/s"},
        )
        _, diagnostics, _ = self._run(monkeypatch, bench, output, thresholds=constant)
        _, state, _ = _extract(monkeypatch, bench, _output(maps), _stack(bench, [200.0]), None)

        assert diagnostics["net.J_signed_minimal"] == pytest.approx(state["net.J_signed"])
        assert diagnostics["net.J_signed_maximal"] == pytest.approx(state["net.J_signed"])

    def test_a_visible_flow_shrinks_both_masks(self, monkeypatch, bench, maps) -> None:
        fields = {"minimal_stream_geometry_path": str(maps.minimal)}
        _, geometric, _ = self._run(
            monkeypatch, bench, _output(maps, **fields, extent={"visible_flow": "0 L/s"})
        )
        _, visible, _ = self._run(
            monkeypatch, bench, _output(maps, **fields, extent={"visible_flow": "0.02 L/s"})
        )
        for bound in ("minimal", "maximal"):
            assert visible[f"net.n_network_sim_{bound}"] < geometric[f"net.n_network_sim_{bound}"]
        assert visible["net.visible_flow_m3_s"] == pytest.approx(2.0e-5)

    def test_a_steady_run_is_refused(self, monkeypatch, bench, maps) -> None:
        output = _output(maps, extent={})
        with pytest.raises(ObjectiveError, match="single period"):
            _extract(monkeypatch, bench, output, _stack(bench, [200.0]), None)

    def test_a_run_with_no_complete_year_is_refused(self, monkeypatch, bench, maps) -> None:
        bounds = list(pd.date_range("2001-03-01", periods=7, freq="MS"))
        output = _output(maps, extent={})
        with pytest.raises(ObjectiveError, match="no complete"):
            _extract(monkeypatch, bench, output, _stack(bench, np.full(6, 50.0)), bounds)

    def test_a_rule_longer_than_the_year_is_refused(self, monkeypatch, bench, maps) -> None:
        output = _output(maps, extent={"maximal_flowing_steps": 30})
        with pytest.raises(ObjectiveError, match="maximal_flowing_steps = 30"):
            self._run(monkeypatch, bench, output)

    def test_an_undated_stack_is_refused(self, monkeypatch, bench, maps) -> None:
        output = _output(maps, extent={})
        with pytest.raises(ObjectiveError, match="carry no date"):
            _extract(monkeypatch, bench, output, _stack(bench, np.full(24, 50.0)), None)


class TestTheMinimalMapFromTheDataLayer:
    def _ctx(self, bench, permanent):
        ctx = _fake_ctx(bench, None)
        networks = SimpleNamespace(reference_permanent=permanent)
        ctx.state.setup.geographic_features = SimpleNamespace(hydrographic_networks=networks)
        return ctx

    def test_the_permanent_reaches_the_loader_wrote_are_the_minimal_map(
        self, monkeypatch, bench, maps
    ) -> None:
        permanent = SimpleNamespace(
            vector_path=str(maps.minimal),
            crs=CRS,
            read_vector=lambda: gpd.read_file(maps.minimal),
        )
        ctx = self._ctx(bench, permanent)
        adapter = _StackAdapter(_stack(bench, [200.0]))
        monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, ctx))
        output = _output(maps, minimal_observed_network="data.hydrography")
        from_layer = extract_outputs(ctx, {"net": output}).diagnostics
        _, from_file, _ = _extract(
            monkeypatch,
            bench,
            _output(maps, minimal_stream_geometry_path=str(maps.minimal)),
            _stack(bench, [200.0]),
            None,
        )
        assert from_layer["net.J_signed"] == pytest.approx(from_file["net.J_signed"])
        assert from_layer["net.observed_network_clipped_minimal"] == 1.0

    def test_a_project_without_them_is_refused_by_name(self, monkeypatch, bench, maps) -> None:
        from hydromodpy.calibration.observations.network_source import (
            UnresolvedObservedNetwork,
        )

        ctx = self._ctx(bench, None)
        adapter = _StackAdapter(_stack(bench, [200.0]))
        monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, ctx))
        output = _output(maps, minimal_observed_network="data.hydrography")
        with pytest.raises(UnresolvedObservedNetwork, match="minimal_stream_geometry_path"):
            extract_outputs(ctx, {"net": output})


def test_the_union_projection_counts_the_cells_and_reaches_of_both_maps() -> None:
    from hydromodpy.calibration.observations.network_geometry import union_projection
    from hydromodpy.calibration.observations.observed_network import ObservedNetworkMask

    maximal = ObservedNetworkMask(
        mask=np.array([True, True, False, False]),
        rasterization="crossing",
        n_fallback_parts=1,
        n_outside_parts=0,
    )
    minimal = ObservedNetworkMask(
        mask=np.array([False, True, False, True]),
        rasterization="crossing",
        n_fallback_parts=2,
        n_outside_parts=1,
    )
    union = union_projection(maximal, minimal)

    assert union.mask.tolist() == [True, True, False, True]
    assert union.rasterization == "crossing"
    assert union.n_fallback_parts == 3
    assert union.n_outside_parts == 1
