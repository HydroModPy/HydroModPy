"""Tests of `metrics.solver_extract`."""

from __future__ import annotations

import datetime
import json
import logging
import tomllib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from shapely.geometry import LineString

from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    CalibOutputCell,
    CalibOutputLake,
    CalibOutputNetwork,
    CalibOutputPoint,
    CalibrationConfig,
    validate_calib_output,
)
from hydromodpy.calibration.criteria import criterion_for
from hydromodpy.calibration.metrics import ObservedSeries as ObservedSeries__metrics_extractors
from hydromodpy.calibration.metrics import (
    build_metric_extractor,
    composite,
    observable_scoring,
    solver_extract,
)
from hydromodpy.calibration.metrics import composite as _composite_module
from hydromodpy.calibration.metrics import solver_extract as _solver_extract
from hydromodpy.calibration.metrics import solver_extract as _solver_extract_module
from hydromodpy.calibration.metrics.composite import _build_composite_metric_extractor  # noqa: F401
from hydromodpy.calibration.metrics.gauge_snap import GaugeSnapError, snap_to_most_accumulated
from hydromodpy.calibration.metrics.observable_scoring import ObservableScorer, StationBlockScorer
from hydromodpy.calibration.metrics.observable_scoring import slice_time as _slice_time
from hydromodpy.calibration.metrics.series import ObservedSeries, load_observed
from hydromodpy.calibration.metrics.solver_extract import (
    _coerce_length_to_m,
    _saturated_thickness_or_none,
    catchment_saturation,
    cell_for_station,
    extract_outputs,
    network_state_row,
    observable_request_for_output,
    resolve_station_cells,
)
from hydromodpy.calibration.metrics.solver_extract import extract_outputs as _extract_outputs
from hydromodpy.calibration.metrics.solver_extract import (
    observable_request_for_output as _request_for_output,
)
from hydromodpy.calibration.metrics.solver_extract import (
    resolve_station_cells as _resolve_station_cells,
)
from hydromodpy.calibration.observations.network_geometry import (
    network_maps_from_run,
    union_projection,
)
from hydromodpy.calibration.observations.network_source import UnresolvedObservedNetwork
from hydromodpy.calibration.observations.observed_network import ObservedNetworkMask
from hydromodpy.calibration.optim.objective import build_objective_from_config
from hydromodpy.catchment.drainage.descent import DescentBasin
from hydromodpy.catchment.drainage.distance import resolve_outlet
from hydromodpy.core.contracts.observables import ObservableRequest, ObservableResult
from hydromodpy.core.exceptions import ObjectiveError, ObservableNotAvailableError
from hydromodpy.core.time.selection import TimeSelectionError, resolve_state
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.results.derive.stream.geometry import build_network_geometry
from hydromodpy.solver.base.cell_lookup import (
    locate_cell_on_solver_mesh,
    top_active_layer_on_solver_mesh,
)
from hydromodpy.solver.boussinesq.adapter import BoussinesqFlowAdapter
from hydromodpy.solver.modflow6.adapter import Modflow6FlowAdapter
from hydromodpy.solver.modflow6.extractors.lake import extract_lake_series
from hydromodpy.solver.modflow_common import observable_extraction as _extraction
from hydromodpy.solver.modflow_common.flow_directions import build_solver_mesh_descent
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_nwt.adapter import ModflowNwtFlowAdapter
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays
from tests._helpers.ugrid_meshes import quad_mesh
from tests._helpers.v_valley import (
    AXIS_COL,
    CELL_SIZE,
    FIRST_OBSERVED_ROW,
    N_CELLS,
    N_COLS,
    N_ROWS,
    build_bench,
    cell_id,
    observed_network,
    simulated_network,
)
from tests.unit.calibration._factories import one_state
from tests.unit.calibration._factories_scoring import (
    CRS,
    SPIN_UP_RUN,
    WINDOW,
    StackAdapter,
    adapter_result,
    axis_file,
    axis_line,
    boundary_output,
    make_trial_ctx,
    monthly_bounds,
    network_output,
    objective_block,
    release_stack,
    run_extraction,
    seasonal_thresholds,
    stream_file_fixture,  # noqa: F401
)
from tests.unit.solver.modflow_common.solver_runs import solved_run

# From test_a_cell_target_without_layer_reads_the_top_active_cell.py
# A cell target given without a layer reads the top active cell of its column.
#
# The v2 vertical contract places a point without a layer in the top active cell
# of its column. ``CalibOutputCell.layer`` used to default to 0, which is a
# pinched cell (idomain -1) or an inactive one where layer 0 does not reach. The
# layer is now asked of the flow adapter when the request is built, through
# ``CellLocator.top_active_layer``: the MODFLOW backends read the idomain of the
# run, Boussinesq has one layer. An explicit layer keeps its meaning, and a
# backend that cannot answer is refused rather than read at layer 0.


NROW, NCOL, NLAY = 2, 3, 3


def _pinched_mesh() -> SolverMesh:
    """Three layers on 2 x 3 cells. Row 0, col 1 loses layer 0; row 1, col 2 loses two."""
    mesh = solver_mesh_from_structured_arrays(
        nrow=NROW,
        ncol=NCOL,
        top=np.full((NROW, NCOL), 30.0),
        botm=np.stack([np.full((NROW, NCOL), z) for z in (20.0, 10.0, 0.0)]),
    )
    idomain = np.ones((NLAY, NROW, NCOL), dtype=int)
    idomain[0, 0, 1] = -1
    idomain[0, 1, 2] = -1
    idomain[1, 1, 2] = 0
    return replace(mesh, idomain=idomain.reshape(NLAY, -1))


def _wire(monkeypatch, adapter: object, model: object) -> SimpleNamespace:
    run_ctx = SimpleNamespace(
        run=SimpleNamespace(id="r1"), solver_run=SimpleNamespace(solver_model=model)
    )
    monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, run_ctx))
    return SimpleNamespace()


@pytest.fixture(params=[Modflow6FlowAdapter, ModflowNwtFlowAdapter], ids=["mf6", "nwt"])
def ctx__cell_target(request, monkeypatch):
    return _wire(monkeypatch, request.param(), SimpleNamespace(solver_mesh=_pinched_mesh()))


def _cell(**selector: int) -> CalibOutputCell:
    return CalibOutputCell.model_validate({"variable": "head", "support": "cell", **selector})


def test_a_cell_target_declares_no_layer_by_default() -> None:
    assert _cell(row=0, col=1).layer is None


def test_a_column_pinched_at_layer_0_is_read_at_layer_1(ctx__cell_target) -> None:
    request = observable_request_for_output("piezo", _cell(row=0, col=1), ctx__cell_target)
    assert request.cell == (1, 0, 1)


def test_a_column_that_starts_lower_is_read_at_its_first_active_layer(ctx__cell_target) -> None:
    request = observable_request_for_output("piezo", _cell(row=1, col=2), ctx__cell_target)
    assert request.cell == (2, 1, 2)


def test_a_column_active_from_the_top_is_read_at_layer_0(ctx__cell_target) -> None:
    request = observable_request_for_output("piezo", _cell(row=1, col=0), ctx__cell_target)
    assert request.cell == (0, 1, 0)


@pytest.mark.parametrize("layer", [0, 2])
def test_an_explicit_layer_is_kept_even_on_a_pinched_column(ctx__cell_target, layer: int) -> None:
    request = observable_request_for_output(
        "piezo", _cell(row=0, col=1, layer=layer), ctx__cell_target
    )
    assert request.cell == (layer, 0, 1)


def test_a_cell_outside_the_grid_is_refused_by_name(ctx__cell_target) -> None:
    with pytest.raises(ValueError, match="'piezo'.*outside the 2 x 3 grid"):
        observable_request_for_output("piezo", _cell(row=5, col=0), ctx__cell_target)


def test_the_one_layer_solver_reads_layer_0(monkeypatch) -> None:
    ctx = _wire(monkeypatch, BoussinesqFlowAdapter(), SimpleNamespace())
    request = observable_request_for_output("piezo", _cell(row=1, col=2), ctx)
    assert request.cell == (0, 1, 2)


def test_a_run_without_a_grid_is_refused_rather_than_read_at_layer_0(monkeypatch) -> None:
    ctx = _wire(monkeypatch, Modflow6FlowAdapter(), None)
    with pytest.raises(NotImplementedError, match="'piezo' gives no layer.*no grid yet"):
        observable_request_for_output("piezo", _cell(row=1, col=2), ctx)


def test_a_backend_that_cannot_answer_is_refused_by_name(monkeypatch) -> None:
    ctx = _wire(monkeypatch, object(), SimpleNamespace(solver_mesh=_pinched_mesh()))
    with pytest.raises(NotImplementedError, match="'piezo' gives no layer.*Write the layer"):
        observable_request_for_output("piezo", _cell(row=0, col=1), ctx)


# From test_a_gauge_block_scores_what_a_gauge_measures.py
# A block fitted to a gauge has to be scored on the gauge's own quantity.
#
# Measured on a real Nancon run before this was fixed: the single-metric route
# returned a cost of 0.259 and the weighted-block route 82.97 on the same
# simulation, the same twelve monthly samples and the same parameter. The pairing
# was right, 12 of 12 with nothing clipped; the quantity was not. A drain budget is
# baseflow alone, and a gauge measures the whole streamflow, so the runoff forcing
# is owed on both routes or neither.


CELL = (0, 7)
AREA_M2 = 6.4e7
TIMES = pd.date_range("2015-01-31", periods=3, freq="ME")
BASEFLOW = np.array([1.0, 2.0, 3.0])
RUNOFF_ADDED = 0.5
CATCHMENT_KM2 = 64.6
BASIN_M2 = 64.77e6


class _Adapter:
    """Serves a dated discharge at a cell and the area that cell drains."""

    def __init__(self, *, includes_runoff: bool) -> None:
        self.includes_runoff = includes_runoff
        self.asked: list[tuple[str, str]] = []

    def observables(self, _run_ctx, requests, time_index=None):
        out = {}
        for request in requests:
            self.asked.append((request.name, request.support))
            if request.name == "upstream_area":
                out[request.id] = adapter_result(request.id, np.array([AREA_M2]), "m2")
                continue
            out[request.id] = ObservableResult(
                request_id=request.id,
                values=BASEFLOW.copy(),
                units="m3 s-1",
                times=TIMES,
                includes_runoff=self.includes_runoff,
            )
        return out


@pytest.fixture
def wired(monkeypatch):
    def _wire(
        *,
        includes_runoff: bool,
        observes: str | None,
        station_cell=CELL,
        basin: DescentBasin | None = None,
        builds_descent: bool = True,
    ):
        adapter = _Adapter(includes_runoff=includes_runoff)
        model = SimpleNamespace(descent_basin=basin) if builds_descent else SimpleNamespace()
        run_ctx = SimpleNamespace(solver_run=SimpleNamespace(solver_model=model))
        monkeypatch.setattr(
            _solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, run_ctx)
        )
        monkeypatch.setattr(_solver_extract, "find_cell_at_point", lambda *_: CELL)
        monkeypatch.setattr(_solver_extract, "cell_for_station", lambda *_a, **_k: station_cell)
        monkeypatch.setattr(_solver_extract, "resolve_time_index", lambda *_a, **_k: TIMES)
        seen: dict[str, float | None] = {}

        def _add_runoff(series, _ctx, *, area_m2=None):
            seen["area_m2"] = None if area_m2 is None else float(area_m2)
            return series + RUNOFF_ADDED

        monkeypatch.setattr(_solver_extract, "add_runoff_to_discharge", _add_runoff)
        declaration = {"variable": "discharge", "support": "point", "x": 1.0, "y": 2.0}
        if observes is not None:
            declaration["observes"] = observes
        outputs = {"gauge": CalibOutputPoint.model_validate(declaration)}
        ctx = SimpleNamespace(
            setup=SimpleNamespace(geographic=SimpleNamespace(catch_area=CATCHMENT_KM2))
        )
        return adapter, seen, extract_outputs(ctx, outputs)

    return _wire


def test_a_baseflow_discharge_fitted_to_a_gauge_gets_the_runoff(wired) -> None:
    _adapter, seen, extracted = wired(includes_runoff=False, observes="NANCON")
    assert seen["area_m2"] == pytest.approx(AREA_M2)
    assert extracted.series["gauge"].to_numpy() == pytest.approx(BASEFLOW + RUNOFF_ADDED)
    # The positional values the block scores have to carry the same correction,
    # or the two faces of one output disagree.
    assert np.asarray(extracted.values["gauge"]) == pytest.approx(BASEFLOW + RUNOFF_ADDED)
    observable = extracted.observables["gauge"]
    assert observable.values == pytest.approx(BASEFLOW + RUNOFF_ADDED)
    assert observable.times.equals(TIMES)
    assert observable.units == "m3 s-1"
    assert observable.includes_runoff is True


def test_the_area_that_cell_drains_is_asked_for(wired) -> None:
    adapter, _seen, _extracted = wired(includes_runoff=False, observes="NANCON")
    assert ("upstream_area", "cell") in adapter.asked


def test_a_routed_discharge_is_left_alone(wired) -> None:
    # SFR injected the runoff into the reaches; adding it again counts it twice.
    _adapter, seen, extracted = wired(includes_runoff=True, observes="NANCON")
    assert "area_m2" not in seen
    assert extracted.series["gauge"].to_numpy() == pytest.approx(BASEFLOW)


def test_the_share_of_the_catchment_the_gauge_cell_drains_is_published(wired) -> None:
    # No universal threshold exists to veto on, so the number is stated beside the
    # cost on every run: a station two cells off the talweg is then visible.
    _adapter, _seen, extracted = wired(includes_runoff=False, observes="NANCON")
    assert extracted.diagnostics["gauge.drained_fraction"] == pytest.approx(
        (AREA_M2 / 1e6) / CATCHMENT_KM2
    )


def test_a_gauge_whose_cell_no_loader_placed_scores_the_catchment_series(wired) -> None:
    # A discharge station is deliberately not located by its coordinate, so on a
    # project where nothing resolved its cell there is one series to score it on,
    # the whole catchment's, which is what the single-metric route falls back to
    # and what an outlet gauge measures. Refusing instead left a weighted block
    # unable to fit a gauge on any such project, which is every project whose
    # loader writes no cell for a hydrometric station.
    adapter, seen, extracted = wired(includes_runoff=False, observes="NANCON", station_cell=None)
    assert ("discharge", "domain") in adapter.asked
    assert ("upstream_area", "cell") not in adapter.asked
    # The runoff is still owed, and the basin's own forcing needs no area.
    assert seen["area_m2"] is None
    assert extracted.series["gauge"].to_numpy() == pytest.approx(BASEFLOW + RUNOFF_ADDED)
    assert "gauge.drained_fraction" not in extracted.diagnostics


def _basin(rule: str) -> DescentBasin:
    return DescentBasin(
        mask=np.ones(4, dtype=bool),
        outlet=3,
        rule=rule,
        area_m2=BASIN_M2,
        seeded_at_outlet=False,
    )


def test_the_catchment_series_is_scaled_by_the_basin_it_sums(wired) -> None:
    # The drain is summed over the basin of D, so its runoff covers that same area.
    _adapter, seen, extracted = wired(
        includes_runoff=False, observes="NANCON", station_cell=None, basin=_basin("near_point")
    )
    assert seen["area_m2"] == pytest.approx(BASIN_M2)
    assert extracted.series["gauge"].to_numpy() == pytest.approx(BASEFLOW + RUNOFF_ADDED)


