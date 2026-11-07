"""Tests of stream redraw."""

from __future__ import annotations

import dataclasses
import datetime
import logging
import uuid
from dataclasses import replace
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, box

from hydromodpy.calibration.protocols import expand_calibration_protocol
from hydromodpy.calibration.protocols.matching_hydrographic_network import (
    STEADY_STAGE,
    TRANSIENT_STAGE,
)
from hydromodpy.core.scoring.stream_defaults import STREAM_CRITERION_DEFAULTS
from hydromodpy.core.time.selection import resolve_state
from hydromodpy.core.units import factor_to_m_per_s
from hydromodpy.display.figures._stream_comparison import compared_timestep, dated_title
from hydromodpy.model.forcing.recharge_rates import (
    CRITERION_MEAN_RECHARGE_ATTR,
    criterion_mean_recharge,
    forcing_period_rates,
    mean_recharge_m_s,
)
from hydromodpy.results.derive.stream import geometry as stream_geometry
from hydromodpy.results.derive.stream import run_extent
from hydromodpy.results.derive.stream.comparison import (
    _delineated_catchment,
    _watershed_catchment,
    has_recharge_source,
    network_comparison_from_run,
    unavailable_reason_for_comparison,
)
from hydromodpy.results.derive.stream.criterion_settings import (
    DEFAULT_CRITERION_SETTINGS,
    DEFAULT_EXTENT_RULES,
    NetworkExtentRules,
    network_criterion_settings,
    network_outputs_of_run,
)
from hydromodpy.results.derive.stream.extent import DEFAULT_VISIBLE_FLOW, parse_visible_flow
from hydromodpy.results.derive.stream.geometry import build_network_geometry
from hydromodpy.results.derive.stream.heads_view import network_heads_view_from_run
from hydromodpy.results.derive.stream.run_extent import (
    block_flow_counts,
    flow_geometry_from_run,
    graph_role,
    network_extents_from_run,
    run_step_edges,
    scored_cells,
    unavailable_reason_for_extents,
    unavailable_reason_for_flow,
)
from hydromodpy.results.derive.virtual_fields import (
    SIMULATED_ACTIVE_NETWORK,
    field_descriptor,
    simulated_active_network_stack,
)
from hydromodpy.results.run.descent import RunDescent
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.spatial.geographic.core import network_heads
from tests._helpers.sealed_runs import sealed_search
from tests._helpers.transient_network_run import (
    HEAD,
    HILLSLOPE,
    MIDDLE,
    N_STEPS,
    OUTLET,
    transient_run,
)
from tests.unit.display._network_comparison_run import (
    AXIS_COLUMN,
    CELL_M,
    CELL_RECHARGE_M3_S,
    NX,
    NY,
    cell,
    column_cells,
    comparison_run,
    stored_descent,
)

# ``[calibration.outputs.<n>] time`` is ``"last"``, ``"first"`` or one date.
# The trials read a date as the period ``[s, e)`` that holds it. The results
# layer read only the two words and refused the date, so a promoted run whose
# output named ``"2002-10-15"`` could not render its figures and the promotion
# failed. The settings now resolve the date on the run's own periods, by the one
# rule of :func:`hydromodpy.core.time.selection.resolve_state`.
# 36 monthly periods, 2000-01 to 2002-12. October 2002 is period 33.
MONTHS = pd.date_range("2000-01-01", "2003-01-01", freq="MS")


OCTOBER_2002 = 33


def _run(time, *, edges=MONTHS, stamps=None, n_timesteps=None) -> SimpleNamespace:
    """A run-shaped object with one network output sealed at ``time``."""
    search = {
        "outputs": {
            "seepage_network": {
                "support": "network",
                "observed_network": "data.hydrography",
                "time": time,
            }
        }
    }
    run = SimpleNamespace(sim_id="sim-x", dir=sealed_search(search))
    if edges is not None:
        run.periods = SimpleNamespace(edges=pd.DatetimeIndex(edges))
    if stamps is not None:
        run.time_index = pd.DatetimeIndex(stamps)
    if n_timesteps is not None:
        run.n_timesteps = n_timesteps
    return run


@pytest.mark.parametrize("time", ["2002-10-15", "2002-11-01", datetime.date(2002, 10, 31)])
def test_a_date_reads_the_period_that_holds_it(time) -> None:
    settings = network_criterion_settings(_run(time))

    assert settings.timestep == OCTOBER_2002


def test_the_stamp_of_a_period_reads_the_state_it_closes() -> None:
    assert network_criterion_settings(_run("2002-10-01")).timestep == OCTOBER_2002 - 1


def test_the_redraw_reads_the_state_the_trials_scored() -> None:
    for time in ("2000-01-01", "2001-06-30", "2002-10-15", "2003-01-01"):
        scored = resolve_state(time, MONTHS, n_periods=len(MONTHS) - 1)
        assert network_criterion_settings(_run(time)).timestep == scored


def test_the_words_keep_their_timestep() -> None:
    assert network_criterion_settings(_run("last")).timestep == -1
    assert network_criterion_settings(_run("first")).timestep == 0


def test_a_run_known_by_its_stamps_alone_reads_the_same_period() -> None:
    run = _run("2002-10-15", edges=None, stamps=MONTHS[1:])

    assert network_criterion_settings(run).timestep == OCTOBER_2002


def test_a_steady_run_over_its_window_reads_its_one_state() -> None:
    window = pd.DatetimeIndex(["2000-01-01", "2003-01-01"])

    assert network_criterion_settings(_run("2002-10-15", edges=window)).timestep == 0


def test_a_run_of_one_state_without_dates_serves_it() -> None:
    run = _run("2002-10-15", edges=None, n_timesteps=1)

    assert network_criterion_settings(run).timestep == 0


def test_a_date_the_run_does_not_hold_is_refused() -> None:
    with pytest.raises(ValueError, match="names no state of this run"):
        network_criterion_settings(_run("2004-01-15"))


@pytest.mark.parametrize("time", ["all", ["2001-10-15", "2002-10-15"], 3])
def test_what_no_trial_could_read_is_refused(time) -> None:
    with pytest.raises(ValueError, match="seepage_network"):
        network_criterion_settings(_run(time))


def test_the_stream_figures_draw_the_dated_period() -> None:
    run = _run("2002-10-15")

    assert compared_timestep(run) == OCTOBER_2002
    assert dated_title("Seepage network", run).endswith("October 2002")


# The by-hand Nancon calibration scores the network in a steady phase, then
# promotes a transient run whose first period is a steady spin-up. The trials
# read the rate the forcing gives each period (9.062e-9 m/s on average). The
# redraw read the budget the solver wrote, where the spin-up period holds the
# record mean in place of January (8.634e-9), so the figures cut the network at
# another threshold than the one scored, and the check logged "The mean recharge
# moved" though the forcing never changed. Both now average the forcing rates by
# one rule, each period by its length, the redraw rebuilding them from the station
# forcing the run stores.
# A real change of data or of window still warns.
MM_PER_DAY = factor_to_m_per_s("mm/day")


CELL_AREA_M2 = CELL_M * CELL_M


# Three monthly samples in mm/day, stamped at the end of their month as the
# Nancon file is, and the three monthly periods of the run.
FORCING_MM_D = pd.Series(
    [2.09, 0.76, 0.5], index=pd.DatetimeIndex(["2000-01-31", "2000-02-29", "2000-03-31"])
)


EDGES = pd.DatetimeIndex(["2000-01-01", "2000-02-01", "2000-03-01", "2000-04-01"])


RATES_M_S = FORCING_MM_D.to_numpy() * MM_PER_DAY


PERIOD_DAYS = np.array([31.0, 29.0, 31.0])


RECORD_MEAN_M_S = float(np.average(RATES_M_S, weights=PERIOD_DAYS))


