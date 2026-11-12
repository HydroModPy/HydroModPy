"""The stream network a figure redraws from a stored run, as the trials scored it.

The criterion cuts the network at tau * R * A, with R the mean recharge (m/s) the
trial read and A a cell area (m2). The redraw takes R, the outlet, the basin and the
sealed settings from the store, so the numbers it prints are the ones the trials
scored. Tests run on the 5 x 3 valley of 1 ha cells of
``tests.unit.display._network_comparison_run``, whose graph catchment is the whole grid.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, box

from hydromodpy.catchment.stream_network import geometry as stream_geometry
from hydromodpy.catchment.stream_network.geometry import build_network_geometry
from hydromodpy.core.time.window import (
    ResolvedSimulationTimeWindow,
    build_simulation_time_boundaries,
)
from hydromodpy.core.units.quantities import factor_to_m_per_s
from hydromodpy.mesh.planar.geometry import cell_polygons
from hydromodpy.model.forcing.recharge_rates import forcing_period_rates, mean_recharge_m_s
from hydromodpy.model.forcing.time_alignment import align_forcing_series_to_simulation_window
from hydromodpy.results.derive.stream_network.comparison import (
    has_recharge_source,
    network_comparison_from_run,
    no_recharge_reason,
    unavailable_reason_for_comparison,
)
from hydromodpy.results.derive.stream_network.criterion_inputs import catchment_cells
from hydromodpy.results.derive.stream_network.criterion_settings import network_criterion_settings
from hydromodpy.results.derive.stream_network.run_extent import unavailable_reason_for_flow
from hydromodpy.results.run.descent import RunDescent, StoredBasin
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from tests._helpers.sealed_runs import sealed_search
from tests.unit.display._network_comparison_run import (
    AXIS_COLUMN,
    CELL_M,
    NX,
    NY,
    cell,
    comparison_run,
    stored_descent,
)

CELL_AREA_M2 = CELL_M * CELL_M
MM_PER_DAY = factor_to_m_per_s("mm/day")

# Three monthly samples in mm/day, stamped at the end of their month as the
# Nancon file is, and the three monthly periods of the run.
FORCING_MM_D = pd.Series(
    [2.09, 0.76, 0.5], index=pd.DatetimeIndex(["2000-01-31", "2000-02-29", "2000-03-31"])
)
EDGES = pd.DatetimeIndex(["2000-01-01", "2000-02-01", "2000-03-01", "2000-04-01"])
RATES_M_S = FORCING_MM_D.to_numpy() * MM_PER_DAY
PERIOD_DAYS = np.array([31.0, 29.0, 31.0])
RECORD_MEAN_M_S = float(np.average(RATES_M_S, weights=PERIOD_DAYS))

# Recharge of the valley in m3/s at each of three steps. The mean is the one a
# trial reads, not the last step.
RECHARGE_BY_STEP_M3_S = (1.0e-4, 1.0e-4, 7.0e-4)

GENERATED_COLUMN = 4
NO_BASIN_WARNING = "carries no basin of D"


@pytest.fixture(autouse=True)
def fresh_process(monkeypatch):
    """Each test starts as a new process, with no recharge seen."""
    monkeypatch.setattr(stream_geometry, "_last_mean_recharge", {})


def recharge_moves(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "mean recharge moved" in r.getMessage()]


def trial_build(model) -> None:
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


def monthly_window(start: str, end: str) -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp(start),
        end=pd.Timestamp(end),
        step_value=1,
        step_unit="month",
        coverage_policy="error",
    )


# The by-hand Nancon calibration scores the network in a steady phase, then promotes
# a transient run whose first period is a steady spin-up. The trials read the rate
# the forcing gives each period (9.062e-9 m/s on average). Averaging the budget the
# solver wrote would give the spin-up period the record mean in place of January.
def test_models_hold_record_mean() -> None:
    steady = SimpleNamespace(recharge=pd.Series([RECORD_MEAN_M_S]))
    transient = SimpleNamespace(
        recharge=pd.Series(RATES_M_S, index=EDGES[:-1]), perlen=PERIOD_DAYS * 86400.0
    )

    assert mean_recharge_m_s(steady) == pytest.approx(RECORD_MEAN_M_S, rel=1e-12)
    assert mean_recharge_m_s(transient) == pytest.approx(RECORD_MEAN_M_S, rel=1e-12)


def test_a_grid_weighs_its_cells_by_area_and_its_periods_by_length() -> None:
    fine_and_coarse = np.array([1.0, 100.0])
    model = SimpleNamespace(
        recharge={0: np.array([3.0, 1.0]), 1: np.array([5.0, 1.0])},
        solver_mesh=SimpleNamespace(cell_areas=lambda: fine_and_coarse),
        perlen=np.array([1.0, 3.0]),
    )

    own = [(3.0 + 100.0) / 101.0, (5.0 + 100.0) / 101.0]
    assert mean_recharge_m_s(model) == pytest.approx(np.average(own, weights=[1.0, 3.0]))


def test_series_is_one_rate_per_period() -> None:
    mesh = SimpleNamespace(cell_areas=lambda: np.array([1.0, 100.0]))
    model = SimpleNamespace(
        recharge=pd.Series([3.0, 1.0]), solver_mesh=mesh, perlen=np.array([1.0, 3.0])
    )

    assert mean_recharge_m_s(model) == pytest.approx(1.5)


FORCING_SAMPLES = [
    pytest.param(
        # The example 04 file, monthly, stamped at each month's end.
        pd.Series(
            [2.088043, 0.760928, 0.551107, 0.642604, 0.0, 1.2],
            index=pd.to_datetime(
                ["2000-01-31", "2000-02-29", "2000-03-31", "2000-04-30", "2000-05-31", "2000-06-30"]
            ),
        ),
        id="monthly file",
    ),
    pytest.param(
        # A daily series with a gap: April has no sample and carries March's last one.
        pd.Series(
            [1.0, 3.0, 2.0, 5.0, 4.0],
            index=pd.to_datetime(
                ["2000-01-10", "2000-01-20", "2000-02-15", "2000-03-31", "2000-05-02"]
            ),
        ),
        id="daily series with a gap",
    ),
]


@pytest.mark.parametrize("samples", FORCING_SAMPLES)
def test_criterion_rates_match_forcing(samples: pd.Series) -> None:
    # Two copies of one rule: the solver forcing and the criterion must not drift apart.
    window = monthly_window("2000-01-01", "2000-05-31")
    forced = align_forcing_series_to_simulation_window(samples, simulation_window=window)

    rates = forcing_period_rates(samples, build_simulation_time_boundaries(window))

    assert rates == pytest.approx(np.maximum(forced.to_numpy(dtype=float), 0.0))


def test_run_gives_trial_recharge() -> None:
    comparison = network_comparison_from_run(comparison_run(kept_recharge=1.25e-8))

    assert comparison.geometry.mean_recharge_m_s == pytest.approx(1.25e-8)


def test_redraw_reads_scored_recharge(caplog) -> None:
    steady = SimpleNamespace(recharge=pd.Series([RECORD_MEAN_M_S]))

    with (
        caplog.at_level(logging.INFO, logger=stream_geometry.__name__),
        stream_geometry.recharge_session("session"),
    ):
        trial_build(steady)
        comparison = network_comparison_from_run(
            comparison_run(kept_recharge=mean_recharge_m_s(steady))
        )

    assert comparison.geometry.mean_recharge_m_s == pytest.approx(RECORD_MEAN_M_S, rel=1e-9)
    assert recharge_moves(caplog) == []


def test_the_threshold_reads_the_kept_recharge() -> None:
    mean_rate = float(np.mean(RECHARGE_BY_STEP_M3_S)) / CELL_AREA_M2
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, NY - 1)], kept_recharge=mean_rate)

    comparison = network_comparison_from_run(run, tau_specific_ratio=1.0e-2)

    last_rate = RECHARGE_BY_STEP_M3_S[-1] / CELL_AREA_M2
    assert comparison.geometry.mean_recharge_m_s == pytest.approx(mean_rate)
    assert comparison.geometry.mean_recharge_m_s != pytest.approx(last_rate)
    assert comparison.geometry.threshold_m3_s[0] == pytest.approx(1.0e-2 * mean_rate * CELL_AREA_M2)


def test_steady_run_one_state() -> None:
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, NY - 1)])
    run.n_timesteps = None

    comparison = network_comparison_from_run(run, tau_specific_ratio=1.0e-2)

    assert comparison.geometry.mean_recharge_m_s == pytest.approx(1.0e-4 / CELL_AREA_M2)


def test_outlet_from_snapped_pour_point() -> None:
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


def run_with_budget_policy(tmp_path, policy):
    """A run whose store says which per-cell budget terms it kept, and no recharge."""
    run = comparison_run(kept_recharge=False)
    run.has_field = lambda variable, **_: variable in {"release_flux", "topography"}
    path = tmp_path / "fields.zarr"
    SimulationZarr.create(path, n_cells=0, n_layers=1).close()
    writer = SimulationZarr(path)
    budget = writer.root.require_group("budget")
    budget.attrs.update({"policy": policy[0], "kept_terms": list(policy[1])})
    writer.close()
    run._catalog.open_zarr = lambda sim_id: SimulationZarr(path)
    return run


# Redrawing a network the DEM was thresholded into ("generated") must follow the
# role a trial used, or a map disagrees with the counts it publishes. The default
# stays "reference".
def run_with_two_networks():
    """A run whose 'reference' and 'generated' networks sit on different columns."""
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, row) for row in range(NY)])
    generated_x = (GENERATED_COLUMN + 0.5) * CELL_M
    generated = gpd.GeoDataFrame(
        geometry=[LineString([(generated_x, 0.1 * CELL_M), (generated_x, (NY - 0.1) * CELL_M)])],
        crs=run.mesh.crs,
    )
    networks = {"reference": run.hydrographic_network("reference"), "generated": generated}
    run.has_hydrographic_network = lambda role="generated": role in networks
    run.hydrographic_network = lambda role="generated": networks[role]
    return run


def test_unavailable_reason_by_role() -> None:
    run = run_with_two_networks()
    run.has_hydrographic_network = lambda role="generated": role == "reference"

    assert unavailable_reason_for_comparison(run) is None
    reason = unavailable_reason_for_comparison(run, role="generated")

    assert reason is not None
    assert "generated" in reason


# A trial compares the catchment its graph closed with the outline the geographic
# step delineated (catchment_mismatch) and with the basin of D the build kept on
# the model (basin_mismatch). A run sealed before the basin was stored keeps the
# delineated polygon for both and says so.
def descent_with(run, *, basin, rule="near_point", outline=None) -> RunDescent:
    """The descent of ``run`` with a stored basin and a stored outline, as a store gives them."""
    mesh = run.mesh
    stored = (
        None
        if basin is None
        else StoredBasin(mask=basin, area_m2=float(basin.sum()) * CELL_M**2, rule=rule)
    )
    return RunDescent(
        lambda: stored_descent(mesh.topography, mesh.face_node_connectivity, mesh.vertices),
        load_basin=lambda: stored,
        load_open_water=lambda: np.zeros(NX * NY, dtype=bool),
        load_catchment_cells=lambda: outline,
        load_recharge=lambda: 1.0e-8,
    )


def run_with_polygon(*, basin: np.ndarray | None, rule: str = "near_point", outline: bool = True):
    """A run whose delineated polygon spans columns 1 to 3 and whose graph closes on the grid."""
    run = comparison_run()
    narrow = gpd.GeoDataFrame(
        geometry=[box(1 * CELL_M, -0.1 * CELL_M, 4 * CELL_M, (NY + 0.1) * CELL_M)], crs=run.mesh.crs
    )
    cells = catchment_cells(
        cell_polygons(run.mesh.vertices, run.mesh.face_node_connectivity),
        narrow,
        mesh_crs=run.mesh.crs,
    )
    run.descent = descent_with(run, basin=basin, rule=rule, outline=cells if outline else None)
    return run


def geometry_of(run):
    return network_comparison_from_run(run, observed_rasterization="crossing").geometry


def test_outline_and_basin_mismatch(caplog) -> None:
    whole_grid = np.ones(NX * NY, dtype=bool)

    with caplog.at_level(logging.WARNING):
        geometry = geometry_of(run_with_polygon(basin=whole_grid))

    # The polygon spans 9 of the 15 cells the graph closes, and the basin all of them.
    assert geometry.catchment_mismatch == pytest.approx(6 / 9)
    assert geometry.basin_mismatch == pytest.approx(0.0)
    assert NO_BASIN_WARNING not in caplog.text


def test_basin_without_outline() -> None:
    run = run_with_polygon(basin=np.ones(NX * NY, dtype=bool), outline=False)

    assert geometry_of(run).catchment_mismatch == pytest.approx(0.0)


def test_synthetic_domain_no_outline() -> None:
    run = run_with_polygon(basin=np.ones(NX * NY, dtype=bool), rule="largest_basin", outline=False)

    geometry = geometry_of(run)

    assert np.isnan(geometry.catchment_mismatch)
    assert np.isnan(geometry.basin_mismatch)


def test_no_stored_basin_keeps_polygon(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        mismatch = geometry_of(run_with_polygon(basin=None)).catchment_mismatch

    # The polygon spans 9 of the 15 cells the graph closes: 6 of them lie outside it.
    assert mismatch == pytest.approx(6 / 9)
    assert (
        "Network criterion: run sim-network carries no basin of D, so the catchment mismatch "
        "is measured against the old reference 'polygon_centroid'." in caplog.text
    )


def test_largest_basin_is_no_catchment(caplog) -> None:
    run = run_with_polygon(basin=np.ones(NX * NY, dtype=bool), rule="largest_basin")

    with caplog.at_level(logging.WARNING):
        mismatch = geometry_of(run).catchment_mismatch

    assert mismatch == pytest.approx(6 / 9)
    assert NO_BASIN_WARNING not in caplog.text


def test_run_without_d_not_rebuilt(caplog) -> None:
    run = run_with_polygon(basin=None)
    outline = np.isin(np.arange(NX * NY), [1, 2, 3, 6, 7, 8, 11, 12, 13])

    def refuse() -> None:
        raise AssertionError("D was loaded or rebuilt to read a basin that is not there")

    run.descent = RunDescent(
        refuse,
        load_basin=lambda: None,
        load_open_water=lambda: np.zeros(NX * NY, dtype=bool),
        load_catchment_cells=lambda: outline,
        load_recharge=lambda: 1.0e-8,
    )

    with caplog.at_level(logging.WARNING):
        mismatch = geometry_of(run).catchment_mismatch

    assert mismatch == pytest.approx(6 / 9)
    assert NO_BASIN_WARNING in caplog.text


# A watershed with nothing in it gives no outline, whatever the file held.
@pytest.mark.parametrize("watershed", [None, gpd.GeoDataFrame(geometry=[], crs="EPSG:2154")])
def test_empty_watershed_no_outline(watershed) -> None:
    assert catchment_cells(np.empty((0, 4)), watershed, mesh_crs="EPSG:2154") is None


# A run scored under observed_rasterization = "heads" sealed where a head may land,
# a snap radius (m) and a minimum drained area (km2). The redraw reads both back.
# On the valley, the mapped axis starts 40 m north of the center of its head cell,
# which drains 5 ha. The cell below drains 10 ha.
def sealed_heads_run(**map_knobs):
    run = comparison_run()
    output = {
        "support": "network",
        "model": {"seepage_threshold": 0.0},
        "map": {"complete": "data.hydrography", "drawn_by": "heads", **map_knobs},
    }
    run.dir = sealed_search({"outputs": {"streams": output}})
    return run


def redraw(run):
    settings = network_criterion_settings(run)
    return network_comparison_from_run(
        run,
        tau_specific_ratio=settings.tau_specific_ratio,
        observed_rasterization=settings.observed_rasterization,
        heads_snap_radius_m=settings.heads_snap_radius_m,
        heads_min_drained_area_km2=settings.heads_min_drained_area_km2,
        clip_map_to_catchment=settings.clip_map_to_catchment,
    )


def test_the_sealed_area_moves_the_landing_cell() -> None:
    comparison = redraw(sealed_heads_run(heads={"radius": 150.0, "min_drained_area": 0.06}))

    trace = comparison.geometry.heads
    assert trace is not None
    assert trace.settings.min_drained_area_m2 == pytest.approx(6.0e4)
    assert trace.head_cell.tolist() == [cell(AXIS_COLUMN, 1)]
    assert trace.snap_distance_m[0] == pytest.approx(140.0)


def test_sealed_radius_loses_head() -> None:
    kept = redraw(sealed_heads_run(heads={"radius": 50.0, "min_drained_area": 0.04}))
    assert kept.geometry.heads is not None
    assert kept.geometry.heads.head_cell.tolist() == [cell(AXIS_COLUMN, 2)]

    with pytest.raises(ValueError, match="snap radius 30 m"):
        redraw(sealed_heads_run(heads={"radius": "30 m", "min_drained_area": 0.04}))


# A run that kept no mean recharge is refused by one sentence that says how to get
# one, and a zero ratio asks for none. The gate and the computation ask one predicate,
# has_recharge_source.
def test_no_recharge_refusal() -> None:
    run = comparison_run(kept_recharge=False)

    reason = unavailable_reason_for_flow(run, tau_specific_ratio=1e-4)

    assert not has_recharge_source(run)
    assert reason == no_recharge_reason()
    assert reason == (
        "This run kept no criterion mean recharge, so a seepage threshold cannot be read on it. "
        "Replay it with hmp replay, or set tau_specific_ratio = 0."
    )
    with pytest.raises(ValueError, match="kept no criterion mean recharge"):
        network_comparison_from_run(run, tau_specific_ratio=1e-4)


def test_no_open_water_refusal() -> None:
    run = comparison_run()
    run.descent = RunDescent(lambda: None)

    reason = unavailable_reason_for_comparison(run)

    assert reason is not None
    assert "mesh/open_water" in reason
    assert "hmp replay" in reason


@pytest.mark.parametrize(
    "policy",
    [
        pytest.param(("consumers", ("drain",)), id="consumers only"),
        pytest.param(("all", ("drain",)), id="every term"),
    ],
)
def test_recharge_refusal_by_budget_policy(tmp_path, policy) -> None:
    run = run_with_budget_policy(tmp_path, policy)

    assert unavailable_reason_for_flow(run, tau_specific_ratio=1e-4) == no_recharge_reason()