def test_a_model_without_a_basin_names_the_old_runoff_area(wired, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        _adapter, seen, _extracted = wired(
            includes_runoff=False, observes="NANCON", station_cell=None
        )
    assert seen["area_m2"] is None
    assert (
        "Calibration discharge: the model carries no basin of D, so the runoff is scaled by "
        "the old support 'catch_area' (64.600 km2)." in caplog.text
    )


def test_a_model_that_builds_no_d_names_the_old_runoff_area_without_a_warning(
    wired, caplog
) -> None:
    # Boussinesq has no D, so no basin: expected, not an anomaly to warn about at each trial.
    with caplog.at_level(logging.INFO):
        _adapter, seen, _extracted = wired(
            includes_runoff=False, observes="NANCON", station_cell=None, builds_descent=False
        )
    assert seen["area_m2"] is None
    records = [r for r in caplog.records if "carries no basin of D" in r.getMessage()]
    assert records
    assert {r.levelno for r in records} == {logging.INFO}


def test_the_largest_basin_of_a_synthetic_domain_keeps_the_old_area_silently(wired, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        _adapter, seen, _extracted = wired(
            includes_runoff=False,
            observes="NANCON",
            station_cell=None,
            basin=_basin("largest_basin"),
        )
    assert seen["area_m2"] is None
    assert "carries no basin of D" not in caplog.text


def test_a_gauge_cell_keeps_the_area_it_drains_whatever_the_basin(wired) -> None:
    _adapter, seen, _extracted = wired(
        includes_runoff=False, observes="NANCON", basin=_basin("near_point")
    )
    assert seen["area_m2"] == pytest.approx(AREA_M2)


def test_an_output_fitted_to_no_record_is_left_alone(wired) -> None:
    # Nothing says the vector typed into the file is what a gauge measures.
    adapter, seen, extracted = wired(includes_runoff=False, observes=None)
    assert "area_m2" not in seen
    assert ("upstream_area", "cell") not in adapter.asked
    assert extracted.series["gauge"].to_numpy() == pytest.approx(BASEFLOW)


# From test_a_gauge_snaps_only_when_asked.py
# A gauge moves onto the most accumulated cell only when its output asks.
#
# A discharge gauge coordinate is rarely on the talweg the model routes on: on the
# Nancon it resolves to a cell draining 0.107 km2 of 64.6. ``snap_radius`` moves it
# onto the most accumulated cell within a radius. It is opt-in, so every project
# that does not write it keeps the cell it had.
#
# The grid is a 5 x 5 V-shaped valley of 100 m cells whose talweg is column 2,
# flowing towards the last row. Its drained areas, in cells, are::
#
#     1  2   5  2  1
#     1  2  10  2  1
#     1  2  15  2  1
#     1  2  20  2  1
#     1  2  25  2  1
#
# The accumulation is the solver's own: the fake adapter serves the
# ``upstream_area`` field through the shared MODFLOW extraction.


N = 5
CELL_M2 = 1.0e4
GAUGE_XY = (140.0, 250.0)


def _valley_model() -> SimpleNamespace:
    rows, cols = np.mgrid[0:N, 0:N]
    top = 10.0 * np.abs(cols - 2) + (N - rows) * 1.0 + 5.0
    mesh = solver_mesh_from_structured_arrays(
        nrow=N, ncol=N, top=top, botm=np.full((1, N, N), -10.0), dx=100.0, dy=100.0
    )
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    return SimpleNamespace(solver_mesh=mesh, descent=descent)


class _Adapter__gauge_snaps:
    """Serves the solver's own drained areas and cell centers, and a flat baseflow."""

    def __init__(self, model: SimpleNamespace) -> None:
        self.model = model
        self.asked: list = []

    def observables(self, _run_ctx, requests, time_index=None):
        self.asked.extend(requests)
        geometry = [r for r in requests if r.name in ("upstream_area", "cell_xy")]
        served, _ = _extraction.extract_common_modflow_observables(
            Path("."), "model", self.model, geometry
        )
        for request in requests:
            if request.name == "discharge":
                served[request.id] = adapter_result(
                    request.id, np.ones(TIMES.size), "m3 s-1", times=TIMES
                )
        return served

    def locate_cell(self, run_ctx, x, y):
        return locate_cell_on_solver_mesh(run_ctx, x, y)

    def top_active_layer(self, run_ctx, row, col):
        return top_active_layer_on_solver_mesh(run_ctx, row, col)


@pytest.fixture
def adapter__gauge_snaps(monkeypatch) -> _Adapter:
    model = _valley_model()
    fake = _Adapter__gauge_snaps(model)
    run_ctx = SimpleNamespace(
        solver_run=SimpleNamespace(solver_model=model),
        run=SimpleNamespace(id="flow", solver="modflow6"),
    )
    monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda _ctx: (fake, run_ctx))
    monkeypatch.setattr(_solver_extract, "resolve_time_index", lambda *_a, **_k: TIMES)
    monkeypatch.setattr(
        _extraction, "catchment_cell_mask", lambda m: np.ones(m.solver_mesh.n_cells, bool)
    )
    return fake


def _point(**extra) -> CalibOutputPoint:
    return CalibOutputPoint.model_validate(
        {"variable": "discharge", "x": GAUGE_XY[0], "y": GAUGE_XY[1], **extra}
    )


def _asked_for_the_field(fake: _Adapter) -> bool:
    return any(r.name == "upstream_area" and r.support == "cells" for r in fake.asked)


# --- the pure rule ---------------------------------------------------------
def _grid_centres() -> np.ndarray:
    rows, cols = np.mgrid[0:N, 0:N]
    return np.column_stack([50.0 + 100.0 * cols.ravel(), 50.0 + 100.0 * rows.ravel()])


def _grid_accumulation() -> np.ndarray:
    acc = np.tile([1.0, 2.0, 0.0, 2.0, 1.0], (N, 1))
    acc[:, 2] = 5.0 * np.arange(1, N + 1)
    return acc.ravel() * CELL_M2


def test_a_snap_within_the_radius_lands_on_the_talweg() -> None:
    snap = snap_to_most_accumulated(
        _grid_centres(), _grid_accumulation(), x=140.0, y=250.0, radius_m=120.0, start_index=11
    )
    assert snap.moved
    assert snap.index_after == 2 * N + 2
    assert snap.distance_m == pytest.approx(110.0)
    assert snap.area_before_m2 == pytest.approx(2 * CELL_M2)
    assert snap.area_after_m2 == pytest.approx(15 * CELL_M2)


def test_the_radius_is_a_maximum_displacement() -> None:
    """At 150 m the diagonal talweg cell 148.7 m away is reached, and wins."""
    snap = snap_to_most_accumulated(
        _grid_centres(), _grid_accumulation(), x=140.0, y=250.0, radius_m=150.0, start_index=11
    )
    assert snap.index_after == 3 * N + 2
    assert snap.distance_m == pytest.approx(np.hypot(110.0, 100.0))


def test_a_gauge_already_on_the_talweg_stays_put() -> None:
    snap = snap_to_most_accumulated(
        _grid_centres(),
        _grid_accumulation(),
        x=250.0,
        y=450.0,
        radius_m=150.0,
        start_index=4 * N + 2,
    )
    assert not snap.moved


def test_a_radius_too_small_says_so() -> None:
    with pytest.raises(GaugeSnapError, match=r"reaches no cell but the one.*90\.0 m away"):
        snap_to_most_accumulated(
            _grid_centres(), _grid_accumulation(), x=140.0, y=250.0, radius_m=50.0, start_index=11
        )


# --- the wiring, on the solver's own accumulation ---------------------------
def test_default_off_leaves_the_cell_unchanged(adapter__gauge_snaps: _Adapter) -> None:
    request = observable_request_for_output("gauge", _point(), SimpleNamespace())
    assert request.cell == (0, 0, 2 * N + 1)
    assert not _asked_for_the_field(adapter__gauge_snaps)


def test_a_point_snap_moves_the_cell_and_logs_both_areas(
    adapter__gauge_snaps: _Adapter, caplog
) -> None:
    with caplog.at_level(logging.INFO):
        request = observable_request_for_output(
            "gauge", _point(snap_radius="120 m"), SimpleNamespace()
        )
    assert request.cell == (0, 0, 2 * N + 2)
    assert _asked_for_the_field(adapter__gauge_snaps)
    message = " ".join(record.getMessage() for record in caplog.records)
    assert "snapped 110.0 m (of 120 m allowed)" in message
    assert "draining 0.020 km2" in message
    assert "draining 0.150 km2" in message


def test_a_radius_too_small_is_refused_through_the_output(adapter__gauge_snaps: _Adapter) -> None:
    with pytest.raises(GaugeSnapError, match="'gauge'.*90.0 m away"):
        observable_request_for_output("gauge", _point(snap_radius=50.0), SimpleNamespace())


def test_a_cell_output_snaps_from_its_own_centre(adapter__gauge_snaps: _Adapter) -> None:
    output = CalibOutputCell.model_validate(
        {"variable": "discharge", "row": 2, "col": 1, "snap_radius": 100.0}
    )
    request = observable_request_for_output("gauge", output, SimpleNamespace())
    assert request.cell == (0, 0, 2 * N + 2)


def _station_ctx() -> SimpleNamespace:
    record = SimpleNamespace(
        station_id="J0000000", location=SimpleNamespace(x=GAUGE_XY[0], y=GAUGE_XY[1])
    )
    return SimpleNamespace(loaded_data=SimpleNamespace(hydrometry=SimpleNamespace(points=[record])))


def test_a_named_discharge_station_keeps_the_catchment_series_by_default(
    adapter__gauge_snaps: _Adapter,
) -> None:
    """The measured default: a discharge station is not placed by its coordinate."""
    output = _point(observes="J0000000")
    request = observable_request_for_output("gauge", output, _station_ctx())
    assert request.support == "domain"
    assert not _asked_for_the_field(adapter__gauge_snaps)


def test_a_named_discharge_station_is_placed_and_snapped_when_asked(
    adapter__gauge_snaps: _Adapter,
) -> None:
    output = CalibOutputPoint.model_validate(
        {
            "variable": "discharge",
            "observes": "J0000000",
            # Written beside the station, and ignored: its record says where it is.
            "x": 450.0,
            "y": 450.0,
            "snap_radius": 120.0,
        }
    )
    request = observable_request_for_output("gauge", output, _station_ctx())
    assert request.support == "cell"
    assert request.cell == (0, 0, 2 * N + 2)


def test_several_gauges_each_snap_to_their_own_cell(adapter__gauge_snaps: _Adapter) -> None:
    outputs = {
        "upper": _point(x=160.0, y=350.0, snap_radius=100.0),
        "lower": _point(x=160.0, y=150.0, snap_radius=100.0),
    }
    extract_outputs(SimpleNamespace(), outputs)
    discharge = {r.id: r.cell for r in adapter__gauge_snaps.asked if r.name == "discharge"}
    areas = {
        r.id: r.cell for r in adapter__gauge_snaps.asked if r.name == "upstream_area" and r.cell
    }
    assert discharge == {"upper": (0, 0, 1 * N + 2), "lower": (0, 0, 3 * N + 2)}
    assert areas == {}  # no 'observes': no runoff scaling asked


def test_two_gauges_snapped_onto_one_cell_are_named(adapter__gauge_snaps: _Adapter, caplog) -> None:
    outputs = {
        "a": _point(x=160.0, y=350.0, snap_radius=100.0),
        "b": _point(x=160.0, y=340.0, snap_radius=100.0),
    }
    with caplog.at_level(logging.WARNING):
        extract_outputs(SimpleNamespace(), outputs)
    assert any(
        f"a, b were all snapped onto cell (0, 0, {1 * N + 2})" in record.getMessage()
        for record in caplog.records
    )


# --- the declaration --------------------------------------------------------
def test_a_snap_radius_on_a_head_is_refused() -> None:
    with pytest.raises(ValidationError, match="not a discharge"):
        CalibOutputPoint.model_validate(
            {"variable": "head", "x": 0.0, "y": 0.0, "snap_radius": 100.0}
        )


def test_a_non_positive_snap_radius_is_refused() -> None:
    with pytest.raises(ValidationError, match="must be > 0 m"):
        CalibOutputCell.model_validate(
            {"variable": "discharge", "row": 0, "col": 0, "snap_radius": 0.0}
        )


def test_the_default_is_off() -> None:
    assert _point().snap_radius is None
    assert (
        CalibOutputCell.model_validate({"variable": "discharge", "row": 0, "col": 0}).snap_radius
        is None
    )


# --- the solver serves the centers, the calibration never reads the mesh ----
def test_the_solver_serves_the_cell_centres_a_snap_searches() -> None:
    model = _valley_model()
    served, unserved = _extraction.extract_common_modflow_observables(
        Path("."),
        "model",
        model,
        [
            ObservableRequest(id="all", name="cell_xy", support="cells"),
            ObservableRequest(id="one", name="cell_xy", support="cell", cell=(0, 2, 1)),
        ],
    )

    assert unserved == []
    assert served["all"].values.shape == (N * N, 2)
    assert served["all"].units == "m"
    np.testing.assert_allclose(served["one"].values, served["all"].values[2 * N + 1])


# From test_a_heads_output_scores_the_trace_of_its_heads.py
# A network output drawn by its heads scores the trace of those heads.
#
# Under ``observed_rasterization = "heads"`` the calibration projects no cell
# from the mapped lines: it keeps their free ends, lands each on a cell draining
# enough, and the criterion graph draws the rest. On the V-valley bench the
# mapped talweg starts on row 12, which drains 169 cells of 100 m2; the default
# 0.02 km2 first holds on row 14, so the scored map is the axis from row 14 to
# the outlet, and the trial publishes how the head landed.


LANDING_ROW = 14


def _run_ctx(bench):
    """A trial context exposing what network_maps_from_run reads, the talweg mapped."""
    lines = gpd.GeoDataFrame(geometry=[axis_line()], crs=CRS)
    network = SimpleNamespace(vector_path="/fake/streams.gpkg", crs=CRS, read_vector=lambda: lines)
    return make_trial_ctx(bench, networks={"reference": network, "generated": None})


def _heads_output():
    return validate_calib_output(
        {
            "support": "network",
            "map": {"complete": "data.hydrography", "drawn_by": "heads"},
            "model": {"neighbours": "D8", "seepage_threshold": 0.0},
        }
    )


def _trace() -> np.ndarray:
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[[cell_id(row, AXIS_COL) for row in range(LANDING_ROW, N_ROWS)]] = True
    return mask


def test_a_heads_output_scores_the_trace_of_its_heads() -> None:
    maps = network_maps_from_run(_run_ctx(build_bench()), _heads_output())

    np.testing.assert_array_equal(maps.maximal.observed, _trace())
    assert maps.maximal_projection.rasterization == "heads"
    np.testing.assert_array_equal(maps.maximal_projection.mask, _trace())
    assert maps.maximal.heads is not None
    assert maps.maximal.heads.indices["n_heads"] == 1.0
    assert maps.maximal.heads.indices["head_snap_p90_m"] == pytest.approx(
        (LANDING_ROW - FIRST_OBSERVED_ROW) * CELL_SIZE
    )


class _AxisRelease:
    """Releases on the mapped trace, so the trial matches the drawn map exactly."""

    def observables(self, ctx, requests, *, time_index=None):
        del ctx, time_index
        return {
            request.id: adapter_result(request.id, np.where(_trace(), 1e-06, 0.0), "m3 s-1")
            for request in requests
        }


def test_the_trial_publishes_how_the_heads_drew_the_map(monkeypatch) -> None:
    run_ctx = _run_ctx(build_bench())
    adapter = _AxisRelease()
    monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda ctx: (adapter, run_ctx))

    diagnostics = extract_outputs(run_ctx, {"net": _heads_output()}).diagnostics

    assert diagnostics["net.n_observed_cells"] == float(N_ROWS - LANDING_ROW)
    assert diagnostics["net.n_heads"] == 1.0
    assert diagnostics["net.n_heads_lost"] == 0.0
    assert diagnostics["net.heads_trace_near_map_share"] == 1.0


# From test_a_network_state_is_read_at_its_date.py
# A network output read in one state reads the state its ``time`` names.
#
# ``time`` is ``"last"``, ``"first"`` or a date, and a date reads the period
# ``[s, e)`` that holds it, as :mod:`hydromodpy.core.time.selection` resolves
# it. The backend serves the whole stack for a date, and the extraction has to
# serve the criterion that one row, not the last one it was given. The trial
# context is faked and everything it feeds is real: the V-valley mesh, a mapped
# network read off disk, and a monthly release stack whose network moves over
# the year.


MONTHS = pd.date_range("2000-01-01", periods=37, freq="MS")