@pytest.fixture(autouse=True)
def _fresh_process(monkeypatch):
    """Each test starts as a new process: no recharge seen."""
    monkeypatch.setattr(stream_geometry, "_last_mean_recharge", {})


def _moves(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "mean recharge moved" in r.getMessage()]


def _trial_build(model) -> None:
    """Build the criterion geometry as a trial does, from its built model."""
    run = comparison_run()
    observed = np.zeros(NX * NY, dtype=bool)
    observed[[cell(AXIS_COLUMN, row) for row in range(NY)]] = True
    build_network_geometry(
        topography=run.mesh.topography,
        face_node_connectivity=run.mesh.face_node_connectivity,
        vertices=run.mesh.vertices,
        observed=observed,
        cell_area_m2=np.full(NX * NY, CELL_AREA_M2),
        mean_recharge_m_s=mean_recharge_m_s(model),
        tau_specific_ratio=1e-4,
    )


def _promoted_run(tmp_path, *, forcing_mm_d=FORCING_MM_D, edges=EDGES, store=True):
    """A promoted transient run: a spin-up budget, and the forcing it stored."""
    budget = [RECORD_MEAN_M_S, *RATES_M_S[1:]]
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, row) for row in range(NY)])
    fields = {"release_flux": run.field("release_flux"), "topography": run.field("topography")}
    run.n_timesteps = len(budget)
    run.periods = SimpleNamespace(edges=edges)

    def field(variable, *, time=-1, **_):
        if variable == "recharge":
            return np.full(NX * NY, budget[time] * CELL_AREA_M2)
        return fields[variable]

    run.field = field
    if store:
        path = tmp_path / "fields.zarr"
        SimulationZarr.create(path, n_cells=0, n_layers=1).close()
        writer = SimulationZarr(path)
        writer.write_forcing_timeseries(
            "recharge",
            "NANCON",
            forcing_mm_d.index.values,
            forcing_mm_d.to_numpy(),
            unit="mm/day",
        )
        writer.close()
        run._catalog.open_zarr = lambda sim_id: SimulationZarr(path)
    return run


def test_a_period_takes_the_mean_of_its_samples_or_carries_the_last() -> None:
    samples = pd.Series(
        [1.0, 3.0, -2.0], index=pd.DatetimeIndex(["2000-01-05", "2000-01-20", "2000-03-10"])
    )
    edges = pd.DatetimeIndex(["2000-01-01", "2000-02-01", "2000-03-01", "2000-04-01"])

    assert forcing_period_rates(samples, edges).tolist() == [2.0, 3.0, 0.0]
    assert criterion_mean_recharge([np.array([1.0, np.nan]), 3.0]) == 2.0


def test_the_steady_and_transient_models_hold_the_record_mean() -> None:
    steady = SimpleNamespace(recharge=pd.Series([RECORD_MEAN_M_S]))
    transient = SimpleNamespace(
        recharge=pd.Series(RATES_M_S, index=EDGES[:-1]), perlen=PERIOD_DAYS * 86400.0
    )

    assert mean_recharge_m_s(steady) == pytest.approx(RECORD_MEAN_M_S, rel=1e-12)
    assert mean_recharge_m_s(transient) == pytest.approx(RECORD_MEAN_M_S, rel=1e-12)


def test_a_grid_weighs_its_cells_by_area_and_its_periods_by_length() -> None:
    fine_and_coarse = np.array([1.0, 100.0])
    mesh = SimpleNamespace(cell_areas=lambda: fine_and_coarse)
    model = SimpleNamespace(
        recharge={0: np.array([3.0, 1.0]), 1: np.array([5.0, 1.0])},
        solver_mesh=mesh,
        perlen=np.array([1.0, 3.0]),
    )

    own = [(3.0 + 100.0) / 101.0, (5.0 + 100.0) / 101.0]
    assert mean_recharge_m_s(model) == pytest.approx(np.average(own, weights=[1.0, 3.0]))


def test_a_series_as_long_as_the_mesh_stays_one_rate_per_period() -> None:
    mesh = SimpleNamespace(cell_areas=lambda: np.array([1.0, 100.0]))
    model = SimpleNamespace(
        recharge=pd.Series([3.0, 1.0]), solver_mesh=mesh, perlen=np.array([1.0, 3.0])
    )

    assert mean_recharge_m_s(model) == pytest.approx(1.5)


def test_the_run_gives_back_the_number_its_trials_read(tmp_path) -> None:
    run = _promoted_run(tmp_path)
    writer = SimulationZarr(tmp_path / "fields.zarr")
    writer.write_forcing_attrs({CRITERION_MEAN_RECHARGE_ATTR: 1.25e-8})
    writer.close()

    comparison = network_comparison_from_run(run)

    assert comparison.geometry.mean_recharge_m_s == pytest.approx(1.25e-8)


def test_the_redraw_reads_the_recharge_the_trials_scored(tmp_path, caplog) -> None:
    steady = SimpleNamespace(recharge=pd.Series([RECORD_MEAN_M_S]))

    with (
        caplog.at_level(logging.INFO, logger=stream_geometry.__name__),
        stream_geometry.recharge_session("session"),
    ):
        _trial_build(steady)
        comparison = network_comparison_from_run(_promoted_run(tmp_path))

    assert comparison.geometry.mean_recharge_m_s == pytest.approx(RECORD_MEAN_M_S, rel=1e-9)
    assert _moves(caplog) == []


def test_other_data_still_warns(tmp_path, caplog) -> None:
    steady = SimpleNamespace(recharge=pd.Series([RECORD_MEAN_M_S]))

    with (
        caplog.at_level(logging.INFO, logger=stream_geometry.__name__),
        stream_geometry.recharge_session("session"),
    ):
        _trial_build(steady)
        network_comparison_from_run(_promoted_run(tmp_path, forcing_mm_d=FORCING_MM_D * 0.8))

    assert len(_moves(caplog)) == 1


def test_another_window_still_warns(tmp_path, caplog) -> None:
    steady = SimpleNamespace(recharge=pd.Series([RECORD_MEAN_M_S]))

    with (
        caplog.at_level(logging.INFO, logger=stream_geometry.__name__),
        stream_geometry.recharge_session("session"),
    ):
        _trial_build(steady)
        network_comparison_from_run(_promoted_run(tmp_path, edges=EDGES[1:]))

    assert len(_moves(caplog)) == 1


def test_a_run_without_a_stored_forcing_reads_its_budget(tmp_path) -> None:
    comparison = network_comparison_from_run(_promoted_run(tmp_path, store=False))

    spin_up_budget = np.average([RECORD_MEAN_M_S, *RATES_M_S[1:]], weights=PERIOD_DAYS)
    assert comparison.geometry.mean_recharge_m_s == pytest.approx(spin_up_budget, rel=1e-9)


def _monthly_window(start: str, end: str):
    from hydromodpy.core.time import ResolvedSimulationTimeWindow

    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp(start),
        end=pd.Timestamp(end),
        step_value=1,
        step_unit="month",
        coverage_policy="error",
    )


@pytest.mark.parametrize(
    "samples",
    [
        # The example 04 file, monthly, stamped at each month's end.
        pd.Series(
            [2.088043, 0.760928, 0.551107, 0.642604, 0.0, 1.2],
            index=pd.to_datetime(
                ["2000-01-31", "2000-02-29", "2000-03-31", "2000-04-30", "2000-05-31", "2000-06-30"]
            ),
        ),
        # A daily series with a gap: April has no sample and carries March's last one.
        pd.Series(
            [1.0, 3.0, 2.0, 5.0, 4.0],
            index=pd.to_datetime(
                ["2000-01-10", "2000-01-20", "2000-02-15", "2000-03-31", "2000-05-02"]
            ),
        ),
    ],
)
def test_the_criterion_rates_are_the_rates_the_model_is_forced_with(samples: pd.Series) -> None:
    """Two copies of one rule: the solver forcing and the criterion must not drift apart."""
    from hydromodpy.core.time import build_simulation_time_boundaries
    from hydromodpy.model.forcing.time_alignment import align_forcing_series_to_simulation_window

    window = _monthly_window("2000-01-01", "2000-05-31")
    forced = align_forcing_series_to_simulation_window(samples, simulation_window=window)
    edges = build_simulation_time_boundaries(window)

    rates = forcing_period_rates(samples, edges)

    assert rates == pytest.approx(np.maximum(forced.to_numpy(dtype=float), 0.0))