def _scored(monkeypatch, bench, stream_file, stack, bounds, time):
    outputs = {"net": one_state(stream_file, time)}
    return run_extraction(monkeypatch, bench, outputs, stack, bounds)[0].diagnostics


class TestTheDeclaration:
    def test_a_date_is_accepted_beside_first_and_last(self) -> None:
        for time in ("last", "first", "2002-10-15"):
            assert CalibOutputNetwork(map={"complete": "n.gpkg"}, time=time).time == time

    def test_a_bare_toml_date_is_kept_as_its_iso_spelling(self) -> None:
        output = CalibOutputNetwork(map={"complete": "n.gpkg"}, time=datetime.date(2002, 10, 15))
        assert output.time == "2002-10-15"

    @pytest.mark.parametrize("time", ["all", ["2002-01-01"], "October"])
    def test_what_names_no_single_state_is_refused(self, time) -> None:
        with pytest.raises(ValidationError, match="network"):
            CalibOutputNetwork(map={"complete": "n.gpkg"}, time=time)

    def test_the_extent_table_still_takes_no_time(self) -> None:
        with pytest.raises(ValidationError, match="extent"):
            CalibOutputNetwork(map={"complete": "n.gpkg"}, model={"extent": {}}, time="2002-10-15")


class TestWhichPeriodADateReads:
    def test_a_date_reads_the_month_that_holds_it(self) -> None:
        assert resolve_state("2002-10-15", MONTHS, n_periods=36) == 33
        assert resolve_state("2002-11-01", MONTHS, n_periods=36) == 33
        assert resolve_state("2002-10-01", MONTHS, n_periods=36) == 32

    def test_first_and_last_read_the_ends(self) -> None:
        assert resolve_state("first", MONTHS, n_periods=36) == 0
        assert resolve_state("last", MONTHS, n_periods=36) == 35

    def test_a_steady_period_holds_every_date_of_its_window(self) -> None:
        steady = (pd.Timestamp("2000-01-01"), pd.Timestamp("2003-01-01"))
        for date in ("2000-01-01", "2002-10-15", "2002-12-31"):
            assert resolve_state(date, steady, n_periods=1) == 0

    def test_one_state_without_dates_is_served_to_any_selector(self) -> None:
        assert resolve_state("2002-10-15", None, n_periods=1) == 0

    def test_a_date_outside_the_run_is_refused(self) -> None:
        with pytest.raises(TimeSelectionError, match="outside the record"):
            resolve_state("2004-01-15", MONTHS, n_periods=36)


class TestTheRowServed:
    def release_stack(self) -> ObservableResult:
        values = np.arange(36, dtype=float)[:, None] * np.ones((1, 4))
        return adapter_result("net", values, "m3 s-1", times=MONTHS[1:])

    def test_a_date_is_served_its_own_row(self) -> None:
        output = CalibOutputNetwork(map={"complete": "n.gpkg"}, time="2002-10-15")
        row, index = network_state_row("net", output, self.release_stack(), tuple(MONTHS))
        assert index == 33
        assert np.asarray(row.values).tolist() == [[33.0] * 4]
        assert pd.DatetimeIndex(row.times).tolist() == [pd.Timestamp("2002-11-01")]

    def test_the_stamps_date_the_stack_when_the_grid_does_not(self) -> None:
        output = CalibOutputNetwork(map={"complete": "n.gpkg"}, time="2001-03-31")
        row, index = network_state_row("net", output, self.release_stack(), None)
        assert index == 14
        assert np.asarray(row.values)[0, 0] == 14.0

    def test_one_state_is_served_as_it_came(self) -> None:
        output = CalibOutputNetwork(map={"complete": "n.gpkg"}, time="2002-10-15")
        one = adapter_result("net", np.ones(4), "m3 s-1")
        row, index = network_state_row("net", output, one, None)
        assert row is one
        assert index is None

    def test_a_date_on_an_undated_stack_is_refused_by_name(self) -> None:
        output = CalibOutputNetwork(map={"complete": "n.gpkg"}, time="2002-10-15")
        undated = adapter_result("net", np.ones((3, 4)), "m3 s-1")
        with pytest.raises(ObjectiveError, match="Output 'net': time = '2002-10-15'"):
            network_state_row("net", output, undated, None)


class TestTheStateScored:
    """The criterion scores the state the date names, and no other."""

    def test_a_date_scores_what_that_month_alone_scores(
        self, monkeypatch, bench, stream_file
    ) -> None:  # noqa: F811
        thresholds = seasonal_thresholds(3, wet_first_year=True)
        october = 12 + 9  # October 2001, the 22nd month of the run
        dated = _scored(
            monkeypatch,
            bench,
            stream_file,
            release_stack(bench, thresholds),
            SPIN_UP_RUN,
            "2001-10-15",
        )
        alone = _scored(
            monkeypatch,
            bench,
            stream_file,
            release_stack(bench, thresholds[october : october + 1]),
            None,
            "last",
        )
        assert dated["net.D_so"] == pytest.approx(alone["net.D_so"])
        assert dated["net.D_os"] == pytest.approx(alone["net.D_os"])
        assert dated["net.n_network_sim"] == alone["net.n_network_sim"]

    def test_the_date_is_not_the_last_state(self, monkeypatch, bench, stream_file) -> None:  # noqa: F811
        stack = release_stack(bench, seasonal_thresholds(3, wet_first_year=True))
        dated = _scored(monkeypatch, bench, stream_file, stack, SPIN_UP_RUN, "2001-10-15")
        last = _scored(monkeypatch, bench, stream_file, stack, SPIN_UP_RUN, "last")
        assert dated["net.n_network_sim"] != last["net.n_network_sim"]

    def test_a_date_the_run_does_not_hold_stops_the_trial(
        self, monkeypatch, bench, stream_file
    ) -> None:  # noqa: F811
        with pytest.raises(ObjectiveError, match="outside the record"):
            _scored(
                monkeypatch,
                bench,
                stream_file,
                release_stack(bench, seasonal_thresholds(3, wet_first_year=True)),
                SPIN_UP_RUN,
                "2005-06-01",
            )


# From test_a_point_output_asks_for_what_it_declares.py
# A gauge declared at a coordinate has to be scored on the gauge's quantity.
#
# The point support used to coerce every declared variable to ``head``, which made
# the commonest calibration target in the project, the discharge at a gauge,
# unreachable through the weighted-block route: a block naming `observes` on a
# point output was scored on a water level instead, and nothing said so. The
# translation is one function, so the fix is gated here.


CELL__point_output = (0, 12)


@pytest.fixture
def ctx__point_output(monkeypatch):
    monkeypatch.setattr(
        "hydromodpy.calibration.metrics.solver_extract.find_cell_at_point",
        lambda _ctx, _x, _y: CELL__point_output,
    )
    return SimpleNamespace()


def _point__point_output(variable: str) -> CalibOutputPoint:
    return CalibOutputPoint.model_validate(
        {"variable": variable, "support": "point", "x": 1.0, "y": 2.0}
    )


def test_a_head_target_is_unchanged(ctx__point_output) -> None:
    request = observable_request_for_output(
        "piezo", _point__point_output("head"), ctx__point_output
    )
    assert (request.name, request.support, request.cell) == ("head", "cell", CELL__point_output)


def test_a_discharge_target_asks_for_the_discharge(ctx__point_output) -> None:
    request = observable_request_for_output(
        "gauge", _point__point_output("discharge"), ctx__point_output
    )
    assert (request.name, request.support, request.cell) == (
        "discharge",
        "cell",
        CELL__point_output,
    )


def test_the_request_is_the_one_the_single_metric_route_already_builds(ctx__point_output) -> None:
    # `composite.py` resolves a station to its cell and asks for
    # ObservableRequest(name="discharge", support="cell", cell=...). A block
    # scoring the same gauge has to ask the solver the same question, or the two
    # routes are not comparable.
    request = observable_request_for_output(
        "gauge", _point__point_output("discharge"), ctx__point_output
    )
    assert request.name == "discharge"
    assert request.support == "cell"


def test_a_point_with_no_coordinates_is_refused_at_declaration() -> None:
    with pytest.raises(ValueError, match="requires both 'x' and 'y'"):
        CalibOutputPoint.model_validate({"variable": "head", "support": "point"})


def test_a_point_that_observes_a_station_needs_no_coordinates() -> None:
    """'observes' locates the point by the station's own record.

    A protocol writing this output has no coordinate to give it, and none is
    read once 'observes' is set (`observable_request_for_output` above).
    """
    declaration = CalibOutputPoint.model_validate(
        {"variable": "discharge", "support": "point", "observes": "NANCON"}
    )
    assert declaration.x is None
    assert declaration.y is None


@pytest.mark.parametrize(
    ("model", "selector"),
    [
        (CalibOutputPoint, {"support": "point", "x": 1.0, "y": 2.0}),
        (CalibOutputCell, {"support": "cell", "row": 3, "col": 7}),
    ],
)
def test_a_gauge_declares_no_neighbourhood_of_its_own(model, selector) -> None:
    # The discharge at a gauge is routed on the descent D of the build, whose
    # neighborhood the mesh fixes. A per-output knob would route one gauge on
    # another graph than the area it is snapped by, so the key is refused.
    with pytest.raises(ValueError, match="diagonal_neighbors"):
        model.model_validate({"variable": "discharge", "diagonal_neighbors": True, **selector})


# From test_a_station_is_located_by_its_record.py
# A station's position lives on its record, and the resolver has to read it.
#
# Measured on a real Nancon run: no station resolved to a cell, so every gauge was
# scored on the whole-catchment discharge whatever its position. The cause was one
# lookup that read ``x``/``y``, ``easting``/``northing``, ``longitude``/``latitude``
# and a geometry, and never ``PointRecord.location``, which is where every loader
# puts it. Right for a gauge at the outlet, silently wrong for any other.


GAUGE_XY__station_located = (389285.91, 6816518.749)
CELL__station_located = (0, 4, 9)


def _record(station_id: str, *, located: bool) -> PointRecord:
    return PointRecord(
        station_id=station_id,
        variable="discharge",
        source="custom",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame(
            {"datetime": pd.date_range("2015-01-01", periods=2), "value": [1.0, 2.0]}
        ),
        date_start=pd.Timestamp("2015-01-01").to_pydatetime(),
        date_end=pd.Timestamp("2015-01-02").to_pydatetime(),
        location=(
            StationLocation(
                id=station_id,
                x=GAUGE_XY__station_located[0],
                y=GAUGE_XY__station_located[1],
                crs="EPSG:2154",
            )
            if located
            else None
        ),
    )


@pytest.fixture
def ctx__station_located(monkeypatch):
    seen: dict[str, tuple[float, float]] = {}

    def _find(_ctx, x, y):
        seen["xy"] = (float(x), float(y))
        return CELL__station_located

    monkeypatch.setattr(_solver_extract, "find_cell_at_point", _find)
    return seen


def _ctx_with(record: PointRecord, *, geographic: SimpleNamespace | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        loaded_data=SimpleNamespace(
            hydrometry=SimpleNamespace(points=[record]),
            piezometry=SimpleNamespace(points=[record]),
        ),
        setup=SimpleNamespace(geographic=geographic),
    )


def test_a_piezometer_is_located_at_the_coordinates_its_record_carries(
    ctx__station_located,
) -> None:
    cell = cell_for_station(_ctx_with(_record("P1", located=True)), "P1", variable="head")
    assert cell == CELL__station_located
    assert ctx__station_located["xy"] == pytest.approx(GAUGE_XY__station_located)


def test_a_gauge_is_not_located_by_a_coordinate_at_all(ctx__station_located) -> None:
    # A head is read at the cell the point falls in; a discharge is the flow
    # accumulated over everything draining to it, and the cell a coordinate lands
    # in was measured on Nancon to drain two tenths of a per cent of the basin.
    assert (
        cell_for_station(_ctx_with(_record("NANCON", located=True)), "NANCON", variable="discharge")
        is None
    )
    assert "xy" not in ctx__station_located


def test_a_record_with_no_location_resolves_to_nothing(ctx__station_located) -> None:
    # Refusing to guess is the point: the caller then says so instead of
    # substituting a different quantity without a word.
    assert cell_for_station(_ctx_with(_record("P1", located=False)), "P1", variable="head") is None


def test_the_batch_resolver_uses_the_same_lookup(ctx__station_located) -> None:
    cells = resolve_station_cells(
        _ctx_with(_record("P1", located=True)),
        [ObservedSeries(station_id="P1", variable="head", series=pd.Series(dtype=float))],
        variable="head",
    )
    assert cells == {"P1": CELL__station_located}


def test_an_unknown_station_resolves_to_nothing(ctx__station_located) -> None:
    assert (
        cell_for_station(_ctx_with(_record("OTHER", located=True)), "P1", variable="head") is None
    )


# From test_lake_level_calibration.py
# Tests for the lake-level (LAK stage) calibration target.
#
# Covers the encapsulated feature added to calibrate a MODFLOW 6 LAK lake stage:
#
# - schema: the ``lake`` output support variant and its discrimination,
# - extractor: ``extract_lake_series`` reading the LAK obs CSV + JSON sidecar,
# - bridge: ``extract_lake`` and the ``lake_id`` threading guard,
# - observations: ``load_observed`` mapping ``lake_level`` to the ``lake_levels``
#   data family,
# - single-metric path: the ``variable="lake_level"`` metric extractor,
#   time-aligned. This is the standard TOML route taken when no
#   ``objective_blocks`` are declared.


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class TestSchema:
    def test_lake_output_discriminates_on_support(self):
        out = validate_calib_output(
            {"support": "lake", "lake_id": "lac0", "observed_values": [1.0, 2.0]}
        )
        assert isinstance(out, CalibOutputLake)
        assert out.lake_id == "lac0"
        assert out.variable == "stage"
        assert out.time == "all"
        assert out.reducer == "none"

    @pytest.mark.parametrize(
        ("output", "match"),
        [
            pytest.param({"support": "lake"}, "lake_id", id="no-lake-id"),
            pytest.param(
                {"support": "lake", "lake_id": "lac0", "variable": "inflow"},
                "",
                id="unknown-variable",
            ),
        ],
    )
    def test_lake_output_refuses_a_missing_lake_id_and_an_unknown_variable(self, output, match):
        with pytest.raises(ValueError, match=match):
            validate_calib_output(output)

    @pytest.mark.parametrize("quantity", ["stage", "volume", "surface_area"])
    def test_lake_output_accepts_every_lak_state(self, quantity):
        out = validate_calib_output({"support": "lake", "lake_id": "lac0", "variable": quantity})
        assert out.variable == quantity


# ---------------------------------------------------------------------------
# Extractor (LAK obs CSV + sidecar)
# ---------------------------------------------------------------------------
def _write_lake_outputs(
    output_dir: Path,
    model_name: str,
    *,
    lake_id: str = "lac0",
    stages: tuple[float, ...] = (86.97, 87.01, 87.05),
) -> None:
    """Write a minimal LAK obs CSV + JSON sidecar for one lake."""
    obs_csv = f"{model_name}.lak.obs.csv"
    meta = {
        "obs_csv": obs_csv,
        "budgetcsv": None,
        "entries": [
            {"obsname": f"{lake_id}_stage", "lake_id": lake_id, "quantity": "stage"},
            {"obsname": f"{lake_id}_volume", "lake_id": lake_id, "quantity": "volume"},
        ],
    }
    (output_dir / f"{model_name}.lak.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    lines = [f"time,{lake_id}_stage,{lake_id}_volume"]
    for step, stage in enumerate(stages, start=1):
        lines.append(f"{float(step)},{stage},{stage * 1000.0}")
    (output_dir / obs_csv).write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_head_file(output_dir / f"{model_name}.hds", n_periods=len(stages))


def _write_head_file(path: Path, *, n_periods: int) -> None:
    """Write a one-cell MODFLOW 6 head file, one record per period of one day.

    The adapter puts the LAK observations on the stamps the head file holds.
    """
    with path.open("wb") as handle:
        for kper in range(n_periods):
            np.array([1, kper + 1], dtype="<i4").tofile(handle)
            np.array([1.0, float(kper + 1)], dtype="<f8").tofile(handle)
            handle.write(b"HEAD".rjust(16))
            np.array([1, 1, 1], dtype="<i4").tofile(handle)
            np.array([0.0], dtype="<f8").tofile(handle)


_DAYS = [1.0, 2.0, 3.0]


class TestExtractor:
    def test_reads_stage_column_positional(self, tmp_path: Path):
        _write_lake_outputs(tmp_path, "m", stages=(86.97, 87.01, 87.05))
        series = extract_lake_series(tmp_path, "m", lake_id="lac0", times=_DAYS)
        assert list(series.values) == pytest.approx([86.97, 87.01, 87.05])
        assert series.name == "stage"

    def test_applies_time_index_when_length_matches(self, tmp_path: Path):
        _write_lake_outputs(tmp_path, "m", stages=(86.97, 87.01, 87.05))
        idx = pd.DatetimeIndex(["2007-01-01", "2007-01-02", "2007-01-03"])
        series = extract_lake_series(tmp_path, "m", lake_id="lac0", times=_DAYS, time_index=idx)
        assert series.index.equals(idx)
        assert series.loc["2007-01-02"] == pytest.approx(87.01)

    def test_ignores_mismatched_time_index(self, tmp_path: Path):
        _write_lake_outputs(tmp_path, "m", stages=(86.97, 87.01, 87.05))
        idx = pd.DatetimeIndex(["2007-01-01"])
        series = extract_lake_series(tmp_path, "m", lake_id="lac0", times=_DAYS, time_index=idx)
        assert not isinstance(series.index, pd.DatetimeIndex)

    def test_reads_volume_state_quantity(self, tmp_path: Path):
        _write_lake_outputs(tmp_path, "m", stages=(10.0,))
        series = extract_lake_series(tmp_path, "m", lake_id="lac0", times=[1.0], quantity="volume")
        assert list(series.values) == pytest.approx([10000.0])

    @pytest.mark.parametrize(
        ("fields", "error", "match"),
        [
            pytest.param(
                {"lake_id": "other_lake"},
                ObservableNotAvailableError,
                "other_lake",
                id="unknown-lake",
            ),
            pytest.param(
                {"lake_id": "lac0", "quantity": "inflow"},
                NotImplementedError,
                "Lake calibration supports",
                id="unsupported-quantity",
            ),
        ],
    )
    def test_a_lake_or_quantity_the_run_cannot_serve_raises(
        self, tmp_path: Path, fields, error, match
    ):
        _write_lake_outputs(tmp_path, "m")
        with pytest.raises(error, match=match):
            extract_lake_series(tmp_path, "m", times=_DAYS, **fields)

    def test_missing_sidecar_raises(self, tmp_path: Path):
        with pytest.raises(ObservableNotAvailableError, match="sidecar"):
            extract_lake_series(tmp_path, "m", lake_id="lac0", times=_DAYS)


# ---------------------------------------------------------------------------
# Adapter branch
# ---------------------------------------------------------------------------
class TestAdapterBranch:
    def _solver_run(self, tmp_path: Path):
        return solved_run(
            tmp_path, solver_model=SimpleNamespace(model_output_name="m", solver_mesh=None)
        )

    def test_lake_request_needs_a_lake_key(self):
        # The contract refuses a lake request with no lake, so the adapter is
        # never reached with an unusable request.
        with pytest.raises(ValueError, match="needs a key"):
            ObservableRequest(id="l", name="stage", support="lake")

    def _extract(self, tmp_path: Path, *requests: ObservableRequest):
        _write_lake_outputs(tmp_path, "m", stages=(86.0, 87.0))
        return Modflow6FlowAdapter().observables(self._solver_run(tmp_path), list(requests))

    @pytest.mark.parametrize(
        ("name", "values", "units"),
        [("stage", [86.0, 87.0], "m"), ("volume", [86000.0, 87000.0], "m3")],
        ids=["stage-column", "volume-column"],
    )
    def test_the_request_name_selects_the_lake_state(self, tmp_path: Path, name, values, units):
        request = ObservableRequest(id="l", name=name, support="lake", key="lac0")
        results = self._extract(tmp_path, request)
        assert list(results["l"].values) == pytest.approx(values)
        assert results["l"].units == units

    def test_two_lake_states_come_back_from_one_call(self, tmp_path: Path):
        results = self._extract(
            tmp_path,
            ObservableRequest(id="stage", name="stage", support="lake", key="lac0"),
            ObservableRequest(id="vol", name="volume", support="lake", key="lac0"),
        )
        assert sorted(results) == ["stage", "vol"]
        assert list(results["stage"].values) == pytest.approx([86.0, 87.0])
        assert list(results["vol"].values) == pytest.approx([86000.0, 87000.0])

    def test_unknown_lake_state_is_refused_by_name(self, tmp_path: Path):
        request = ObservableRequest(id="l", name="inflow", support="lake", key="lac0")
        with pytest.raises(ObservableNotAvailableError, match="inflow"):
            self._extract(tmp_path, request)

    def test_last_timestep_only_is_honoured(self, tmp_path: Path):
        request = ObservableRequest(id="l", name="stage", support="lake", key="lac0", times="last")
        results = self._extract(tmp_path, request)
        assert list(results["l"].values) == pytest.approx([87.0])


# ---------------------------------------------------------------------------
# Bridge: extract_lake + lake_id threading guard
# ---------------------------------------------------------------------------
class _LakeAdapter:
    """Stub solver adapter that serves any lake request with a fixed series."""

    def observables(self, ctx, requests, *, time_index=None):
        del ctx, time_index
        return {
            request.id: adapter_result(request.id, np.array([1.0, 2.0, 3.0]), "m")
            for request in requests
        }


class _NoLakeAdapter:
    """Stub adapter that refuses lake observables, as MODFLOW-NWT does."""

    def observables(self, ctx, requests, *, time_index=None):
        del ctx, time_index
        for request in requests:
            if request.support == "lake":
                raise ObservableNotAvailableError(
                    f"this backend does not produce observable {request.name!r} on support "
                    f"{request.support!r}."
                )
        return {}


class TestBridge:
    def test_lake_output_raises_without_flow_run(self):
        ctx = SimpleNamespace(execution=None)
        out = validate_calib_output({"support": "lake", "lake_id": "lac0"})
        with pytest.raises(NotImplementedError, match="No flow solver adapter"):
            _extract_outputs(ctx, {"lake": out})

    def test_lake_output_slices_last(self, monkeypatch):
        run_ctx = SimpleNamespace(run=SimpleNamespace(solver="modflow6"), solver_run=None)
        monkeypatch.setattr(
            _solver_extract_module,
            "resolve_flow_adapter",
            lambda ctx: (_LakeAdapter(), run_ctx),
        )
        out = validate_calib_output(
            {"support": "lake", "lake_id": "lac0", "time": "last", "reducer": "last"}
        )
        extracted = _extract_outputs(SimpleNamespace(), {"lake": out})
        simulated, diagnostics = extracted.values, extracted.diagnostics
        assert simulated == {"lake": [3.0]}
        assert diagnostics == {}

    def test_a_backend_without_lakes_refuses_by_name(self, monkeypatch):
        # The refusal now comes from the backend itself rather than from the
        # caller reading its signature.
        run_ctx = SimpleNamespace(run=SimpleNamespace(solver="modflow_nwt"), solver_run=None)
        monkeypatch.setattr(
            _solver_extract_module,
            "resolve_flow_adapter",
            lambda ctx: (_NoLakeAdapter(), run_ctx),
        )
        out = validate_calib_output({"support": "lake", "lake_id": "lac0"})
        with pytest.raises(ObservableNotAvailableError, match="on support 'lake'"):
            _extract_outputs(SimpleNamespace(), {"lake": out})

    @pytest.mark.parametrize("declared", ["stage", "volume", "surface_area"])
    def test_declared_quantity_reaches_the_adapter(self, monkeypatch, declared):
        """The config quantity is what the adapter is asked for, not a fixed stage."""
        seen: dict[str, str] = {}

        class _Recorder:
            def observables(self, ctx, requests, *, time_index=None):
                del ctx, time_index
                seen["name"] = requests[0].name
                seen["key"] = requests[0].key
                seen["support"] = requests[0].support
                return {requests[0].id: adapter_result(requests[0].id, np.array([1.0]), "m")}

        run_ctx = SimpleNamespace(run=SimpleNamespace(solver="modflow6"), solver_run=None)
        monkeypatch.setattr(
            _solver_extract_module,
            "resolve_flow_adapter",
            lambda ctx: (_Recorder(), run_ctx),
        )
        out = validate_calib_output({"support": "lake", "lake_id": "lac0", "variable": declared})
        _extract_outputs(SimpleNamespace(), {"lake": out})
        # No composed lake_<quantity> string any more: the state is the name and
        # the lake is the key.
        assert seen == {"name": declared, "key": "lac0", "support": "lake"}


# ---------------------------------------------------------------------------
# Observations: load_observed lake_level mapping
# ---------------------------------------------------------------------------
def _lake_levels_ctx(station_id: str = "lac0"):
    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]),
            "value": [10.0, 11.0, 12.0],
        }
    )
    rec = SimpleNamespace(station_id=station_id, variable="lake_level", data=df)
    return SimpleNamespace(
        setup=SimpleNamespace(time_grid=None),
        loaded_data=SimpleNamespace(lake_levels=SimpleNamespace(points=[rec])),
    )


class TestLoadObserved:
    def test_maps_lake_level_to_lake_levels_family(self):
        ctx = _lake_levels_ctx()
        observed = load_observed(ctx, "lake_level")
        assert len(observed) == 1
        assert observed[0].station_id == "lac0"
        assert observed[0].variable == "lake_level"
        assert list(observed[0].series.values) == pytest.approx([10.0, 11.0, 12.0])

    def test_unknown_variable_returns_empty(self):
        ctx = _lake_levels_ctx()
        assert load_observed(ctx, "salinity") == []


# ---------------------------------------------------------------------------
# Single-metric path: variable="lake_level" metric extractor (time-aligned)
# ---------------------------------------------------------------------------
class TestSingleMetricLakeLevelPath:
    def test_metric_fn_scores_time_aligned_stage(self, monkeypatch):
        ctx = _lake_levels_ctx()
        metric_fn = build_metric_extractor(
            "lake_level", "rmse", ctx, outputs=None, objective_blocks=None
        )

        observed_dates = pd.DatetimeIndex(["2020-01-01", "2020-01-02", "2020-01-03"])

        class _AlignedAdapter:
            def observables(self, ctx, requests, *, time_index=None):
                del ctx, time_index
                # Observed is [10, 11, 12]; offset by 0.5 -> rmse == 0.5. A lake
                # stage is the state AT its stamp, so it pairs with the reading
                # taken at that instant, not with the day its stamp closes.
                return {
                    request.id: adapter_result(
                        request.id, np.array([10.5, 11.5, 12.5]), "m", times=observed_dates
                    )
                    for request in requests
                }

        run_ctx = SimpleNamespace(run=SimpleNamespace(solver="modflow6"), solver_run=None)
        monkeypatch.setattr(
            _composite_module,
            "resolve_flow_adapter",
            lambda ctx: (_AlignedAdapter(), run_ctx),
        )

        total, components = metric_fn(ctx, objective="rmse", variable="lake_level")
        assert total == pytest.approx(0.5)
        assert components["rmse@lac0.raw_cost"] == pytest.approx(0.5)


# From test_metrics_decomposition.py
# Smoke tests that lock the metrics sub-package decomposition.
#
# Each sub-module of ``hydromodpy.calibration.metrics`` exposes a focused
# concern. These tests import each sub-module independently and exercise one
# representative entry point so the package layout stays stable. The network
# cost left ``metrics`` for ``observations.network_cost`` and keeps its test here.


def test_observable_scoring_module_exposes_the_block_scorers() -> None:
    assert callable(observable_scoring.ObservableScorer)
    assert callable(observable_scoring.StationBlockScorer)
    assert observable_scoring.sampling_step_days(
        pd.date_range("2020-01-01", periods=3, freq="D")
    ) == pytest.approx(1.0)


def test_series_module_exposes_observed_series_and_helpers() -> None:
    from hydromodpy.calibration.metrics import series

    assert hasattr(series, "ObservedSeries")
    assert callable(series.load_observed)
    assert callable(series.resolve_time_index)
    assert callable(series.add_runoff_to_discharge)


def test_composite_module_exposes_build_metric_extractor() -> None:
    assert callable(composite.build_metric_extractor)


def test_solver_extract_module_exposes_extractors() -> None:
    assert callable(solver_extract.resolve_flow_adapter)
    assert callable(solver_extract.extract_outputs)
    assert callable(solver_extract.observable_request_for_output)
    assert callable(solver_extract.resolve_station_cells)
    assert callable(solver_extract.find_cell_at_point)


# From test_metrics_extractors.py
# Tests for :func:`hydromodpy.calibration.metrics.build_metric_extractor`.
#
# Covers Phase 3 of the calibration integration:
#
# - Without ``outputs`` the single-metric extractor is returned and no
#   composite objective is built. This is the standard TOML route, taken
#   whenever no ``objective_blocks`` are declared.
# - With ``outputs`` and ``objective_blocks`` the extractor routes through
#   :func:`build_objective_from_config` and exposes per-block costs as
#   components.
# - The point / boundary helpers fail loudly when the trial context does
#   not expose a flow run.


def _empty_ctx():
    """Return a minimal context with no flow run and no loaded data."""
    return SimpleNamespace(
        setup=SimpleNamespace(cell_mesh=None, domain=None, time_grid=None),
        loaded_data=SimpleNamespace(piezometry=None, hydrometry=None),
        execution=None,
    )


# ---------------------------------------------------------------------------
# Single-metric path (no objective_blocks declared)
# ---------------------------------------------------------------------------
def _score(observed, simulated, metric: str, *, variable: str = "discharge", **options):
    """Score two series as ``variable`` + ``objective`` does: through one implicit block."""
    scorer = StationBlockScorer(
        variable, metric, [ObservedSeries__metrics_extractors("S", variable, observed)], **options
    )
    answer = ObservableResult("S", simulated.to_numpy(), "-", simulated.index)
    return scorer.score({"S": answer})


class TestSingleMetricPath:
    def test_falls_back_when_no_outputs(self):
        ctx = _empty_ctx()
        metric_fn = build_metric_extractor(
            "head",
            "rmse",
            ctx,
            outputs=None,
            objective_blocks=None,
        )
        with pytest.raises(NotImplementedError, match="No flow solver adapter"):
            metric_fn(ctx, objective="rmse", variable="head")

    def test_falls_back_when_outputs_empty(self):
        ctx = _empty_ctx()
        metric_fn = build_metric_extractor("head", "rmse", ctx, outputs={}, objective_blocks=[])
        with pytest.raises(NotImplementedError, match="No flow solver adapter"):
            metric_fn(ctx, objective="rmse", variable="head")