# ``network_comparison_from_run`` sizes the seepage threshold from the mean
# recharge rate the solver's budget wrote. MODFLOW stores a budget component as
# ``(time, layer, cell)`` even when only one layer carries it (recharge applies
# to the top layer, the rest zero); reading it back and reshaping ``(time, -1)``
# without summing the layer axis doubles the row width instead of collapsing it,
# so the next array op against a ``(cell,)`` array of areas breaks. That is the
# ``(72930,) (36465,)`` broadcast a two-layer Flume run hit.
def test_recharge_split_over_two_layers_scores_the_same_threshold() -> None:
    single = comparison_run(seepage_cells=[7])
    layered = comparison_run(seepage_cells=[7])

    per_cell = np.full(NX * NY, CELL_RECHARGE_M3_S)
    two_layers = np.stack([per_cell, np.zeros_like(per_cell)])
    original_field = layered.field

    def field(variable, **kwargs):
        if variable == "recharge":
            return two_layers
        return original_field(variable, **kwargs)

    layered.field = field

    one_layer = network_comparison_from_run(single)
    two_layer = network_comparison_from_run(layered)

    assert two_layer.geometry.mean_recharge_m_s == pytest.approx(
        one_layer.geometry.mean_recharge_m_s, rel=1e-12
    )


# The run is the monthly V-valley of :mod:`tests._helpers.transient_network_run`:
# the outlet flows every month, the two upper axis cells five months of twelve,
# and the run covers 2001 and 2002 whole and 2003 up to March. Every count below
# is written from that description, not read back from the code under test.
def _cells(mask: np.ndarray) -> list[int]:
    return sorted(int(index) for index in np.flatnonzero(mask))


class TestTheTimeAxis:
    def test_the_first_bound_is_the_start_the_catalog_recorded(self) -> None:
        edges = run_step_edges(transient_run())

        assert edges.size == N_STEPS + 1
        assert edges[0] == np.datetime64("2001-01-01")
        assert edges[1] == np.datetime64("2001-01-31")

    def test_a_zoned_start_keeps_its_wall_clock(self) -> None:
        """Converted to UTC, a start west of Greenwich would cut the first year."""
        run = transient_run()
        run._load_row = lambda: {"period_start": pd.Timestamp("2001-01-01", tz="America/Cayenne")}

        edges = run_step_edges(run)

        assert edges[0] == np.datetime64("2001-01-01")
        assert network_extents_from_run(run).years.years == (2001, 2002)

    def test_without_a_recorded_start_the_first_period_is_as_long_as_the_second(self) -> None:
        edges = run_step_edges(transient_run(with_period_start=False))

        assert edges[1] - edges[0] == edges[2] - edges[1]

    def test_a_run_without_a_time_axis_has_no_bounds(self) -> None:
        assert run_step_edges(transient_run(with_time=False)) is None


class TestTheExtents:
    def test_the_complete_years_are_scored_and_the_cut_one_left_out(self) -> None:
        extents = network_extents_from_run(transient_run())

        assert extents.years.years == (2001, 2002)
        assert extents.years.incomplete == (2003,)
        assert extents.counts.n_steps.tolist() == [12, 12]

    def test_a_scoring_window_leaves_the_spin_up_year_out(self) -> None:
        extents = network_extents_from_run(
            transient_run(), window=(pd.Timestamp("2002-01-01"), None)
        )

        assert extents.years.years == (2002,)
        assert extents.years.outside_window == (2001,)
        assert extents.counts.n_steps.tolist() == [12]
        assert extents.masks.n_years_required == 1

    def test_a_window_holding_no_complete_year_is_refused_by_name(self) -> None:
        window = (pd.Timestamp("2001-03-01"), pd.Timestamp("2002-06-30"))

        reason = unavailable_reason_for_extents(transient_run(), window=window)

        assert reason is not None
        assert "leaves out 2001, 2002" in reason
        with pytest.raises(ValueError, match="scoring window holds no complete"):
            network_extents_from_run(transient_run(), window=window)

    def test_each_cell_flows_the_timesteps_its_releases_reach_it(self) -> None:
        counts = network_extents_from_run(transient_run()).counts.flowing

        assert counts[:, [OUTLET, MIDDLE, HEAD, HILLSLOPE]].tolist() == [[12, 5, 5, 0]] * 2

    def test_the_maximal_extent_holds_every_flowing_cell_the_minimal_the_perennial_one(
        self,
    ) -> None:
        extents = network_extents_from_run(transient_run())

        assert _cells(extents.simulated("maximal")) == [OUTLET, MIDDLE, HEAD]
        assert _cells(extents.simulated("minimal")) == [OUTLET]
        assert _cells(extents.simulated("minimal", year=2002)) == [OUTLET]

    def test_the_rules_are_counted_in_timesteps(self) -> None:
        """Five flowing months of twelve pass a maximal rule of five, not one of six."""
        five = network_extents_from_run(transient_run(), maximal_flowing_duration="5 months")
        six = network_extents_from_run(transient_run(), maximal_flowing_duration="6 months")

        assert _cells(five.simulated("maximal")) == [OUTLET, MIDDLE, HEAD]
        assert _cells(six.simulated("maximal")) == [OUTLET]

    def test_the_maximal_map_is_the_union_of_the_two_maps(self) -> None:
        extents = network_extents_from_run(transient_run())

        assert _cells(extents.observed("maximal")) == [OUTLET, MIDDLE, HEAD]
        assert _cells(extents.observed("minimal")) == [OUTLET, MIDDLE]
        assert extents.frac_minimal_outside_maximal == pytest.approx(0.0)

    def test_each_bound_is_partitioned_against_its_own_map(self) -> None:
        extents = network_extents_from_run(transient_run())

        assert extents.supports("minimal").counts == {
            "n_valid": 1.0,
            "n_excess": 0.0,
            "n_missing": 1.0,
        }
        assert extents.supports("maximal").counts == {
            "n_valid": 3.0,
            "n_excess": 0.0,
            "n_missing": 0.0,
        }

    def test_a_visible_flow_above_the_summer_release_dries_the_outlet_in_summer(self) -> None:
        """Two litres per second pass one litre per second, not five."""
        default = network_extents_from_run(transient_run())
        strict = network_extents_from_run(transient_run(), visible_flow="5 L/s")

        assert default.counts.flowing[0, OUTLET] == 12
        assert strict.counts.flowing[0, OUTLET] == 5
        assert _cells(strict.simulated("minimal")) == []

    def test_a_water_body_leaves_the_share_outside_as_it_leaves_the_counts(
        self, monkeypatch
    ) -> None:
        """A lake on the middle cell, which the maximal map misses.

        The minimal map holds the outlet and the middle cell. The lake takes
        the middle cell out of every scored quantity, so the one minimal cell
        left, the outlet, is covered by the maximal map.
        """
        build = run_extent.flow_geometry_from_run

        def with_lake(sim, *, role, **kwargs):
            geometry = build(sim, role=role, **kwargs)
            if role != run_extent.MAXIMAL_ROLE:
                return geometry
            lake = np.zeros_like(geometry.catchment, dtype=bool)
            lake[MIDDLE] = True
            observed = np.zeros_like(lake)
            observed[[OUTLET, HEAD]] = True
            return dataclasses.replace(geometry, observed=observed, excluded=lake)

        monkeypatch.setattr(run_extent, "flow_geometry_from_run", with_lake)
        extents = network_extents_from_run(transient_run())

        assert not scored_cells(extents.geometry)[MIDDLE]
        assert extents.frac_minimal_outside_maximal == pytest.approx(0.0)
        assert np.array_equal(extents.supports("minimal").keep, scored_cells(extents.geometry))
        assert extents.supports("minimal").counts["n_missing"] == 0.0

    def test_a_run_with_one_map_has_no_minimal_map(self) -> None:
        extents = network_extents_from_run(transient_run(with_minimal=False))

        assert extents.minimal_observed is None
        assert np.isnan(extents.frac_minimal_outside_maximal)
        with pytest.raises(ValueError, match="no minimal map"):
            extents.observed("minimal")

    def test_rules_the_years_cannot_hold_are_refused_by_name(self) -> None:
        with pytest.raises(ValueError, match="maximal rule of 13 timestep"):
            network_extents_from_run(transient_run(), maximal_flowing_duration="13 months")


class TestOneDefinitionOfFlowing:
    def test_the_counts_are_the_network_the_criterion_draws_at_each_step(self) -> None:
        """With no visible flow, flowing is the simulated network of the comparison."""
        run = transient_run()
        geometry = flow_geometry_from_run(run)
        for step in (0, 5):
            counts = block_flow_counts(
                run, geometry, [np.asarray([step])], visible_flow="0 L/s"
            ).flowing[0]
            comparison = network_comparison_from_run(run, timestep=step)
            network = comparison.simulated
            assert _cells(counts.astype(bool) & comparison.supports.keep) == _cells(network)

    def test_a_small_chunk_counts_the_same(self) -> None:
        run = transient_run()
        geometry = flow_geometry_from_run(run)
        blocks = [np.arange(12), np.arange(12, 24)]
        whole = block_flow_counts(run, geometry, blocks)
        chunked = block_flow_counts(run, geometry, blocks, chunk_elements=1)

        np.testing.assert_array_equal(whole.flowing, chunked.flowing)
        assert whole.visible_flow == parse_visible_flow("1 L/s")

    def test_the_seepage_threshold_of_the_criterion_applies(self) -> None:
        """A threshold of 0.1 m3/s silences the summer release and keeps the winter one."""
        run = transient_run()
        geometry = flow_geometry_from_run(run, tau_specific_ratio=1.0e3)
        counts = block_flow_counts(run, geometry, [np.arange(12)]).flowing[0]

        assert counts[OUTLET] == 5


class TestRefusals:
    def test_a_run_with_only_a_generated_network_still_counts(self) -> None:
        run = transient_run(roles=("generated",))

        assert graph_role(run) == "generated"
        assert unavailable_reason_for_flow(run) is None

    def test_a_run_with_no_network_is_told_why(self) -> None:
        reason = unavailable_reason_for_flow(transient_run(roles=()))

        assert reason is not None
        assert "'reference'" in reason

    def test_a_steady_run_has_no_extents(self) -> None:
        reason = unavailable_reason_for_extents(transient_run(n_steps=1))

        assert reason is not None
        assert "steady" in reason

    def test_a_run_with_one_map_is_told_it_lacks_the_minimal_one(self) -> None:
        reason = unavailable_reason_for_extents(transient_run(with_minimal=False))

        assert reason is not None
        assert "reference_permanent" in reason

    def test_a_run_shorter_than_a_calendar_year_is_told_so(self) -> None:
        reason = unavailable_reason_for_extents(transient_run(n_steps=6))

        assert reason is not None
        assert "no complete calendar year" in reason


# The criterion cuts the network at ``tau * R * A`` and reads the mean recharge R
# from the station forcing the run stores, and from the budget only when it stores
# none. The gate used to ask the budget alone, so a run forced by stations and
# holding no ``budget/recharge`` was refused for a term the computation never
# read. Both now ask one predicate, ``has_recharge_source``.
FORCING_MM_D_2 = pd.Series(
    [2.0, 1.0, 0.5], index=pd.DatetimeIndex(["2000-01-31", "2000-02-29", "2000-03-31"])
)


MEAN_M_S = float(np.average(FORCING_MM_D_2, weights=[31, 29, 31])) * factor_to_m_per_s("mm/day")


def _run_2(tmp_path, *, budget_recharge: bool, forcing: bool, dates: bool = True, policy=None):
    """A run with or without a recharge budget and with or without a station forcing.

    ``policy`` is what the ``budget/`` group of the store declares it kept,
    None for a group with no attributes.
    """
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, row) for row in range(NY)])
    fields = {name: run.field(name) for name in ("release_flux", "topography", "recharge")}
    if not budget_recharge:
        del fields["recharge"]
    run.has_field = lambda variable, **_: variable in fields
    run.field = lambda variable, **_: fields[variable]
    run.periods = SimpleNamespace(edges=EDGES if dates else None)
    run.time_index = None
    if not (forcing or policy is not None):
        # A stand-in whose catalog opens no store: the budget is read step by step.
        return run
    path = tmp_path / "fields.zarr"
    SimulationZarr.create(path, n_cells=0, n_layers=1).close()
    writer = SimulationZarr(path)
    if forcing:
        writer.write_forcing_timeseries(
            "recharge",
            "STATION",
            FORCING_MM_D_2.index.values,
            FORCING_MM_D_2.to_numpy(),
            unit="mm/day",
        )
    if policy is not None:
        budget = writer.root.require_group("budget")
        budget.attrs.update({"policy": policy[0], "kept_terms": list(policy[1])})
    writer.close()
    run._catalog.open_zarr = lambda sim_id: SimulationZarr(path)
    return run


def test_a_station_forced_run_without_a_recharge_budget_passes_the_gate(tmp_path) -> None:
    run = _run_2(tmp_path, budget_recharge=False, forcing=True)

    assert has_recharge_source(run)
    assert unavailable_reason_for_flow(run, tau_specific_ratio=1e-4) is None


def test_a_station_forced_run_without_a_recharge_budget_computes_the_criterion(tmp_path) -> None:
    run = _run_2(tmp_path, budget_recharge=False, forcing=True)

    comparison = network_comparison_from_run(run, tau_specific_ratio=1e-4)

    assert comparison.geometry.mean_recharge_m_s == pytest.approx(MEAN_M_S, rel=1e-9)
    assert comparison.simulated.any()


def test_a_run_with_the_recharge_budget_passes_the_gate(tmp_path) -> None:
    run = _run_2(tmp_path, budget_recharge=True, forcing=False)

    assert has_recharge_source(run)
    assert unavailable_reason_for_flow(run, tau_specific_ratio=1e-4) is None
    assert network_comparison_from_run(run, tau_specific_ratio=1e-4).simulated.any()


def test_a_grid_forced_run_without_a_recharge_budget_is_refused(tmp_path) -> None:
    run = _run_2(tmp_path, budget_recharge=False, forcing=False)

    reason = unavailable_reason_for_flow(run, tau_specific_ratio=1e-4)

    assert not has_recharge_source(run)
    assert reason is not None
    assert "tau = 0.0001" in reason
    assert "persisted no recharge budget and no dated recharge forcing" in reason
    with pytest.raises(ValueError, match="persisted no recharge budget"):
        network_comparison_from_run(run, tau_specific_ratio=1e-4)


def test_a_forcing_with_no_dates_to_place_it_on_is_not_a_source(tmp_path) -> None:
    run = _run_2(tmp_path, budget_recharge=False, forcing=True, dates=False)

    assert not has_recharge_source(run)
    assert unavailable_reason_for_flow(run, tau_specific_ratio=1e-4) is not None