# ---------------------------------------------------------------------------
# Composite path
# ---------------------------------------------------------------------------
class TestCompositeRouting:
    def _outputs_and_block(self):
        outputs = {
            "head_A": validate_calib_output(
                {
                    "variable": "head",
                    "support": "cell",
                    "row": 0,
                    "col": 0,
                    "observed_values": [1.0, 2.0, 3.0],
                }
            )
        }
        block = objective_block("head_block", "rmse", ["head_A"])
        return outputs, [block]

    def test_routes_through_composite_with_outputs_and_blocks(self):
        outputs, blocks = self._outputs_and_block()
        ctx = _empty_ctx()
        metric_fn = build_metric_extractor(
            None,
            None,
            ctx,
            outputs=outputs,
            objective_blocks=blocks,
        )
        # Extraction is one batch now, so a context with no flow run fails once
        # for the batch rather than once per output.
        with pytest.raises(NotImplementedError, match="No flow solver adapter"):
            metric_fn(ctx)

    def test_composite_total_matches_block_when_simulated_provided(self):
        """When the extractor is replaced with a stub returning known
        simulated values, the composite total must reproduce the block
        cost computed manually.
        """
        outputs, blocks = self._outputs_and_block()
        ctx = _empty_ctx()
        # Patch the cell extractor for this single test by running the
        # composite directly against a known sim mapping.

        cfg_subset = SimpleNamespace(outputs=dict(outputs), objective_blocks=list(blocks))
        obj = build_objective_from_config(cfg_subset)
        result = obj.evaluate({"head_A": [1.5, 2.5, 3.5]})
        # rmse([1,2,3], [1.5,2.5,3.5]) = 0.5
        assert result.total == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class TestHelpers:
    def test_coerce_length_handles_pint(self):
        out = validate_calib_output({"variable": "head", "support": "point", "x": 100.0, "y": 0.0})
        assert _coerce_length_to_m(out.x) == 100.0
        assert _coerce_length_to_m(out.y) == 0.0
        assert _coerce_length_to_m(None) is None

    def test_slice_time_first_last_all(self):
        arr = [1.0, 2.0, 3.0, 4.0]
        assert _slice_time(arr, "all", "none") == [1.0, 2.0, 3.0, 4.0]
        assert _slice_time(arr, "first", "none") == [1.0]
        assert _slice_time(arr, "last", "none") == [4.0]
        assert _slice_time(arr, "all", "mean")[0] == pytest.approx(2.5)
        assert _slice_time(arr, "all", "sum")[0] == pytest.approx(10.0)
        assert _slice_time(arr, "all", "last") == [4.0]

    def test_score_raises_when_series_do_not_overlap(self):
        obs = pd.Series([1.0], index=pd.DatetimeIndex(["2020-01-01"]))
        sim = pd.Series([1.0], index=pd.DatetimeIndex(["2021-01-01"]))
        with pytest.raises(ValueError, match="share no timestamp"):
            _score(obs, sim, "rmse", variable="head")

    def test_extract_outputs_raises_when_no_flow_run(self):
        out = validate_calib_output({"variable": "head", "support": "point", "x": 1.0, "y": 2.0})
        with pytest.raises(NotImplementedError, match="No flow solver adapter"):
            _extract_outputs(_empty_ctx(), {"head_A": out})

    def test_boundary_output_becomes_a_keyed_request(self):
        out = boundary_output()
        request = _request_for_output("q", out, _empty_ctx())
        assert (request.id, request.name, request.support) == ("q", "discharge", "boundary")
        assert request.key == "outlet"

    def test_lake_output_carries_its_quantity_and_lake(self):
        out = validate_calib_output(
            {"variable": "volume", "support": "lake", "lake_id": "lac0", "time": "last"}
        )
        request = _request_for_output("lake", out, _empty_ctx())
        assert (request.name, request.support, request.key) == ("volume", "lake", "lac0")
        assert request.times == "last"

    def test_cell_output_carries_its_cell(self):
        out = validate_calib_output(
            {"variable": "head", "support": "cell", "layer": 2, "row": 0, "col": 1}
        )
        request = _request_for_output("h", out, _empty_ctx())
        assert (request.support, request.cell) == ("cell", (2, 0, 1))

    def test_a_flat_cell_id_is_refused_with_the_keys_to_write(self):
        with pytest.raises(ValidationError, match="cell_id.*row and col.*support = 'point'"):
            validate_calib_output({"variable": "head", "support": "cell", "cell_id": 7})

    def test_extract_outputs_batches_every_declaration_in_one_call(self, monkeypatch):
        seen = {}

        class _Adapter:
            def top_active_layer(self, ctx, row, col):
                del ctx, row, col
                return 0

            def observables(self, ctx, requests, *, time_index=None):
                del ctx, time_index
                seen["n_calls"] = seen.get("n_calls", 0) + 1
                seen["ids"] = [request.id for request in requests]
                return {
                    request.id: adapter_result(request.id, np.array([1.0, 2.0, 3.0]), "m")
                    for request in requests
                }

        run_ctx = SimpleNamespace(run=SimpleNamespace(solver="fake_solver"), solver_run=None)
        monkeypatch.setattr(
            _solver_extract_module,
            "resolve_flow_adapter",
            lambda ctx: (_Adapter(), run_ctx),
        )
        outputs = {
            "lake": validate_calib_output(
                {"variable": "stage", "support": "lake", "lake_id": "lac0", "time": "last"}
            ),
            "cell": validate_calib_output(
                {"variable": "head", "support": "cell", "row": 0, "col": 1}
            ),
        }

        extracted = _extract_outputs(_empty_ctx(), outputs)
        simulated, diagnostics = extracted.values, extracted.diagnostics

        # Two outputs, one adapter call: that is what the batch buys.
        assert seen["n_calls"] == 1
        assert seen["ids"] == ["lake", "cell"]
        assert simulated["lake"] == [3.0]
        assert simulated["cell"] == [1.0, 2.0, 3.0]
        # Only a network output produces diagnostics beside its values.
        assert diagnostics == {}

    def test_extract_outputs_names_the_output_whose_declaration_is_wrong(self, monkeypatch):
        class _Adapter:
            def observables(self, ctx, requests, *, time_index=None):
                raise AssertionError("must not be reached")

        run_ctx = SimpleNamespace(run=SimpleNamespace(solver="fake_solver"), solver_run=None)
        monkeypatch.setattr(
            _solver_extract_module,
            "resolve_flow_adapter",
            lambda ctx: (_Adapter(), run_ctx),
        )
        out = validate_calib_output({"variable": "head", "support": "point", "x": 0.0, "y": 0.0})
        with pytest.raises(RuntimeError, match="Output 'h' extraction failed"):
            _extract_outputs(_empty_ctx(), {"h": out})

    def test_station_cells_uses_structural_metadata_without_mesh(self):
        rec = SimpleNamespace(station_id="P1", cell_ij=(3, 4, 2))
        ctx = SimpleNamespace(
            setup=SimpleNamespace(cell_mesh=None, domain=None),
            loaded_data=SimpleNamespace(piezometry=SimpleNamespace(points=[rec])),
        )
        observed = [
            ObservedSeries__metrics_extractors(
                station_id="P1",
                variable="head",
                series=pd.Series([1.0], index=pd.DatetimeIndex(["2020-01-01"])),
            )
        ]

        assert _resolve_station_cells(ctx, observed) == {"P1": (2, 3, 4)}


# From test_network_output_wiring.py
# A network output, from the TOML declaration down to the scored pair.
#
# The trial context is faked but everything it feeds is real: the mesh comes
# from the V-valley bench, the mapped network is a geometry read off disk and
# projected by the same helper the rest of the package uses, and the criterion is
# the one a calibration runs.


class _Adapter__network_output:
    """Returns the bench pattern as a per-cell release flux."""

    def __init__(self, threshold: float, units: str = "m3 s-1") -> None:
        self.threshold = threshold
        self.units = units
        self.seen: list = []

    def observables(self, ctx, requests, *, time_index=None):
        del ctx, time_index
        self.seen = list(requests)
        bench = build_bench()
        pattern = simulated_network(bench, self.threshold)
        return {
            request.id: adapter_result(request.id, np.where(pattern, 1e-06, 0.0), self.units)
            for request in requests
        }


class TestSchema__network_output:
    def test_a_network_output_has_no_observed_values_at_all(self, stream_file) -> None:
        # The criterion balances two simulated quantities, so there is nothing to
        # fit and the schema says so rather than standing in a pair of zeros.
        out = network_output(stream_file)
        assert not hasattr(out, "observed_values")
        assert out.time == "last"

    def test_writing_observed_values_on_it_is_refused(self, stream_file) -> None:
        with pytest.raises(ValueError):
            network_output(stream_file, observed_values=[0.0, 0.0])

    def test_it_becomes_a_whole_field_request(self, stream_file) -> None:
        request = observable_request_for_output("net", network_output(stream_file), None)
        assert (request.support, request.name, request.times) == ("cells", "release_flux", "last")

    def test_it_declares_no_reducer_at_all(self, stream_file) -> None:
        # Nothing ever read it: extract_outputs branches on support == "network"
        # before slice_time, the only reader of a reducer.
        assert "reducer" not in CalibOutputNetwork.model_fields
        with pytest.raises(ValidationError, match="reducer"):
            network_output(stream_file, reducer="sum")

    def test_a_config_can_declare_the_gap_as_its_metric(self, stream_file) -> None:
        cfg = CalibrationConfig.model_validate(
            {
                "method": "grid",
                "outputs": {"net": network_output(stream_file).model_dump()},
                "objective_blocks": [
                    {"name": "abherve", "metric": "distance_gap", "uses_outputs": ["net"]}
                ],
            }
        )
        assert cfg.objective_blocks[0].metric == "distance_gap"


class TestGeometry:
    def test_the_outlet_is_the_largest_drained_area(self, bench) -> None:
        assert resolve_outlet(bench.metric) == cell_id(N_ROWS - 1, AXIS_COL)

    def test_the_data_diagnostics_are_reported(self, bench) -> None:
        vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
        geometry = build_network_geometry(
            topography=bench.elevation,
            face_node_connectivity=connectivity,
            vertices=vertices,
            observed=observed_network("aligned"),
            cell_area_m2=np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
            mean_recharge_m_s=1e-8,
            tau_specific_ratio=1e-4,
            diagonal_neighbors=True,
        )
        # A network sitting exactly on the talwegs has an alpha of one and
        # nothing unreachable: that is what says the surface was pre-treated.
        assert geometry.alpha_obs_closure == pytest.approx(1.0)
        assert geometry.frac_reachable_obs_raw == pytest.approx(1.0)
        assert geometry.diagnostics["n_outlet_sealed"] == 0.0
        assert geometry.h_obs_m == pytest.approx(CELL_SIZE)
        assert geometry.validity_length().length_m == pytest.approx(2.0 * CELL_SIZE)

    def test_a_declared_accuracy_widens_the_validity_length_only(self, bench) -> None:
        vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
        geometry = build_network_geometry(
            topography=bench.elevation,
            face_node_connectivity=connectivity,
            vertices=vertices,
            observed=observed_network("aligned"),
            cell_area_m2=np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
            mean_recharge_m_s=1e-8,
            tau_specific_ratio=1e-4,
            diagonal_neighbors=True,
            observed_position_accuracy_m=75.0,
        )
        # The error floor comes from the network's own precision, which a finer
        # mesh does not improve. It widens Eq. 4, and r_optim keeps h_obs.
        assert geometry.h_obs_m == pytest.approx(CELL_SIZE)
        validity = geometry.validity_length()
        assert validity.length_m == pytest.approx(150.0)
        assert validity.provenance == "declared_accuracy"

    def test_an_empty_projection_is_refused(self, bench) -> None:
        vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
        with pytest.raises(ValueError, match="projects onto no active cell"):
            build_network_geometry(
                topography=bench.elevation,
                face_node_connectivity=connectivity,
                vertices=vertices,
                observed=np.zeros(N_CELLS, dtype=bool),
                cell_area_m2=np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
                mean_recharge_m_s=1e-8,
                tau_specific_ratio=1e-4,
            )


def _extract(monkeypatch, bench, stream_file, threshold, units="m3 s-1", **overrides):
    """Drive one output through the real extraction, with a faked adapter."""
    adapter = _Adapter__network_output(threshold, units=units)
    run_ctx = make_trial_ctx(bench)
    monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda ctx: (adapter, run_ctx))
    outputs = {"net": network_output(stream_file, **overrides)}
    extracted = extract_outputs(run_ctx, outputs)
    return extracted.values, extracted.diagnostics


class TestEndToEnd:
    def _extract(self, monkeypatch, bench, stream_file, threshold, **overrides):
        return _extract(monkeypatch, bench, stream_file, threshold, **overrides)

    def test_the_output_produces_the_pair_and_its_diagnostics(
        self, monkeypatch, bench, stream_file
    ) -> None:
        simulated, diagnostics = self._extract(monkeypatch, bench, stream_file, 200.0)

        d_so, d_os = simulated["net"]
        assert np.isfinite(d_so) and np.isfinite(d_os)
        # The pair reproduces the residual the bracket reads, always.
        assert d_so - d_os == pytest.approx(diagnostics["net.J_signed"])
        assert diagnostics["net.J"] == pytest.approx(abs(d_so - d_os))

    def test_the_thirty_diagnostics_travel_with_it(self, monkeypatch, bench, stream_file) -> None:
        _, diagnostics = self._extract(monkeypatch, bench, stream_file, 200.0)
        for key in (
            "net.D_so",
            "net.D_os",
            "net.D_optim",
            "net.r_optim",
            "net.n_valid",
            "net.n_excess",
            "net.n_missing",
            "net.frac_unreachable_so",
            "net.beta_sim_continuity",
            "net.zero_fraction_os",
            "net.alpha_obs_closure",
            "net.alpha_obs_closure_catchment",
            "net.frac_obs_outside_catchment",
            "net.frac_reachable_obs_raw",
            "net.h_obs",
            "net.L_cap",
        ):
            assert key in diagnostics, key
            assert isinstance(diagnostics[key], float)

    def test_the_trial_measures_one_cell_of_the_mesh_it_scored(
        self, monkeypatch, bench, stream_file
    ) -> None:
        # The default width of an interval on this criterion, read off the
        # geometry the trial built, so the runner never asks the mesh.
        _, diagnostics = self._extract(monkeypatch, bench, stream_file, 200.0)

        assert diagnostics["net.cell_spacing_m"] == pytest.approx(CELL_SIZE)

    def test_the_residual_changes_sign_across_the_sweep(
        self, monkeypatch, bench, stream_file
    ) -> None:
        low = self._extract(monkeypatch, bench, stream_file, 20.0)[1]["net.J_signed"]
        high = self._extract(monkeypatch, bench, stream_file, 900.0)[1]["net.J_signed"]
        assert low > 0.0 > high

    def test_a_trial_past_the_validity_bound_is_scored_even_in_strict_mode(
        self, monkeypatch, bench, stream_file, caplog
    ) -> None:
        # Eq. 4 is read at the optimum, once, by the runner. A trial on the way
        # to the root is not the result, so it neither raises nor warns.
        simulated, _ = self._extract(
            monkeypatch,
            bench,
            stream_file,
            200.0,
            verdict={"validity_length": "1 mm", "on_invalid": "error"},
        )
        assert np.isfinite(simulated["net"][0])
        assert "r_optim" not in caplog.text

    def test_each_trial_still_records_the_ratio_and_its_verdict(
        self, monkeypatch, bench, stream_file
    ) -> None:
        _, diagnostics = self._extract(
            monkeypatch,
            bench,
            stream_file,
            200.0,
            verdict={"validity_length": "1 mm"},
            map={"drawn_by": "crossing"},
        )
        assert diagnostics["net.D_optim"] > 1e-3
        assert diagnostics["net.r_optim_valid"] == 0.0
        assert diagnostics["net.validity_length_m"] == pytest.approx(1e-3)
        assert diagnostics["net.validity_length_provenance"] == 3.0

    def test_an_auto_trial_publishes_two_cells_and_the_paper_ratio(
        self, monkeypatch, bench, stream_file
    ) -> None:
        _, diagnostics = self._extract(monkeypatch, bench, stream_file, 200.0)
        assert diagnostics["net.validity_length_m"] == pytest.approx(2.0 * CELL_SIZE)
        assert diagnostics["net.validity_length_provenance"] == 0.0
        assert diagnostics["net.r_optim"] == pytest.approx(diagnostics["net.D_optim"] / CELL_SIZE)
        assert diagnostics["net.r_optim_valid"] == float(
            diagnostics["net.D_optim"] <= 2.0 * CELL_SIZE
        )

    def test_the_secondary_diagnostics_travel_beside_the_pair(
        self, monkeypatch, bench, stream_file
    ) -> None:
        _, diagnostics = self._extract(
            monkeypatch,
            bench,
            stream_file,
            200.0,
            map={"drawn_by": "crossing"},
        )
        for key in (
            "net.D_so_over_D_os",
            "net.n_neither",
            "net.overlap_Ea",
            "net.overlap_Sa",
            "net.overlap_Na",
            "net.overlap_E",
            "net.L_sim_m",
            "net.L_obs_m",
        ):
            assert key in diagnostics, key
        assert diagnostics["net.D_so_over_D_os"] == pytest.approx(
            diagnostics["net.D_so"] / diagnostics["net.D_os"]
        )

    def test_a_mesh_with_an_inactive_mask_splits_the_unset_thickness(
        self, monkeypatch, bench, stream_file
    ) -> None:
        _, diagnostics = self._extract(monkeypatch, bench, stream_file, 200.0)
        assert "net.d_sat_dry_fraction" in diagnostics
        assert "net.d_sat_inactive_fraction" in diagnostics
        assert "net.d_sat_unset_fraction" not in diagnostics


class TestTheUnitTheReleaseFieldArrivesIn:
    """The seepage threshold is a recharge in m/s times a cell area.

    It is therefore a volumetric flow in m3/s, and the field it is compared to
    has to be one too. The same array is fed in under four unit strings here,
    so what separates the cases is the declared unit alone.
    """

    def _extract(self, monkeypatch, bench, stream_file, units):
        return _extract(monkeypatch, bench, stream_file, 200.0, units=units)

    @pytest.mark.parametrize("units", ["m3 s-1", "m3/s", "m3.s-1"])
    def test_the_spellings_the_adapters_write_are_accepted(
        self, monkeypatch, bench, stream_file, units
    ) -> None:
        # modflow_common and boussinesq write the CF form, the GR4J extractor
        # the solidus one. Both name the same unit.
        simulated, _ = self._extract(monkeypatch, bench, stream_file, units)
        assert np.isfinite(simulated["net"][0])

    @pytest.mark.parametrize("units", ["L/s", "m3/day"])
    def test_a_flow_in_another_unit_is_refused_by_name(
        self, monkeypatch, bench, stream_file, units
    ) -> None:
        # Dimensionally a flow, numerically off by a constant factor: the
        # simulated network would follow the unit and not the hydrogeology.
        with pytest.raises(ObjectiveError) as excinfo:
            self._extract(monkeypatch, bench, stream_file, units)
        message = str(excinfo.value)
        assert "'net'" in message
        assert repr(units) in message
        assert "m3/s" in message

    @pytest.mark.parametrize("units", ["m", ""])
    def test_a_field_that_is_no_flow_at_all_is_refused_by_name(
        self, monkeypatch, bench, stream_file, units
    ) -> None:
        # 'm' is a head served by mistake; '' is what the GR4J adapter used to
        # declare for every series it produced.
        with pytest.raises(ObjectiveError) as excinfo:
            self._extract(monkeypatch, bench, stream_file, units)
        assert "'net'" in str(excinfo.value)
        assert repr(units) in str(excinfo.value)


class TestTheGuardOnAnUnpairedNetworkOutput:
    """A declared network output that nothing scores is a silent wrong answer.

    The single-metric route reads neither ``map.complete`` nor the
    thresholds, so a configuration slipping through it reports a head/NSE
    number while the user believes the stream network was calibrated on.
    """

    def _config(self, stream_file, **overrides):
        return CalibrationConfig.model_validate(
            {
                "method": "grid",
                "outputs": {"net": network_output(stream_file).model_dump()},
                **overrides,
            }
        )

    def test_a_network_output_with_no_block_at_all_is_refused(self, stream_file) -> None:
        with pytest.raises(ValueError, match="distance_gap"):
            self._config(stream_file)

    def test_the_message_names_the_output(self, stream_file) -> None:
        with pytest.raises(ValueError, match="'net'"):
            self._config(stream_file)

    def test_a_head_block_does_not_pair_it(self, stream_file) -> None:
        with pytest.raises(ValueError, match="distance_mean"):
            self._config(
                stream_file,
                outputs={
                    "net": network_output(stream_file).model_dump(),
                    "piezo": {"support": "point", "x": 0.0, "y": 0.0, "variable": "head"},
                },
                objective_blocks=[{"name": "heads", "metric": "rmse", "uses_outputs": ["piezo"]}],
            )

    def test_a_distance_block_pairs_it(self, stream_file) -> None:
        cfg = self._config(
            stream_file,
            objective_blocks=[{"name": "gap", "metric": "distance_gap", "uses_outputs": ["net"]}],
        )
        assert cfg.objective_blocks[0].metric == "distance_gap"

    def test_the_implicit_block_pairs_it_too(self, stream_file) -> None:
        # (objective, variable) builds the block the composite route needs, so
        # the guard must read the config after that block exists.
        cfg = self._config(stream_file, objective="distance_gap", variable="net")
        assert [block.metric for block in cfg.objective_blocks] == ["distance_gap"]

    def test_a_config_with_no_network_output_is_left_alone(self) -> None:
        # A single-metric phase sub-configuration has zero outputs and zero
        # blocks; there is nothing to guard there.
        cfg = CalibrationConfig.model_validate(
            {"method": "grid", "variable": "discharge", "objective": "nse_log"}
        )
        assert cfg.objective_blocks == []


class TestTheMappedNetworkIsRequired:
    def test_a_network_output_without_a_geometry_is_refused(self) -> None:
        # observations/observed_network.py has no fallback: it raises.
        with pytest.raises(ValueError, match="map"):
            validate_calib_output({"support": "network"})


class TestADeletedFieldIsRefusedInATomlToo:
    """``extra="forbid"`` has to make the deletion visible where users write.

    A field silently accepted and then ignored is worse than one that never
    existed: the run answers, and the answer does not depend on what was
    declared.
    """

    def _config_from_toml(self, stream_file, extra_line: str) -> CalibrationConfig:
        payload = tomllib.loads(
            "method = 'grid'\n"
            "[outputs.net]\n"
            "support = 'network'\n"
            f"map.complete = {str(stream_file)!r}\n"
            f"{extra_line}\n"
            "[[objective_blocks]]\n"
            "name = 'abherve'\n"
            "metric = 'distance_gap'\n"
            "uses_outputs = ['net']\n"
        )
        return CalibrationConfig.model_validate(payload)

    def test_a_toml_declaring_a_reducer_is_refused(self, stream_file) -> None:
        with pytest.raises(ValidationError, match="reducer"):
            self._config_from_toml(stream_file, "reducer = 'sum'")

    def test_the_same_toml_without_it_is_accepted(self, stream_file) -> None:
        # The control: only the deleted key separates the two cases.
        cfg = self._config_from_toml(stream_file, "model.weighting = 'cell'")
        assert cfg.outputs["net"].support == "network"


# From test_network_two_bounds.py
# A network output scored against a minimal and a maximal map, in one state or two bounds.
#
# The trial context is faked and everything it feeds is real: the V-valley mesh,
# mapped networks read off disk and projected by the package, and a transient
# release stack whose head of network moves up and down the valley over the
# year. The components checked here are the contract a root search and the
# figures read.


MINIMAL_FIRST_ROW = 36


@pytest.fixture(scope="module")
def maps(tmp_path_factory):
    directory = tmp_path_factory.mktemp("maps")
    return SimpleNamespace(
        maximal=axis_file(directory, "complete.gpkg", FIRST_OBSERVED_ROW),
        minimal=axis_file(directory, "permanent.gpkg", MINIMAL_FIRST_ROW),
        straying=axis_file(directory, "straying.gpkg", MINIMAL_FIRST_ROW, extra_col=AXIS_COL - 6),
    )


def _extract__network_two(monkeypatch, bench, output, stack, bounds):
    extracted, adapter = run_extraction(monkeypatch, bench, {"net": output}, stack, bounds)
    return extracted.values["net"], extracted.diagnostics, adapter


class TestTheSchema:
    def test_the_extent_table_takes_its_defaults(self, maps) -> None:
        extent = network_output(maps.maximal, model={"extent": {}}).model.extent
        assert (extent.flowing_at_least, extent.dry_at_most) == (None, None)
        assert extent.year_quorum == 0.5
        assert extent.visible_flow == "1 L/s"

    def test_without_it_the_output_reads_one_state(self, maps) -> None:
        output = network_output(maps.maximal)
        assert output.model.extent is None
        assert observable_request_for_output("net", output, None).times == "last"

    def test_with_it_every_timestep_is_requested(self, maps) -> None:
        output = network_output(maps.maximal, model={"extent": {}})
        assert observable_request_for_output("net", output, None).times == "all"

    def test_a_single_state_named_beside_it_is_refused(self, maps) -> None:
        with pytest.raises(ValidationError, match="drop 'time'"):
            network_output(maps.maximal, model={"extent": {}}, time="first")

    def test_an_unreadable_visible_flow_is_refused_at_load(self, maps) -> None:
        with pytest.raises(ValidationError, match="no unit"):
            network_output(maps.maximal, model={"extent": {"visible_flow": "2"}})

    @pytest.mark.parametrize(
        "extent",
        [
            {"flowing_at_least": "0 d"},
            {"dry_at_most": "-1 d"},
            {"year_quorum": 0.0},
        ],
    )
    def test_rules_out_of_range_are_refused_at_load(self, maps, extent) -> None:
        with pytest.raises(ValidationError):
            network_output(maps.maximal, model={"extent": extent})

    def test_a_config_round_trips_through_its_dump(self, maps) -> None:
        output = network_output(
            maps.maximal,
            permanent=maps.minimal,
            calibrate_on={"permanent": 1.0, "complete": 0.0},
            model={"extent": {"visible_flow": "1%"}},
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
        assert cfg.outputs["net"].map.bound_weights.permanent == 1.0


class TestOneState:
    def test_one_map_publishes_the_bound_under_both_names(self, monkeypatch, bench, maps) -> None:
        stack = release_stack(bench, [200.0])
        pair, diagnostics, _ = _extract__network_two(
            monkeypatch, bench, network_output(maps.maximal), stack, None
        )
        assert len(pair) == 2
        assert diagnostics["net.n_bounds_scored"] == 1.0
        assert diagnostics["net.J_signed"] == diagnostics["net.J_signed_maximal"]
        assert "net.J_signed_minimal" not in diagnostics
        assert "net.frac_minimal_outside_maximal" not in diagnostics

    def test_with_both_maps_the_state_is_scored_on_the_permanent_one(
        self, monkeypatch, bench, maps
    ) -> None:
        stack = release_stack(bench, [200.0])
        output = network_output(maps.maximal, permanent=maps.minimal)
        pair, diagnostics, _ = _extract__network_two(monkeypatch, bench, output, stack, None)
        _, alone, _ = _extract__network_two(
            monkeypatch,
            bench,
            network_output(maps.maximal, map={"complete": str(maps.minimal)}),
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

    def test_calibrating_on_the_complete_map_swaps_the_two_roles(
        self, monkeypatch, bench, maps
    ) -> None:
        stack = release_stack(bench, [200.0])
        runs = {
            role: _extract__network_two(
                monkeypatch,
                bench,
                network_output(maps.maximal, permanent=maps.minimal, calibrate_on=role),
                stack,
                None,
            )
            for role in ("permanent", "complete")
        }
        (_, permanent, _), (pair, complete, _) = runs["permanent"], runs["complete"]

        assert complete["net.J_signed"] == pytest.approx(
            permanent["net.J_signed_maximal_validation"]
        )
        assert complete["net.J_signed_maximal"] == complete["net.J_signed"]
        assert complete["net.J_signed_minimal_validation"] == pytest.approx(
            permanent["net.J_signed"]
        )
        assert pair[0] - pair[1] == pytest.approx(complete["net.J_signed"])
        assert "net.J_signed_minimal" not in complete

    def test_a_minimal_map_outside_the_maximal_one_is_scored_on_their_union(
        self, monkeypatch, bench, maps
    ) -> None:
        stack = release_stack(bench, [200.0])
        output = network_output(
            maps.maximal,
            permanent=maps.straying,
            map={"drawn_by": "crossing"},
        )
        _, diagnostics, _ = _extract__network_two(monkeypatch, bench, output, stack, None)
        _, alone, _ = _extract__network_two(
            monkeypatch,
            bench,
            network_output(maps.maximal, map={"drawn_by": "crossing"}),
            stack,
            None,
        )

        assert diagnostics["net.frac_minimal_outside_maximal"] > 0.0
        assert diagnostics["net.n_network_obs_maximal_validation"] > alone["net.n_network_obs"]
        # The cells counted beside the maximal bound are the union it was scored on.
        added = diagnostics["net.n_network_obs_maximal_validation"] - alone["net.n_network_obs"]
        assert (
            diagnostics["net.n_observed_cells_maximal_validation"]
            == alone["net.n_observed_cells"] + added
        )


class TestTwoBounds:
    BOUNDS = monthly_bounds(2001, 3)

    def _run(self, monkeypatch, bench, output, *, thresholds=None):
        thresholds = seasonal_thresholds(3) if thresholds is None else thresholds
        return _extract__network_two(
            monkeypatch,
            bench,
            output,
            release_stack(bench, thresholds),
            self.BOUNDS,
        )

    def test_the_maximal_map_alone_is_one_bound_under_the_usual_names(
        self, monkeypatch, bench, maps
    ) -> None:
        output = network_output(maps.maximal, model={"extent": {"visible_flow": "0 L/s"}})
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
        output = network_output(
            maps.maximal,
            permanent=maps.minimal,
            calibrate_on={"permanent": 0.25, "complete": 0.75},
            model={"extent": {"visible_flow": "0 L/s"}},
        )
        pair, diagnostics, _ = self._run(monkeypatch, bench, output)

        assert diagnostics["net.n_bounds_scored"] == 2.0
        # A single-root search must not silently close on one of the two.
        assert "net.J_signed" not in diagnostics
        assert "net.r_optim" not in diagnostics
        for key in ("J_signed", "J", "D_so", "D_os", "D_optim", "r_optim"):
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
        output = network_output(
            maps.maximal,
            permanent=maps.minimal,
            calibrate_on={"permanent": 0.25, "complete": 0.75},
            model={"extent": {"visible_flow": "0 L/s"}},
        )
        pair, diagnostics, _ = self._run(monkeypatch, bench, output)
        scored = criterion_for("distance_gap").score(pair)
        expected = 0.25 * diagnostics["net.J_minimal"] + 0.75 * diagnostics["net.J_maximal"]
        assert scored.cost == pytest.approx(expected)
        assert scored.signed_residual is None

    def test_a_constant_run_scores_what_one_state_scores(self, monkeypatch, bench, maps) -> None:
        # Every cell flows all year or never: both masks are the state itself.
        constant = np.full(36, 200.0)
        output = network_output(
            maps.maximal,
            permanent=maps.maximal,
            calibrate_on={"permanent": 0.5, "complete": 0.5},
            model={"extent": {"visible_flow": "0 L/s"}},
        )
        _, diagnostics, _ = self._run(monkeypatch, bench, output, thresholds=constant)
        _, state, _ = _extract__network_two(
            monkeypatch,
            bench,
            network_output(maps.maximal),
            release_stack(bench, [200.0]),
            None,
        )

        assert diagnostics["net.J_signed_minimal"] == pytest.approx(state["net.J_signed"])
        assert diagnostics["net.J_signed_maximal"] == pytest.approx(state["net.J_signed"])

    def test_a_visible_flow_shrinks_both_masks(self, monkeypatch, bench, maps) -> None:
        fields = {"permanent": maps.minimal, "calibrate_on": {"permanent": 0.5, "complete": 0.5}}
        _, geometric, _ = self._run(
            monkeypatch,
            bench,
            network_output(maps.maximal, **fields, model={"extent": {"visible_flow": "0 L/s"}}),
        )
        _, visible, _ = self._run(
            monkeypatch,
            bench,
            network_output(maps.maximal, **fields, model={"extent": {"visible_flow": "0.02 L/s"}}),
        )
        for bound in ("minimal", "maximal"):
            assert visible[f"net.n_network_sim_{bound}"] < geometric[f"net.n_network_sim_{bound}"]
        assert visible["net.visible_flow_m3_s"] == pytest.approx(2.0e-5)

    def test_a_steady_run_is_refused(self, monkeypatch, bench, maps) -> None:
        output = network_output(maps.maximal, model={"extent": {}})
        with pytest.raises(ObjectiveError, match="single period"):
            _extract__network_two(monkeypatch, bench, output, release_stack(bench, [200.0]), None)

    def test_a_run_with_no_complete_year_is_refused(self, monkeypatch, bench, maps) -> None:
        bounds = list(pd.date_range("2001-03-01", periods=7, freq="MS"))
        output = network_output(maps.maximal, model={"extent": {}})
        with pytest.raises(ObjectiveError, match="no complete"):
            _extract__network_two(
                monkeypatch,
                bench,
                output,
                release_stack(bench, np.full(6, 50.0)),
                bounds,
            )

    def test_a_rule_longer_than_the_year_is_refused(self, monkeypatch, bench, maps) -> None:
        output = network_output(maps.maximal, model={"extent": {"flowing_at_least": "30 months"}})
        with pytest.raises(ObjectiveError, match="flowing_at_least = '30 months'"):
            self._run(monkeypatch, bench, output)

    @pytest.mark.parametrize(
        ("flowing", "dry", "steps"),
        [
            ("1 month", "1 month", (1, 1)),
            ("45 d", "45 d", (2, 1)),
            ("1 d", "1 d", (1, 0)),
            (None, None, (1, 1)),
        ],
    )
    def test_the_durations_are_counted_in_the_timesteps_of_the_run(
        self, monkeypatch, bench, maps, flowing, dry, steps
    ) -> None:
        output = network_output(
            maps.maximal, model={"extent": {"flowing_at_least": flowing, "dry_at_most": dry}}
        )
        _, diagnostics, _ = self._run(monkeypatch, bench, output)

        assert (
            diagnostics["net.maximal_flowing_steps"],
            diagnostics["net.minimal_dry_steps"],
        ) == steps
        assert diagnostics["net.step_days"] == pytest.approx(30.4375)

    def test_no_rule_counts_one_and_one_on_an_hourly_step_too(
        self, monkeypatch, bench, maps
    ) -> None:
        adapter = StackAdapter(release_stack(bench, seasonal_thresholds(3)))
        ctx = make_trial_ctx(bench, bounds=self.BOUNDS)
        ctx.setup.time_grid.window = SimpleNamespace(step_value=1, step_unit="hour")
        monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, ctx))

        diagnostics = extract_outputs(
            ctx, {"net": network_output(maps.maximal, model={"extent": {}})}
        ).diagnostics

        assert diagnostics["net.maximal_flowing_steps"] == 1
        assert diagnostics["net.minimal_dry_steps"] == 1

    def test_a_run_that_states_no_timestep_is_refused(self, monkeypatch, bench, maps) -> None:
        adapter = StackAdapter(release_stack(bench, seasonal_thresholds(3)))
        ctx = make_trial_ctx(bench, bounds=self.BOUNDS)
        del ctx.setup.time_grid.window
        monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, ctx))

        with pytest.raises(ObjectiveError, match="no time window"):
            extract_outputs(ctx, {"net": network_output(maps.maximal, model={"extent": {}})})

    def test_an_undated_stack_is_refused(self, monkeypatch, bench, maps) -> None:
        output = network_output(maps.maximal, model={"extent": {}})
        with pytest.raises(ObjectiveError, match="carry no date"):
            _extract__network_two(
                monkeypatch,
                bench,
                output,
                release_stack(bench, np.full(24, 50.0)),
                None,
            )