def test_a_zero_ratio_asks_for_no_recharge(tmp_path) -> None:
    run = _run_2(tmp_path, budget_recharge=False, forcing=False)

    assert unavailable_reason_for_flow(run, tau_specific_ratio=0.0) is None
    comparison = network_comparison_from_run(run, tau_specific_ratio=0.0)
    assert comparison.geometry.mean_recharge_m_s == 0.0


def test_the_refusal_names_the_terms_a_consumers_run_left_out(tmp_path) -> None:
    run = _run_2(tmp_path, budget_recharge=False, forcing=False, policy=("consumers", ("drain",)))

    reason = unavailable_reason_for_flow(run, tau_specific_ratio=1e-4)

    assert "kept only the per-cell budget terms its consumers read (drain)" in reason
    assert "recharge" in reason.split("also needs")[1]
    assert "keep_per_cell_budget" in reason


def test_a_run_that_kept_the_whole_budget_gets_no_option_it_cannot_use(tmp_path) -> None:
    run = _run_2(tmp_path, budget_recharge=False, forcing=False, policy=("all", ("drain",)))

    reason = unavailable_reason_for_flow(run, tau_specific_ratio=1e-4)

    assert reason is not None
    assert "keep_per_cell_budget" not in reason


def test_a_run_without_release_flux_is_refused_without_the_retired_key(tmp_path) -> None:
    run = _run_2(tmp_path, budget_recharge=True, forcing=False, policy=("consumers", ("recharge",)))
    run.has_field = lambda variable, **_: variable in {"recharge", "topography"}

    reason = unavailable_reason_for_flow(run)

    assert reason.startswith("run has no per-cell release_flux")
    assert "[simulation.results.derived]" not in reason
    assert "keep_per_cell_budget" in reason


def test_the_budget_recharge_is_the_cell_rate_over_the_cell_area(tmp_path) -> None:
    run = _run_2(tmp_path, budget_recharge=True, forcing=False)
    area = float(run.mesh.vertices[:, 0].max() / NX) ** 2

    comparison = network_comparison_from_run(run, tau_specific_ratio=1e-4)

    assert comparison.geometry.mean_recharge_m_s == pytest.approx(
        run.field("recharge")[0] / area, rel=1e-9
    )


# A calibration can score the mapped network (``"reference"``) or the one the
# DEM was thresholded into (``"generated"``). The redraw must follow whichever
# one a trial actually used, or a map disagrees with the counts it publishes.
# The default stays ``"reference"`` so every existing caller is unaffected.
#
# The redraw also draws the mapped network by the trial's rule, with the same
# default, now the heads one: a map drawn thicker, or by a different rule, than
# the trial scored it would show cells the criterion never counted.
GENERATED_COLUMN = 4


def _run_with_role_specific_networks(**kwargs):
    """A run whose 'reference' and 'generated' networks sit on different columns.

    Seepage runs down the axis column, so it agrees with a 'reference' network
    drawn there and disagrees with a 'generated' one drawn on the far column.
    """
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, row) for row in range(NY)], **kwargs)
    reference = run.hydrographic_network("reference")
    generated_x = (GENERATED_COLUMN + 0.5) * CELL_M
    generated = gpd.GeoDataFrame(
        geometry=[LineString([(generated_x, 0.1 * CELL_M), (generated_x, (NY - 0.1) * CELL_M)])],
        crs=run.mesh.crs,
    )
    networks = {"reference": reference, "generated": generated}
    run.has_hydrographic_network = lambda role="generated": role in networks
    run.hydrographic_network = lambda role="generated": networks[role]
    return run


def _mapped_cells(comparison) -> list[int]:
    return sorted(int(index) for index in comparison.mapped.nonzero()[0])


def test_default_role_is_reference() -> None:
    # Pinned to crossing: the subject is which stored network the role picks,
    # not the rasterization rule.
    run = _run_with_role_specific_networks()

    comparison = network_comparison_from_run(run, observed_rasterization="crossing")

    assert _mapped_cells(comparison) == column_cells(AXIS_COLUMN)


def test_asking_for_generated_reaches_the_generated_network() -> None:
    # Pinned to crossing: the subject is which stored network the role picks,
    # not the rasterization rule, and the generated column here is not a tree
    # the heads rule could trace without losing its head.
    run = _run_with_role_specific_networks()

    comparison = network_comparison_from_run(
        run, role="generated", observed_rasterization="crossing"
    )

    assert _mapped_cells(comparison) == column_cells(GENERATED_COLUMN)


def test_unavailable_reason_follows_the_requested_role() -> None:
    run = _run_with_role_specific_networks()
    run.has_hydrographic_network = lambda role="generated": role == "reference"

    assert unavailable_reason_for_comparison(run) is None
    reason = unavailable_reason_for_comparison(run, role="generated")

    assert reason is not None
    assert "generated" in reason


def _run_with_a_diagonal_reference():
    """A run whose 'reference' network runs through three centers on a diagonal."""
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, row) for row in range(NY)])
    centres = [((k + 0.5) * CELL_M, (k + 0.5) * CELL_M) for k in range(NY)]
    diagonal = gpd.GeoDataFrame(geometry=[LineString(centres)], crs=run.mesh.crs)
    run.hydrographic_network = lambda role="generated": diagonal
    return run


def test_the_default_rule_is_heads_and_traces_a_connected_map() -> None:
    comparison = network_comparison_from_run(_run_with_a_diagonal_reference())

    mapped = _mapped_cells(comparison)
    assert mapped == [1, 2]
    assert cell(AXIS_COLUMN, 0) in mapped


def test_the_crossing_rule_draws_the_mapped_network_one_cell_per_step() -> None:
    comparison = network_comparison_from_run(
        _run_with_a_diagonal_reference(), observed_rasterization="crossing"
    )

    assert _mapped_cells(comparison) == [cell(k, k) for k in range(NY)]


def test_touch_replays_the_corner_cells_of_each_diagonal_step() -> None:
    comparison = network_comparison_from_run(
        _run_with_a_diagonal_reference(), observed_rasterization="touch"
    )

    assert len(_mapped_cells(comparison)) == NY + 2 * (NY - 1)


# A trial compares the catchment its graph closed with the outline the geographic
# step delineated (``catchment_mismatch``) and with the basin of D the build kept
# on the model (``basin_mismatch``). A redraw from the store reads the same two, so
# the numbers it prints are the ones the trials scored. A run sealed before the
# basin was stored keeps the delineated polygon for both and says so. The grid is
# the 5 x 3 valley of ``tests.unit.display._network_comparison_run``, whose graph
# catchment is the whole grid.
NO_BASIN_WARNING = "stores no basin of D"


def _run_3(*, basin: np.ndarray | None, rule: str = "near_point"):
    """A run whose delineated polygon spans columns 1 to 3 and whose graph closes on the grid."""
    run = comparison_run()
    narrow = gpd.GeoDataFrame(
        geometry=[box(1 * CELL_M, -0.1 * CELL_M, 4 * CELL_M, (NY + 0.1) * CELL_M)], crs=run.mesh.crs
    )

    def geographic(feature):
        assert feature == "watershed"
        return narrow

    run.geographic = geographic
    mesh = run.mesh
    attrs = {} if basin is None else {"basin_rule": rule}
    run.descent = RunDescent(
        lambda: replace(
            stored_descent(mesh.topography, mesh.face_node_connectivity, mesh.vertices),
            basin=basin,
            basin_attrs=attrs,
        )
    )
    return run


def _geometry(run):
    return network_comparison_from_run(run, observed_rasterization="crossing").geometry


def _mismatch(run) -> float:
    return _geometry(run).catchment_mismatch


def test_the_outline_and_the_stored_basin_each_have_their_mismatch(caplog) -> None:
    whole_grid = np.ones(NX * NY, dtype=bool)

    with caplog.at_level(logging.WARNING):
        geometry = _geometry(_run_3(basin=whole_grid))

    # The polygon spans 9 of the 15 cells the graph closes, and the basin all of them.
    assert geometry.catchment_mismatch == pytest.approx(6 / 9)
    assert geometry.basin_mismatch == pytest.approx(0.0)
    assert NO_BASIN_WARNING not in caplog.text