class TestTheMinimalMapFromTheDataLayer:
    def _ctx(self, bench, permanent):
        ctx = make_trial_ctx(bench)
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
        adapter = StackAdapter(release_stack(bench, [200.0]))
        monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, ctx))
        output = network_output(maps.maximal, permanent="data.hydrography")
        from_layer = extract_outputs(ctx, {"net": output}).diagnostics
        _, from_file, _ = _extract__network_two(
            monkeypatch,
            bench,
            network_output(maps.maximal, permanent=maps.minimal),
            release_stack(bench, [200.0]),
            None,
        )
        assert from_layer["net.J_signed"] == pytest.approx(from_file["net.J_signed"])
        assert from_layer["net.observed_network_clipped_minimal"] == 1.0

    def test_a_project_without_them_is_refused_by_name(self, monkeypatch, bench, maps) -> None:
        ctx = self._ctx(bench, None)
        adapter = StackAdapter(release_stack(bench, [200.0]))
        monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, ctx))
        output = network_output(maps.maximal, permanent="data.hydrography")
        with pytest.raises(UnresolvedObservedNetwork, match="map.permanent"):
            extract_outputs(ctx, {"net": output})


def test_the_union_projection_counts_the_cells_and_reaches_of_both_maps() -> None:

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


# From test_the_network_reads_its_saturated_thickness.py
# The saturated thickness a network trial publishes beside its distances.
#
# ``d_sat_m`` is the paper's dsat: the saturated thickness averaged by area over
# the catchment, at the state the network is read from. It never enters the pair
# the criterion scores, and a backend that serves no such field loses it alone.


def _run_ctx__network_reads(*, top, botm, closed=None):
    mesh = SimpleNamespace(top=np.asarray(top, dtype=float), botm=np.asarray(botm, dtype=float))
    model = SimpleNamespace(solver_mesh=mesh)
    if closed is not None:
        model.inactive_mask = np.asarray(closed, dtype=bool)
    return SimpleNamespace(solver_run=SimpleNamespace(solver_model=model))


def _geometry(catchment, areas):
    return SimpleNamespace(
        catchment=np.asarray(catchment, dtype=bool),
        cell_area_m2=np.asarray(areas, dtype=float),
    )


def test_area_weighted_over_the_catchment_at_the_last_state() -> None:
    run_ctx = _run_ctx__network_reads(
        top=[100.0, 100.0, 100.0, 100.0], botm=[[90.0] * 4, [70.0] * 4]
    )
    geometry = _geometry([True, True, False, True], [1.0, 3.0, 50.0, 1.0])
    # Two timesteps: only the last one is read, as the network reads it. The
    # third cell lies outside the catchment and weighs fifty times the others.
    thickness = SimpleNamespace(values=np.array([[0.0] * 4, [10.0, 20.0, 99.0, np.nan]]))

    out = catchment_saturation(run_ctx, geometry, thickness)

    assert out["d_sat_m"] == pytest.approx((10.0 * 1.0 + 20.0 * 3.0) / 4.0)
    assert out["d_sat_unset_fraction"] == pytest.approx(1.0 / 5.0)
    assert out["d_aquifer_m"] == pytest.approx(30.0)
    assert out["d_sat_over_d"] == pytest.approx(17.5 / 30.0)


def test_the_unset_share_splits_into_dry_and_inactive_when_the_mesh_says_which() -> None:
    # MODFLOW writes HDRY on a dry cell and HNOFLO on one it never computed,
    # and both come back NaN. The closed columns of the model are what tell
    # them apart; a lake footprint is one such cell, and it is not a dry state.
    run_ctx = _run_ctx__network_reads(
        top=[100.0] * 4,
        botm=[[90.0] * 4, [70.0] * 4],
        closed=[False, False, True, False],
    )
    geometry = _geometry([True, True, True, True], [1.0, 2.0, 3.0, 4.0])
    thickness = SimpleNamespace(values=np.array([10.0, np.nan, np.nan, 20.0]))

    out = catchment_saturation(run_ctx, geometry, thickness)

    assert out["d_sat_dry_fraction"] == pytest.approx(2.0 / 10.0)
    assert out["d_sat_inactive_fraction"] == pytest.approx(3.0 / 10.0)
    assert "d_sat_unset_fraction" not in out
    assert out["d_sat_m"] == pytest.approx((10.0 * 1.0 + 20.0 * 4.0) / 5.0)


def test_a_mask_on_another_mesh_keeps_the_single_unset_share() -> None:
    run_ctx = _run_ctx__network_reads(top=[100.0] * 2, botm=[[70.0] * 2], closed=[False] * 3)
    thickness = SimpleNamespace(values=np.array([10.0, np.nan]))

    out = catchment_saturation(run_ctx, _geometry([True, True], [1.0, 1.0]), thickness)

    assert out["d_sat_unset_fraction"] == pytest.approx(0.5)
    assert "d_sat_dry_fraction" not in out


def test_nothing_without_a_saturated_thickness() -> None:
    run_ctx = _run_ctx__network_reads(top=[100.0], botm=[[70.0]])

    assert catchment_saturation(run_ctx, _geometry([True], [1.0]), None) == {}


def test_a_field_on_another_mesh_warns_and_leaves_the_trial_scored(caplog) -> None:
    run_ctx = _run_ctx__network_reads(top=[100.0, 100.0], botm=[[70.0, 70.0]])
    thickness = SimpleNamespace(values=np.array([10.0, 20.0, 30.0]))

    with caplog.at_level(logging.WARNING):
        out = catchment_saturation(run_ctx, _geometry([True, True], [1.0, 1.0]), thickness)

    assert out == {}
    assert "holds 3 cells" in caplog.text


def test_a_backend_without_the_field_keeps_the_criterion() -> None:
    class _Adapter:
        def observables(self, _solver_run, _requests, *, time_index=None):
            raise ObservableNotAvailableError("no saturated thickness here")

    output = SimpleNamespace(time="all")
    run_ctx = SimpleNamespace(solver_run=object())

    assert _saturated_thickness_or_none(_Adapter(), run_ctx, "network", output, None) is None


def test_the_request_reads_the_same_times_as_the_network() -> None:
    seen = []

    solver_run = object()

    class _Adapter:
        def observables(self, run, requests, *, time_index=None):
            assert run is solver_run
            seen.extend(requests)
            return {requests[0].id: "field"}

    output = SimpleNamespace(time="last")
    run_ctx = SimpleNamespace(solver_run=solver_run)

    assert _saturated_thickness_or_none(_Adapter(), run_ctx, "network", output, None) == "field"
    assert seen[0].name == "saturated_thickness"
    assert seen[0].support == "cells"
    assert seen[0].times == "last"


# From test_the_two_bound_mode_scores_the_years_of_its_window.py
# The two-bound mode scores only the complete years the phase's scoring window holds.
#
# A transient run that starts with a spin-up year scores it like the others
# unless a window leaves it out. The trial context is faked and everything it
# feeds is real: the V-valley mesh, a mapped network read off disk, and a
# monthly release stack whose head of network moves over the year.


def _score__two_bound(monkeypatch, bench, stream_file, stack, bounds, window=None):
    output = network_output(stream_file, model={"extent": {"visible_flow": "0 L/s"}})
    extracted, _ = run_extraction(monkeypatch, bench, {"net": output}, stack, bounds, window=window)
    return extracted.diagnostics


def test_without_a_window_the_spin_up_year_is_scored(monkeypatch, bench, stream_file) -> None:
    scored = _score__two_bound(
        monkeypatch,
        bench,
        stream_file,
        release_stack(bench, seasonal_thresholds(3, wet_first_year=True)),
        SPIN_UP_RUN,
    )
    assert scored["net.n_years_scored"] == 3.0
    assert scored["net.year_scored_y2000"] == 1.0
    assert scored["net.n_years_outside_window"] == 0.0


def test_the_window_scores_the_years_it_holds_and_says_so(monkeypatch, bench, stream_file) -> None:
    scored = _score__two_bound(
        monkeypatch,
        bench,
        stream_file,
        release_stack(bench, seasonal_thresholds(3, wet_first_year=True)),
        SPIN_UP_RUN,
        WINDOW,
    )
    assert scored["net.n_years_scored"] == 2.0
    assert (scored["net.first_year_scored"], scored["net.last_year_scored"]) == (2001.0, 2002.0)
    assert scored["net.year_scored_y2000"] == 0.0
    assert scored["net.year_scored_y2001"] == scored["net.year_scored_y2002"] == 1.0
    assert scored["net.n_years_outside_window"] == 1.0
    assert "net.J_signed_maximal_y2000" not in scored
    assert "net.J_signed_maximal_y2001" in scored


def test_a_windowed_run_scores_what_the_run_without_its_spin_up_scores(
    monkeypatch, bench, stream_file
) -> None:
    thresholds = seasonal_thresholds(3, wet_first_year=True)
    windowed = _score__two_bound(
        monkeypatch,
        bench,
        stream_file,
        release_stack(bench, thresholds),
        SPIN_UP_RUN,
        WINDOW,
    )
    trimmed = _score__two_bound(
        monkeypatch,
        bench,
        stream_file,
        release_stack(bench, thresholds[12:]),
        monthly_bounds(2001, 2),
    )
    whole = _score__two_bound(
        monkeypatch,
        bench,
        stream_file,
        release_stack(bench, thresholds),
        SPIN_UP_RUN,
    )
    assert windowed["net.J_signed_maximal"] == pytest.approx(trimmed["net.J_signed_maximal"])
    # Left in, the wet spin-up year is a year of its own the quorum counts.
    assert whole["net.n_years_required"] == 2.0
    assert windowed["net.n_years_required"] == 1.0
    assert whole["net.n_network_sim_maximal_y2000"] > windowed["net.n_network_sim_maximal_y2001"]


def test_a_time_zone_on_the_window_is_read_in_utc(monkeypatch, bench, stream_file) -> None:
    window = (pd.Timestamp("2001-01-01", tz="UTC"), pd.Timestamp("2002-12-31", tz="UTC"))
    scored = _score__two_bound(
        monkeypatch,
        bench,
        stream_file,
        release_stack(bench, seasonal_thresholds(3, wet_first_year=True)),
        SPIN_UP_RUN,
        window,
    )
    assert scored["net.n_years_scored"] == 2.0


def test_a_window_holding_no_whole_year_is_refused_by_name(monkeypatch, bench, stream_file) -> None:
    window = (pd.Timestamp("2001-02-01"), pd.Timestamp("2001-11-30"))
    with pytest.raises(ObjectiveError, match=r"window .* leaves out 2000, 2001, 2002"):
        _score__two_bound(
            monkeypatch,
            bench,
            stream_file,
            release_stack(bench, seasonal_thresholds(3, wet_first_year=True)),
            SPIN_UP_RUN,
            window,
        )


def test_a_window_does_not_touch_one_state(monkeypatch, bench, stream_file) -> None:
    outputs = {"net": network_output(stream_file)}
    stack = release_stack(bench, [200.0])
    plain = run_extraction(monkeypatch, bench, outputs, stack)[0].diagnostics
    windowed = run_extraction(monkeypatch, bench, outputs, stack, window=WINDOW)[0].diagnostics
    assert windowed["net.J_signed"] == plain["net.J_signed"]


# From test_two_nested_gauges_score_at_their_own_cells.py
# Two nested gauges must each be scored on their own cell, not on either's.
#
# The per-cell discharge path of ``observable_request_for_output`` (explicit
# row/col/layer, ``observes`` naming a station, never a call to
# ``cell_for_station``) let two ``CalibOutputCell`` discharge outputs be declared
# side by side, but nothing ever built two of them and checked they stay apart.
# Two ways for that to go wrong silently: a request builder that lets the second
# output's cell fall back to the first's would score both gauges on the same
# reach, and an ``upstream_area`` companion keyed by the wrong output would scale
# one gauge's runoff by the other's catchment. On the numbers here, a downstream
# gauge draining 64 km2 would feed its runoff into a headwater gauge draining
# 15 km2, over four times too much, and the composite objective would still
# return two numbers and call it a calibration.


CELL_DOWN = (0, 2, 10)
CELL_UP = (0, 9, 4)
AREA_DOWN_M2 = 6.4e7
AREA_UP_M2 = 1.5e7
BASEFLOW_DOWN = np.array([1.0, 2.0, 3.0])
BASEFLOW_UP = np.array([10.0, 20.0, 30.0])


class _Adapter__two_nested:
    """Serves each gauge's own discharge and the area its own cell drains."""

    def __init__(self, *, baseflow: dict[str, np.ndarray], areas: dict[str, float]) -> None:
        self.baseflow = baseflow
        self.areas = areas
        self.asked: list[tuple[str, str, tuple[int, int, int] | None]] = []

    def observables(self, _run_ctx, requests, time_index=None):
        out = {}
        for request in requests:
            self.asked.append((request.id, request.name, request.cell))
            if request.name == "upstream_area":
                gauge = request.id.removeprefix("_area:")
                out[request.id] = adapter_result(request.id, np.array([self.areas[gauge]]), "m2")
                continue
            out[request.id] = ObservableResult(
                request_id=request.id,
                values=self.baseflow[request.id].copy(),
                units="m3 s-1",
                times=TIMES,
                includes_runoff=False,
            )
        return out