def test_a_stored_basin_without_a_watershed_measures_against_the_basin(caplog) -> None:
    run = _run_3(basin=np.ones(NX * NY, dtype=bool))

    def missing(feature):
        raise FileNotFoundError(feature)

    run.geographic = missing

    with caplog.at_level(logging.WARNING):
        assert _mismatch(run) == pytest.approx(0.0)
    assert (
        "Stream comparison: run sim-network carries no delineated watershed (FileNotFoundError), "
        "so catchment_mismatch has no outline to read, and a run without a basin of D "
        "re-derives its catchment by descending the model top to its own largest basin. "
        "On a real surface that basin is an internal depression."
    ) in caplog.text


def test_a_synthetic_domain_has_no_outline_as_in_a_trial() -> None:
    run = _run_3(basin=np.ones(NX * NY, dtype=bool), rule="largest_basin")
    run._catalog = SimpleNamespace(read_geographic_metadata=lambda _sim: {"catch_def": "synthetic"})

    geometry = _geometry(run)

    assert np.isnan(geometry.catchment_mismatch)
    assert np.isnan(geometry.basin_mismatch)


def test_a_run_without_a_stored_basin_keeps_the_polygon_and_says_so(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        mismatch = _mismatch(_run_3(basin=None))

    # The polygon spans 9 of the 15 cells the graph closes: 6 of them lie outside it.
    assert mismatch == pytest.approx(6 / 9)
    assert (
        "Stream comparison: run sim-network stores no basin of D, so the catchment mismatch "
        "is measured against the old reference 'polygon_centroid', as its trials were."
        in caplog.text
    )


def test_the_largest_basin_of_a_synthetic_domain_is_no_catchment(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        mismatch = _mismatch(_run_3(basin=np.ones(NX * NY, dtype=bool), rule="largest_basin"))

    assert mismatch == pytest.approx(6 / 9)
    assert NO_BASIN_WARNING not in caplog.text


def test_a_run_sealed_without_d_is_not_rebuilt_to_learn_it_has_no_basin(caplog) -> None:
    run = _run_3(basin=None)

    def refuse() -> None:
        raise AssertionError("D was loaded or rebuilt to read a basin that is not there")

    run.descent = RunDescent(refuse, load_basin=lambda: None)

    with caplog.at_level(logging.WARNING):
        mismatch = _mismatch(run)

    assert mismatch == pytest.approx(6 / 9)
    assert NO_BASIN_WARNING in caplog.text


def test_a_stored_basin_comes_back_as_booleans_of_its_first_member() -> None:
    stored = (np.array([1, 0, 1], dtype=np.int8), {"basin_rule": "near_point"})
    sim = SimpleNamespace(descent=SimpleNamespace(stored_basin=lambda: stored))

    catchment = _delineated_catchment(sim, None)

    assert catchment.dtype == bool
    assert catchment.tolist() == [True, False, True]


@pytest.mark.parametrize("watershed", [None, gpd.GeoDataFrame(geometry=[], crs="EPSG:2154")])
def test_a_watershed_with_nothing_in_it_gives_no_outline(watershed) -> None:
    run = _run_3(basin=None)
    run.geographic = lambda feature: watershed

    assert _watershed_catchment(run, np.empty((0, 4)), "EPSG:2154") is None


# A figure redraws what a trial scored, so it reads the settings of the network
# output the run sealed under ``[calibration.outputs]``, and the defaults when
# the run sealed none. The snapshot is the plain mapping a run stores: the
# results layer never imports the calibration schema.
def _network(**fields) -> dict:
    return {"support": "network", "observed_network": "data.hydrography", **fields}


def _run_4(outputs: dict | None = None, *, window: dict | None = None, **sections):
    run = SimpleNamespace(sim_id="sim-x", config_snapshot=dict(sections))
    if outputs is not None:
        window = {} if window is None else {"window": window}
        run.dir = sealed_search({"outputs": outputs, **window})
    return run


def test_a_run_without_a_snapshot_reads_the_defaults() -> None:
    settings = network_criterion_settings(SimpleNamespace(sim_id="sim-x"))

    assert settings == DEFAULT_CRITERION_SETTINGS
    assert settings.tau_specific_ratio == STREAM_CRITERION_DEFAULTS.tau_specific_ratio
    assert settings.diagonal_neighbors is STREAM_CRITERION_DEFAULTS.diagonal_neighbors
    assert settings.extent_rules == DEFAULT_EXTENT_RULES
    assert settings.extent_rules.visible_flow == DEFAULT_VISIBLE_FLOW
    assert "the defaults" in settings.note()


def test_a_run_without_a_network_output_reads_the_defaults() -> None:
    run = _run_4({"head": {"support": "point", "variable": "head"}})

    assert network_outputs_of_run(run) == {}
    assert network_criterion_settings(run).output is None


def test_every_setting_the_output_sealed_is_read() -> None:
    run = _run_4(
        {
            "streams": _network(
                tau_specific_ratio=0.0,
                diagonal_neighbors=False,
                observed_rasterization="touch",
                weighting="area",
                observed_position_accuracy=25.0,
                time="first",
                extent={
                    "maximal_flowing_duration": "3 months",
                    "minimal_dry_duration": "2 months",
                    "year_quorum": 0.75,
                    "visible_flow": "2%",
                    "weights": {"minimal": 0.5, "maximal": 0.5},
                },
            )
        }
    )

    settings = network_criterion_settings(run)

    assert settings.output == "streams"
    assert settings.tau_specific_ratio == 0.0
    assert settings.diagonal_neighbors is False
    assert settings.observed_rasterization == "touch"
    assert settings.observed_position_accuracy_m == 25.0
    assert settings.timestep == 0
    assert settings.extent == NetworkExtentRules(
        maximal_flowing_duration="3 months",
        minimal_dry_duration="2 months",
        year_quorum=0.75,
        visible_flow="2%",
    )
    assert settings.note() == "criterion settings: calibration output 'streams'"


def test_a_key_the_output_left_out_takes_the_default() -> None:
    settings = network_criterion_settings(_run_4({"streams": _network(extent={})}))

    assert settings.tau_specific_ratio == STREAM_CRITERION_DEFAULTS.tau_specific_ratio
    assert settings.observed_rasterization == STREAM_CRITERION_DEFAULTS.observed_rasterization
    assert settings.observed_position_accuracy_m is None
    assert settings.timestep == -1
    assert settings.extent == DEFAULT_EXTENT_RULES


def test_a_single_state_output_carries_no_extent_rules() -> None:
    settings = network_criterion_settings(_run_4({"streams": _network()}))

    assert settings.extent is None
    assert settings.extent_rules == DEFAULT_EXTENT_RULES


def test_a_positional_accuracy_with_its_unit_is_read_in_metres() -> None:
    run = _run_4({"streams": _network(observed_position_accuracy="0.05 km")})

    assert network_criterion_settings(run).observed_position_accuracy_m == pytest.approx(50.0)


def test_several_network_outputs_read_the_first_and_say_so() -> None:
    run = _run_4(
        {
            "first": _network(tau_specific_ratio=0.0),
            "head": {"support": "point", "variable": "head"},
            "second": _network(tau_specific_ratio=1.0e-2),
        }
    )

    settings = network_criterion_settings(run)

    assert settings.output == "first"
    assert settings.n_network_outputs == 2
    assert "one of 2 network outputs" in settings.note()
    assert network_criterion_settings(run, output="second").tau_specific_ratio == 1.0e-2


def test_an_output_the_run_did_not_seal_is_refused() -> None:
    with pytest.raises(ValueError, match="sealed no network output 'other'"):
        network_criterion_settings(_run_4({"streams": _network()}), output="other")


def test_a_sealed_value_no_trial_could_read_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown map.drawn_by"):
        network_criterion_settings(_run_4({"streams": _network(observed_rasterization="all")}))
    with pytest.raises(ValueError, match="carries no unit"):
        network_criterion_settings(_run_4({"streams": _network(extent={"visible_flow": "1"})}))


def test_the_scoring_window_the_run_sealed_is_read_and_named() -> None:
    run = _run_4({"streams": _network()}, window={"start": "2002-01-01T00:00:00+01:00"})

    settings = network_criterion_settings(run)

    assert settings.window == (pd.Timestamp("2002-01-01"), None)
    assert settings.note().endswith("window 2002-01-01 to open")


def test_a_window_with_both_bounds_open_is_no_window() -> None:
    run = _run_4({"streams": _network()}, window={})

    assert network_criterion_settings(run).window is None
    assert network_criterion_settings(_run_4({"streams": _network()})).window is None


def test_a_window_bound_that_is_not_a_date_is_refused() -> None:
    run = _run_4({"streams": _network()}, window={"start": "spring"})

    with pytest.raises(ValueError, match="window.start 'spring' is not a date"):
        network_criterion_settings(run)


# The seepage threshold is a fraction of the mean recharge. The criterion takes
# the mean over the recharge periods of the built model; a redraw that read the
# last timestep alone drew, on a transient run, another network than the one the
# trial scored. The outlet is placed from the snapped pour point the geographic
# step persisted, as the trial places it.
AREA_M2 = CELL_M * CELL_M


RECHARGE_BY_STEP_M3_S = (1.0e-4, 1.0e-4, 7.0e-4)


def _transient_run(**kwargs):
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, NY - 1)], **kwargs)
    release = run.field("release_flux")
    stacks = {
        "recharge": [np.full(NX * NY, value) for value in RECHARGE_BY_STEP_M3_S],
        "release_flux": [release] * len(RECHARGE_BY_STEP_M3_S),
    }

    def field(variable, time=-1, **_):
        return stacks[variable][time]

    run.n_timesteps = len(RECHARGE_BY_STEP_M3_S)
    run.field = field
    return run


def test_the_threshold_reads_the_time_mean_recharge() -> None:
    comparison = network_comparison_from_run(_transient_run(), tau_specific_ratio=1.0e-2)

    mean_rate = float(np.mean(RECHARGE_BY_STEP_M3_S)) / AREA_M2
    last_rate = RECHARGE_BY_STEP_M3_S[-1] / AREA_M2
    assert comparison.geometry.mean_recharge_m_s == pytest.approx(mean_rate)
    assert comparison.geometry.mean_recharge_m_s != pytest.approx(last_rate)
    assert comparison.geometry.threshold_m3_s[0] == pytest.approx(1.0e-2 * mean_rate * AREA_M2)


def test_a_steady_run_reads_its_one_state() -> None:
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, NY - 1)])
    run.n_timesteps = None

    comparison = network_comparison_from_run(run, tau_specific_ratio=1.0e-2)

    assert comparison.geometry.mean_recharge_m_s == pytest.approx(1.0e-4 / AREA_M2)


def test_the_outlet_is_placed_from_the_snapped_pour_point() -> None:
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, NY - 1)])
    # One cell up the eastern flank: the search moves it onto the axis.
    snapped = {
        "x_outlet_snapped": str((AXIS_COLUMN + 1.5) * CELL_M),
        "y_outlet_snapped": str(1.5 * CELL_M),
    }
    run._catalog.read_geographic_metadata = lambda sim_id: dict(snapped)

    comparison = network_comparison_from_run(run)

    assert comparison.geometry.outlet == cell(AXIS_COLUMN, 0)
    assert comparison.geometry.catchment.all()
    assert comparison.geometry.catchment_mismatch == pytest.approx(0.0)


# A run scored under ``observed_rasterization = "heads"`` sealed where a head may
# land: a snap radius and a minimum drained area. The redraw reads both back, so
# a figure traces the map the trials scored, and a key the run left out takes
# the criterion's default.
#
# On the 5 x 3 valley of cells of 1 ha, the mapped axis starts 40 m north of the
# center of its head cell, which drains 5 ha; the cell below drains 10 ha.
def _sealed_run(**heads):
    run = comparison_run()
    output = {
        "support": "network",
        "observed_network": "data.hydrography",
        "tau_specific_ratio": 0.0,
        "observed_rasterization": "heads",
        **heads,
    }
    run.dir = sealed_search({"outputs": {"streams": output}})
    return run


def _redraw(run):
    settings = network_criterion_settings(run)
    return network_comparison_from_run(
        run,
        tau_specific_ratio=settings.tau_specific_ratio,
        observed_rasterization=settings.observed_rasterization,
        heads_snap_radius_m=settings.heads_snap_radius_m,
        heads_min_drained_area_km2=settings.heads_min_drained_area_km2,
        clip_map_to_catchment=settings.clip_map_to_catchment,
    )


def test_a_key_left_out_takes_the_default() -> None:
    settings = network_criterion_settings(_sealed_run())

    assert settings.observed_rasterization == "heads"
    assert settings.heads_snap_radius_m == STREAM_CRITERION_DEFAULTS.heads_snap_radius_m
    assert settings.heads_min_drained_area_km2 == (
        STREAM_CRITERION_DEFAULTS.heads_min_drained_area_km2
    )


def test_the_sealed_area_moves_the_landing_cell() -> None:
    comparison = _redraw(_sealed_run(heads_snap_radius=150.0, heads_min_drained_area_km2=0.06))

    trace = comparison.geometry.heads
    assert trace is not None
    assert trace.settings.min_drained_area_m2 == pytest.approx(6.0e4)
    assert trace.head_cell.tolist() == [cell(AXIS_COLUMN, 1)]
    assert trace.snap_distance_m[0] == pytest.approx(140.0)


def test_the_sealed_radius_loses_a_head_the_default_would_keep() -> None:
    kept = _redraw(_sealed_run(heads_snap_radius=50.0, heads_min_drained_area_km2=0.04))
    assert kept.geometry.heads is not None
    assert kept.geometry.heads.head_cell.tolist() == [cell(AXIS_COLUMN, 2)]

    with pytest.raises(ValueError, match="snap radius 30 m"):
        _redraw(_sealed_run(heads_snap_radius="30 m", heads_min_drained_area_km2=0.04))


@pytest.mark.parametrize(
    ("sealed", "cut"),
    [
        ({}, True),
        ({"clip_map_to_catchment": True}, True),
        ({"clip_map_to_catchment": False}, False),
    ],
)
def test_the_redraw_takes_no_end_of_the_cut_for_a_head_unless_the_run_did(
    monkeypatch, sealed, cut
) -> None:
    real = network_heads.network_head_candidates
    outlines = []

    def spy(lines, **kwargs):
        outlines.append(kwargs.get("cut_outline"))
        return real(lines, **kwargs)

    monkeypatch.setattr(network_heads, "network_head_candidates", spy)

    _redraw(_sealed_run(heads_snap_radius=50.0, heads_min_drained_area_km2=0.04, **sealed))

    assert (outlines[0] is not None) is cut


# The results layer never sees the model: it reads ``run.descent.dam_foot``, the
# cells the build stored with D. A run whose D carries none draws as it did before
# the feet were stored. On the 5 x 3 valley a hillside cell of the north row stands
# for the foot of a dam.
HILLSIDE = 10  # column 0 of the north row: it drains along the row to the axis


def _run_with_dam_foot(cells):
    run = comparison_run()
    stored = replace(run.descent.view(), dam_foot=np.asarray(cells, dtype=np.int64))
    run.descent = RunDescent(lambda: stored)
    return run