@pytest.fixture
def wired__two_nested(monkeypatch):
    adapter = _Adapter__two_nested(
        baseflow={"gauge_down": BASEFLOW_DOWN, "gauge_up": BASEFLOW_UP},
        areas={"gauge_down": AREA_DOWN_M2, "gauge_up": AREA_UP_M2},
    )
    monkeypatch.setattr(
        _solver_extract,
        "resolve_flow_adapter",
        lambda _ctx: (adapter, SimpleNamespace(solver_run=None)),
    )
    monkeypatch.setattr(_solver_extract, "resolve_time_index", lambda *_a, **_k: TIMES)

    def _add_runoff(series, _ctx, *, area_m2=None):
        # A stand-in for the real area scaling: distinct areas must produce
        # distinct additions, or a swap between the two gauges would go unseen.
        scale = 0.0 if area_m2 is None else float(area_m2) / 1e6
        return series + scale

    monkeypatch.setattr(_solver_extract, "add_runoff_to_discharge", _add_runoff)

    outputs = {
        "gauge_down": CalibOutputCell.model_validate(
            {
                "variable": "discharge",
                "support": "cell",
                "layer": CELL_DOWN[0],
                "row": CELL_DOWN[1],
                "col": CELL_DOWN[2],
                "observes": "NANCON_DOWN",
            }
        ),
        "gauge_up": CalibOutputCell.model_validate(
            {
                "variable": "discharge",
                "support": "cell",
                "layer": CELL_UP[0],
                "row": CELL_UP[1],
                "col": CELL_UP[2],
                "observes": "NANCON_UP",
            }
        ),
    }
    ctx = SimpleNamespace(setup=SimpleNamespace(geographic=SimpleNamespace(catch_area=120.0)))
    return adapter, outputs, extract_outputs(ctx, outputs)


def test_each_gauge_is_read_at_its_own_cell(wired__two_nested) -> None:
    adapter, _outputs, _extracted = wired__two_nested
    discharge_asked = {req_id: cell for req_id, name, cell in adapter.asked if name == "discharge"}
    assert discharge_asked == {"gauge_down": CELL_DOWN, "gauge_up": CELL_UP}


def test_each_gauge_s_upstream_area_is_asked_at_its_own_cell(wired__two_nested) -> None:
    adapter, _outputs, _extracted = wired__two_nested
    area_asked = {req_id: cell for req_id, name, cell in adapter.asked if name == "upstream_area"}
    assert area_asked == {"_area:gauge_down": CELL_DOWN, "_area:gauge_up": CELL_UP}


def test_each_gauge_s_runoff_is_scaled_by_its_own_area(wired__two_nested) -> None:
    _adapter, _outputs, extracted = wired__two_nested
    assert extracted.series["gauge_down"].to_numpy() == pytest.approx(
        BASEFLOW_DOWN + AREA_DOWN_M2 / 1e6
    )
    assert extracted.series["gauge_up"].to_numpy() == pytest.approx(BASEFLOW_UP + AREA_UP_M2 / 1e6)


def test_the_two_costs_stay_separate_in_the_components(wired__two_nested) -> None:
    _adapter, outputs, extracted = wired__two_nested
    blocks = [
        objective_block("down_block", "rmse", ["gauge_down"]),
        objective_block("up_block", "rmse", ["gauge_up"]),
    ]
    # The downstream gauge's record matches its simulated series exactly; the
    # headwater one is off by a fixed 0.1: two different costs, so a bug that
    # merges the two blocks or swaps their inputs cannot pass both assertions.
    # The records are monthly means stamped at their month start, inside the
    # month each simulated stamp closes.
    months = pd.date_range("2015-01-01", periods=3, freq="MS")
    observed_records = {
        "gauge_down": pd.Series(BASEFLOW_DOWN + AREA_DOWN_M2 / 1e6, index=months),
        "gauge_up": pd.Series(BASEFLOW_UP + AREA_UP_M2 / 1e6 + 0.1, index=months),
    }
    scorer = ObservableScorer(outputs, blocks, observed_records=observed_records)
    _total, components = scorer.score(extracted.observables, diagnostics=extracted.diagnostics)
    assert components["down_block.raw_cost"] == pytest.approx(0.0, abs=1e-9)
    assert components["up_block.raw_cost"] == pytest.approx(0.1)


# --- the lookups and the refusals a run leaves unreached --------------------
def _execution(models, plan) -> SimpleNamespace:
    solver_runs = {run_id: SimpleNamespace(solver_model=model) for run_id, model in models.items()}
    return SimpleNamespace(execution=SimpleNamespace(solver_runs=solver_runs, simulation_plan=plan))


@pytest.mark.parametrize(
    "ctx",
    [
        SimpleNamespace(),
        _execution({}, None),
        _execution({"f": object()}, None),
        _execution(
            {"f": object()},
            SimpleNamespace(runs=[SimpleNamespace(process_type="transport", id="f")]),
        ),
        _execution(
            {"f": object()},
            SimpleNamespace(runs=[SimpleNamespace(process_type="flow", id="f", solver="nowhere")]),
        ),
        _execution(
            {"f": None},
            SimpleNamespace(runs=[SimpleNamespace(process_type="flow", id="f", solver="modflow6")]),
        ),
    ],
    ids=["no_execution", "no_model", "no_plan", "no_flow_run", "unknown_solver", "released_model"],
)
def test_a_trial_with_no_flow_solver_to_ask_resolves_to_nothing(ctx) -> None:
    assert solver_extract.resolve_flow_adapter(ctx) is None


class _Length:
    def __init__(self, metres: float, *, fails: bool = False) -> None:
        self.metres, self.fails = metres, fails

    def to(self, unit: str):
        if self.fails:
            raise ValueError(unit)
        return SimpleNamespace(magnitude=self.metres)

    def __float__(self) -> float:
        return self.metres + 1.0


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (SimpleNamespace(x=_Length(3.0), y=4, geometry=None), (3.0, 4.0)),
        (SimpleNamespace(x=None, y=None, geometry=None), None),
        (
            SimpleNamespace(x=None, y=None, geometry={"type": "Point", "coordinates": [5, 6, 7]}),
            (5.0, 6.0),
        ),
    ],
)
def test_a_point_is_read_from_its_coordinates_or_its_geometry(output, expected) -> None:
    assert solver_extract.point_xy_from_output(output) == expected
    assert _coerce_length_to_m(_Length(2.0, fails=True)) == 3.0


@pytest.mark.parametrize(
    ("geometry", "message"),
    [
        ({"type": "Polygon"}, "must be a GeoJSON Point"),
        ({"type": "Point", "coordinates": [1]}, "two coordinates"),
    ],
)
def test_a_geometry_that_is_not_a_point_is_refused(geometry, message) -> None:
    output = SimpleNamespace(x=None, y=None, geometry=geometry)

    with pytest.raises(ValueError, match=message):
        solver_extract.point_xy_from_output(output)


@pytest.mark.parametrize(
    ("attributes", "expected"),
    [
        ({"cell_ij": (2, 3)}, (0, 2, 3)),
        ({"cell_ij": (2, 3, 1)}, (1, 2, 3)),
        ({"cell_ij": 5}, None),
        ({"cell_ij": (2,)}, None),
        ({"cell": {"k": 1, "i": 2, "j": 3}}, (1, 2, 3)),
        ({"cell": {"i": 2}}, None),
        ({"cell": (4, 5)}, (0, 4, 5)),
        ({"station_cell": (4, 5, 6)}, (4, 5, 6)),
        ({"cell": 7}, None),
        ({"cell": (7,)}, None),
        ({}, None),
    ],
)
def test_a_station_is_placed_on_the_cell_its_record_carries(attributes, expected) -> None:
    ctx = SimpleNamespace(
        loaded_data=SimpleNamespace(
            piezometry=SimpleNamespace(points=[SimpleNamespace(station_id="S", **attributes)])
        )
    )

    assert cell_for_station(ctx, "S", variable="head") == expected
    assert cell_for_station(ctx, "other", variable="head") is None
    assert cell_for_station(ctx, "S", variable="lake_level") is None
    assert resolve_station_cells(ctx, [], variable="lake_level") == {}


@pytest.mark.parametrize(
    ("attributes", "expected"),
    [
        ({"location": SimpleNamespace(x=1, y=2)}, (1.0, 2.0)),
        ({"easting": 3, "northing": 4}, (3.0, 4.0)),
        ({"geometry": SimpleNamespace(x=5, y=6)}, (5.0, 6.0)),
        ({"location": SimpleNamespace(x=None, y=None)}, None),
    ],
)
def test_the_coordinate_of_a_station_is_read_wherever_its_loader_put_it(
    attributes, expected
) -> None:
    ctx = SimpleNamespace(
        loaded_data=SimpleNamespace(
            hydrometry=SimpleNamespace(points=[SimpleNamespace(station_id="S", **attributes)])
        )
    )

    assert solver_extract.station_xy(ctx, "S", variable="discharge") == expected
    assert solver_extract.station_xy(ctx, "other", variable="discharge") is None
    assert solver_extract.station_xy(SimpleNamespace(), "S", variable="discharge") is None


def test_a_cell_is_asked_of_the_solver_only_when_it_can_locate_one(monkeypatch) -> None:
    run_ctx = SimpleNamespace(solver_run=object())
    adapter = SimpleNamespace(locate_cell=lambda run, x, y: (run is run_ctx.solver_run, x, y))
    monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda _ctx: None)
    assert solver_extract.find_cell_at_point(SimpleNamespace(), 1.0, 2.0) is None

    monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, run_ctx))
    assert solver_extract.find_cell_at_point(SimpleNamespace(), 1.0, 2.0) == (True, 1.0, 2.0)

    monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda _ctx: (object(), run_ctx))
    assert solver_extract.find_cell_at_point(SimpleNamespace(), 1.0, 2.0) is None


def test_an_unknown_support_and_a_point_with_no_position_are_refused() -> None:
    declared = {"time": "all", "snap_radius": None, "observes": None, "variable": "head"}

    with pytest.raises(ValueError, match="Unknown calibration output support 'weird'"):
        observable_request_for_output("n", SimpleNamespace(support="weird", **declared), None)
    with pytest.raises(ValueError, match="requires x/y or geometry"):
        point = SimpleNamespace(support="point", x=None, y=None, geometry=None, **declared)
        observable_request_for_output("n", point, None)


@pytest.mark.parametrize(
    ("field", "n_times", "kept"),
    [
        (np.ones(4), 2, None),
        (np.ones((3, 4)), 2, None),
        (np.arange(8.0).reshape(2, 4), 2, [4.0, 5.0, 6.0, 7.0]),
    ],
)
def test_the_thickness_is_read_at_the_state_scored_or_left_out(
    field, n_times, kept, caplog
) -> None:
    thickness = adapter_result("d", field, "m")

    with caplog.at_level(logging.WARNING):
        result = solver_extract._thickness_at("net", thickness, 1, n_times)

    assert (result if result is None else result.values.ravel().tolist()) == kept
    assert ("No d_sat_m for output net" in caplog.text) is (kept is None)


@pytest.mark.parametrize(
    ("times", "bounds", "expected"),
    [
        (None, pd.date_range("2000-01-01", periods=4, tz="Europe/Paris"), "1999-12-31T23"),
        (pd.date_range("2000-01-11", periods=3, freq="10D"), None, "2000-01-01T00"),
    ],
)
def test_the_edges_of_the_timesteps_are_naive_utc_and_dated(times, bounds, expected) -> None:
    result = adapter_result("r", np.ones(3), "m3 s-1", times=times)

    edges = solver_extract._timestep_edges("net", result, 3, bounds)

    assert str(edges[0])[:13] == expected
    assert edges.size == 4
    with pytest.raises(ObjectiveError, match="carry no date"):
        solver_extract._timestep_edges("net", adapter_result("r", np.ones(3), "m"), 3, None)


def test_the_mismatch_of_the_complete_map_is_scored_alone(monkeypatch) -> None:
    maps = SimpleNamespace(maximal=SimpleNamespace(catchment_mismatch=np.float32(0.25)))
    monkeypatch.setattr(solver_extract, "network_maps_from_run", lambda _run_ctx, _output: maps)

    assert solver_extract.scored_catchment_mismatch(None, None) == 0.25


def test_a_gauge_the_solver_cannot_snap_is_refused_by_name(
    adapter__gauge_snaps, monkeypatch
) -> None:
    def no_field(*_args, **_kwargs):
        raise KeyError("upstream_area")

    monkeypatch.setattr(adapter__gauge_snaps, "observables", no_field)

    with pytest.raises(NotImplementedError, match="serves no drained area or cell centres"):
        observable_request_for_output("gauge", _point(snap_radius=120.0), SimpleNamespace())


def test_a_gauge_on_the_talweg_is_not_moved_and_one_the_solver_cannot_place_is_refused(
    adapter__gauge_snaps, monkeypatch, caplog
) -> None:
    on_the_talweg = _point(x=250.0, y=50.0, snap_radius=150.0)
    with caplog.at_level(logging.INFO):
        request = observable_request_for_output("gauge", on_the_talweg, SimpleNamespace())

    assert request.cell == (0, 0, 4 * N + 2)
    assert "already sits on the most accumulated cell within 150 m" in caplog.text

    locate = adapter__gauge_snaps.locate_cell
    located = iter([locate(SimpleNamespace(solver_model=adapter__gauge_snaps.model), *GAUGE_XY)])
    monkeypatch.setattr(adapter__gauge_snaps, "locate_cell", lambda *_args: next(located, None))
    with pytest.raises(NotImplementedError, match="did not locate the snapped cell"):
        observable_request_for_output("gauge", _point(snap_radius=120.0), SimpleNamespace())


def test_a_station_without_a_position_of_its_own_snaps_from_the_output_coordinate(
    adapter__gauge_snaps,
) -> None:
    ctx = SimpleNamespace(
        loaded_data=SimpleNamespace(
            hydrometry=SimpleNamespace(points=[SimpleNamespace(station_id="J0000000")])
        )
    )

    request = observable_request_for_output(
        "gauge", _point(observes="J0000000", snap_radius=120.0), ctx
    )

    assert request.cell == (0, 0, 2 * N + 2)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"radius_m": 0.0}, "radius must be > 0"),
        ({"start_index": 99}, "start cell 99 is outside the 25 cells"),
        ({"accumulation": np.ones(3)}, "25 cell centres and the accumulation 3"),
    ],
)
def test_a_snap_that_cannot_be_computed_is_refused(kwargs, message) -> None:
    call = {
        "centroids": _grid_centres(),
        "accumulation": _grid_accumulation(),
        "x": 140.0,
        "y": 250.0,
        "radius_m": 120.0,
        "start_index": 11,
        **kwargs,
    }

    with pytest.raises(ValueError, match=message):
        snap_to_most_accumulated(**call)


def test_a_model_with_no_base_publishes_no_aquifer_thickness() -> None:
    mesh = SimpleNamespace(botm=None, top=np.array([100.0, 100.0]))
    run_ctx = SimpleNamespace(
        solver_run=SimpleNamespace(solver_model=SimpleNamespace(solver_mesh=mesh))
    )
    thickness = SimpleNamespace(values=np.array([10.0, 20.0]))

    out = catchment_saturation(run_ctx, _geometry([True, True], [1.0, 1.0]), thickness)

    assert out == {"d_sat_m": 15.0, "d_sat_unset_fraction": 0.0}


def test_a_snap_with_no_position_anywhere_is_refused(adapter__gauge_snaps) -> None:
    ctx = SimpleNamespace(
        loaded_data=SimpleNamespace(
            hydrometry=SimpleNamespace(points=[SimpleNamespace(station_id="J0000000")])
        )
    )
    output = CalibOutputPoint.model_validate(
        {"variable": "discharge", "observes": "J0000000", "snap_radius": 120.0}
    )

    with pytest.raises(NotImplementedError, match="no cell could be resolved to snap from"):
        observable_request_for_output("gauge", output, ctx)