def _redraw_2(run):
    return network_comparison_from_run(
        run, tau_specific_ratio=0.0, observed_rasterization="heads", heads_min_drained_area_km2=0.0
    )


def test_a_stored_dam_foot_is_traced_as_a_forced_head() -> None:
    comparison = _redraw_2(_run_with_dam_foot([HILLSIDE]))

    trace = comparison.geometry.heads
    assert trace is not None
    assert trace.forced_cell.tolist() == [HILLSIDE]
    assert comparison.geometry.observed[HILLSIDE]
    assert comparison.geometry.diagnostics["n_forced_heads"] == 1.0


def test_a_run_whose_descent_stores_no_foot_draws_as_before() -> None:
    plain = _redraw_2(comparison_run())
    empty = _redraw_2(_run_with_dam_foot([]))

    assert not plain.geometry.observed[HILLSIDE]
    np.testing.assert_array_equal(empty.geometry.observed, plain.geometry.observed)
    assert empty.geometry.diagnostics["n_forced_heads"] == 0.0


def test_the_heads_view_carries_the_forced_heads_apart() -> None:
    view = network_heads_view_from_run(_run_with_dam_foot([HILLSIDE]))

    assert view.full.forced_xy.shape == (1, 2)
    assert view.full.indices["n_forced_heads"] == 1.0
    assert view.full.head_xy.shape[0] == 1


# A phase's ``window`` replaces the calibration's for every block it
# scores, and the protocol writes its default spin-up window on its transient
# stage. The run's phase is the one of the session its trial belongs to.
NETWORK = {"support": "network", "observed_network": "data.hydrography"}


def _run_5(calibration: dict, *, phase: str | None, dashed: bool = False) -> SimpleNamespace:
    """A run whose trial belongs to one session of the named phase."""
    session = uuid.uuid4()
    trial_id = str(session) if dashed else session.hex
    sessions = [
        {"session_id": session, "phase_name": phase},
        {"session_id": uuid.uuid4(), "phase_name": "other"},
    ]
    return SimpleNamespace(
        sim_id="sim-x",
        dir=sealed_search(calibration),
        calibration_iterations=[{"session_id": trial_id, "iteration": 0}],
        calibration_sessions=pd.DataFrame(sessions),
    )


def _phases(window: dict | None) -> list[dict]:
    transient = {"name": "transient", "parameters": ["Sy"]}
    if window is not None:
        transient["window"] = window
    return [{"name": "steady", "parameters": ["K"]}, transient]


def test_the_window_of_the_run_s_phase_wins_over_the_calibration_s() -> None:
    calibration = {
        "outputs": {"streams": NETWORK},
        "window": {"start": "2001-01-01"},
        "phases": _phases({"start": "2003-01-01", "end": "2005-12-31"}),
    }

    settings = network_criterion_settings(_run_5(calibration, phase="transient"))

    assert settings.window == (pd.Timestamp("2003-01-01"), pd.Timestamp("2005-12-31"))
    assert settings.window_phase == "transient"
    assert settings.note().endswith("window 2003-01-01 to 2005-12-31 of phase 'transient'")


def test_a_session_id_spelled_with_dashes_finds_its_phase() -> None:
    calibration = {"outputs": {"streams": NETWORK}, "phases": _phases({"start": "2003-01-01"})}

    settings = network_criterion_settings(_run_5(calibration, phase="transient", dashed=True))

    assert settings.window == (pd.Timestamp("2003-01-01"), None)


def test_a_phase_without_a_window_reads_the_calibration_s() -> None:
    calibration = {
        "outputs": {"streams": NETWORK},
        "window": {"start": "2001-01-01"},
        "phases": _phases({"start": "2003-01-01"}),
    }

    settings = network_criterion_settings(_run_5(calibration, phase="steady"))

    assert settings.window == (pd.Timestamp("2001-01-01"), None)
    assert settings.window_phase is None
    assert settings.note().endswith("window 2001-01-01 to open")


def test_a_run_tied_to_no_phase_reads_the_calibration_s() -> None:
    calibration = {
        "outputs": {"streams": NETWORK},
        "window": {"start": "2001-01-01"},
        "phases": _phases({"start": "2003-01-01"}),
    }
    run = SimpleNamespace(sim_id="sim-x", dir=sealed_search(calibration))

    assert network_criterion_settings(run).window == (pd.Timestamp("2001-01-01"), None)
    assert network_criterion_settings(_run_5(calibration, phase=None)).window_phase is None


def test_a_phase_window_open_on_both_ends_is_no_window() -> None:
    calibration = {
        "outputs": {"streams": NETWORK},
        "window": {"start": "2001-01-01"},
        "phases": _phases({}),
    }

    settings = network_criterion_settings(_run_5(calibration, phase="transient"))

    assert settings.window is None
    assert "window" not in settings.note()


def test_the_protocol_s_spin_up_window_reaches_a_run_of_its_transient_stage() -> None:
    document = {
        "simulation": {"time": {"start_datetime": "2020-01-01", "end_datetime": "2023-12-31"}},
        "data": {"hydrometry": {"sources": [{"station_ids": ["NANCON"]}]}},
        "calibration": {
            "protocol": {"name": "matching_hydrographic_network"},
            "parameters": {"K": {"bounds": [1e-8, 1e-2]}, "Sy": {"bounds": [1e-4, 0.5]}},
            "outputs": {"net": {"support": "network", "stream_geometry_path": "map.gpkg"}},
        },
    }
    calibration = expand_calibration_protocol(document)["calibration"]

    transient = network_criterion_settings(_run_5(calibration, phase=TRANSIENT_STAGE))
    steady = network_criterion_settings(_run_5(calibration, phase=STEADY_STAGE))

    assert transient.window == (pd.Timestamp("2021-01-01"), None)
    assert transient.window_phase == TRANSIENT_STAGE
    assert steady.window is None


# The run is the monthly V-valley of :mod:`tests._helpers.transient_network_run`:
# in January (step 0) the whole axis flows, in June (step 5) the outlet alone at
# two litres per second. The field is 1 on the flowing cells and 0 elsewhere,
# cut with the run's sealed settings, the defaults when it sealed none.
def test_each_step_holds_the_cells_flowing_at_that_step() -> None:
    stack = simulated_active_network_stack(transient_run(), [0, 5])

    assert stack.shape[0] == 2
    assert set(np.unique(stack)) <= {0.0, 1.0}
    january, june = stack
    assert january[[OUTLET, MIDDLE, HEAD]].tolist() == [1.0, 1.0, 1.0]
    assert june[[OUTLET, MIDDLE, HEAD]].tolist() == [1.0, 0.0, 0.0]
    assert january[HILLSLOPE] == 0.0


def test_the_sealed_visible_flow_cuts_the_summer_outlet() -> None:
    """At 5 L/s the two-litre summer outlet no longer flows."""
    run = transient_run()
    run.dir = sealed_search(
        {
            "outputs": {
                "streams": {
                    "support": "network",
                    "observed_network": "data.hydrography",
                    "tau_specific_ratio": 1.0e-4,
                    "extent": {"visible_flow": "5 L/s"},
                }
            }
        }
    )
    (june,) = simulated_active_network_stack(run, [5])
    assert june[OUTLET] == 0.0


def test_a_run_without_a_release_flux_is_refused_by_name() -> None:
    run = transient_run()
    run.has_field = lambda variable, **_: variable == "topography"
    with pytest.raises(ValueError, match="no per-cell release_flux"):
        simulated_active_network_stack(run, [0])


def test_the_field_describes_itself_as_a_mask() -> None:
    descriptor = field_descriptor(SIMULATED_ACTIVE_NETWORK)
    assert descriptor.units == "1"
    assert descriptor.shape == "time_face"
    assert (descriptor.valid_min, descriptor.valid_max) == (0.0, 1.0)
