"""Reading of calibration outputs from a flow solver run.

An output is a cell, a point, a gauge (discharge in m3/s), a lake stage (m) or a
stream network. This file checks how each one becomes a solver request, how the
answer is paired with a record, and what the network criterion publishes (cells,
m, m3/s) for one state or for the minimal and maximal bounds of a year.
"""

from __future__ import annotations

import datetime
import json
import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from shapely.geometry import LineString

from hydromodpy.calibration.config_network import CalibOutputNetwork
from hydromodpy.calibration.config_outputs import (
    CalibOutputCell,
    CalibOutputPoint,
    validate_calib_output,
)
from hydromodpy.calibration.criteria.registry import criterion_for
from hydromodpy.calibration.metrics import composite, observable_scoring, solver_extract
from hydromodpy.calibration.metrics.composite import build_metric_extractor
from hydromodpy.calibration.metrics.gauge_snap import GaugeSnapError
from hydromodpy.calibration.metrics.observable_scoring import (
    ObservableScorer,
    StationBlockScorer,
    slice_time,
)
from hydromodpy.calibration.metrics.series import ObservedSeries, load_observed
from hydromodpy.calibration.metrics.solver_extract import (
    catchment_saturation,
    cell_for_station,
    extract_outputs,
    network_state_row,
    observable_request_for_output,
    resolve_station_cells,
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
from hydromodpy.catchment.stream_network.geometry import build_network_geometry
from hydromodpy.core.contracts.observables import ObservableRequest, ObservableResult
from hydromodpy.core.exceptions import ObjectiveError, ObservableNotAvailableError
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.solver.base.cell_lookup import (
    locate_cell_on_solver_mesh,
    top_active_layer_on_solver_mesh,
)
from hydromodpy.solver.boussinesq.adapter import BoussinesqFlowAdapter
from hydromodpy.solver.modflow6.adapter import Modflow6FlowAdapter
from hydromodpy.solver.modflow6.extractors.lake import extract_lake_series
from hydromodpy.solver.modflow_common import observable_extraction
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

# Cell outputs: a column that starts lower is read at its first active layer.
# The v2 vertical contract places a point without a layer in the top active cell
# of its column. The layer is asked of the flow adapter when the request is built.

NROW, NCOL, NLAY = 2, 3, 3


def pinched_mesh() -> SolverMesh:
    # Three layers on 2 x 3 cells. Row 0, col 1 loses layer 0; row 1, col 2 loses two.
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


def wire_adapter(monkeypatch, adapter: object, model: object) -> SimpleNamespace:
    run_ctx = SimpleNamespace(
        run=SimpleNamespace(id="r1"), solver_run=SimpleNamespace(solver_model=model)
    )
    monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, run_ctx))
    return SimpleNamespace()


@pytest.fixture(params=[Modflow6FlowAdapter, ModflowNwtFlowAdapter], ids=["mf6", "nwt"])
def pinched_ctx(request, monkeypatch):
    return wire_adapter(monkeypatch, request.param(), SimpleNamespace(solver_mesh=pinched_mesh()))


def cell_output(**selector: int) -> CalibOutputCell:
    return CalibOutputCell.model_validate({"variable": "head", "support": "cell", **selector})


def test_first_active_layer_read(pinched_ctx):
    request = observable_request_for_output("piezo", cell_output(row=1, col=2), pinched_ctx)
    assert request.cell == (2, 1, 2)


def test_cell_outside_the_grid_is_refused(pinched_ctx):
    with pytest.raises(ValueError, match="'piezo'.*outside the 2 x 3 grid"):
        observable_request_for_output("piezo", cell_output(row=5, col=0), pinched_ctx)


def test_one_layer_solver_reads_layer_0(monkeypatch):
    ctx = wire_adapter(monkeypatch, BoussinesqFlowAdapter(), SimpleNamespace())
    request = observable_request_for_output("piezo", cell_output(row=1, col=2), ctx)
    assert request.cell == (0, 1, 2)


LAYER_REFUSALS = [
    pytest.param(
        Modflow6FlowAdapter(), None, (1, 2), "'piezo' gives no layer.*no grid yet", id="no grid"
    ),
    pytest.param(
        object(),
        SimpleNamespace(solver_mesh=pinched_mesh()),
        (0, 1),
        "'piezo' gives no layer.*Write the layer",
        id="backend cannot answer",
    ),
]


@pytest.mark.parametrize(("adapter", "model", "rowcol", "message"), LAYER_REFUSALS)
def test_layer_refusals(monkeypatch, adapter, model, rowcol, message):
    ctx = wire_adapter(monkeypatch, adapter, model)
    with pytest.raises(NotImplementedError, match=message):
        observable_request_for_output("piezo", cell_output(row=rowcol[0], col=rowcol[1]), ctx)


# Discharge at a gauge. A drain budget is baseflow alone and a gauge measures the
# whole streamflow, so the runoff is added on every route. Measured on a real
# Nancon run: the single-metric route gave a cost of 0.259 and the weighted-block
# route 82.97 on the same simulation, because only one of them added the runoff.

GAUGE_CELL = (0, 7)
AREA_M2 = 6.4e7
TIMES = pd.date_range("2015-01-31", periods=3, freq="ME")
BASEFLOW = np.array([1.0, 2.0, 3.0])  # m3/s
RUNOFF_ADDED = 0.5  # m3/s
CATCHMENT_KM2 = 64.6
BASIN_M2 = 64.77e6


class GaugeAdapter:
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


def descent_basin(rule: str) -> DescentBasin:
    return DescentBasin(
        mask=np.ones(4, dtype=bool),
        outlet=3,
        rule=rule,
        area_m2=BASIN_M2,
        seeded_at_outlet=False,
    )


@pytest.fixture
def gauge_run(monkeypatch):
    """Extract one gauge output. Returns the adapter, the runoff area seen and the result."""

    def run(
        *,
        includes_runoff: bool,
        observes: str | None,
        station_cell=GAUGE_CELL,
        basin: DescentBasin | None = None,
        builds_descent: bool = True,
    ):
        adapter = GaugeAdapter(includes_runoff=includes_runoff)
        model = SimpleNamespace(descent_basin=basin) if builds_descent else SimpleNamespace()
        run_ctx = SimpleNamespace(solver_run=SimpleNamespace(solver_model=model))
        monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, run_ctx))
        monkeypatch.setattr(solver_extract, "find_cell_at_point", lambda *_: GAUGE_CELL)
        monkeypatch.setattr(solver_extract, "cell_for_station", lambda *_a, **_k: station_cell)
        monkeypatch.setattr(solver_extract, "resolve_time_index", lambda *_a, **_k: TIMES)
        seen: dict[str, float | None] = {}

        def add_runoff(series, _ctx, *, area_m2=None):
            seen["area_m2"] = None if area_m2 is None else float(area_m2)
            return series + RUNOFF_ADDED

        monkeypatch.setattr(solver_extract, "add_runoff_to_discharge", add_runoff)
        declaration = {"variable": "discharge", "support": "point", "x": 1.0, "y": 2.0}
        if observes is not None:
            declaration["observes"] = observes
        outputs = {"gauge": CalibOutputPoint.model_validate(declaration)}
        ctx = SimpleNamespace(
            setup=SimpleNamespace(geographic=SimpleNamespace(catch_area=CATCHMENT_KM2))
        )
        return adapter, seen, extract_outputs(ctx, outputs)

    return run


class BareAdapter:
    """Answers each request with what *answer* makes of it, nothing when it returns None."""

    def __init__(self, answer) -> None:
        self.answer = answer

    def observables(self, _run_ctx, requests, time_index=None):
        return {r.id: self.answer(r) for r in requests if self.answer(r) is not None}


def undated_discharge(request) -> ObservableResult:
    return ObservableResult(request_id=request.id, values=BASEFLOW.copy(), units="m3 s-1")


GAUGE_REFUSALS = [
    pytest.param(lambda request: None, "returned no calibration values", id="no values served"),
    pytest.param(undated_discharge, "on a time axis", id="discharge without dates"),
]


@pytest.mark.parametrize(("answer", "message"), GAUGE_REFUSALS)
def test_gauge_extraction_refusals(monkeypatch, answer, message):
    run_ctx = SimpleNamespace(solver_run=SimpleNamespace(solver_model=SimpleNamespace()))
    monkeypatch.setattr(
        solver_extract, "resolve_flow_adapter", lambda _ctx: (BareAdapter(answer), run_ctx)
    )
    monkeypatch.setattr(solver_extract, "cell_for_station", lambda *_a, **_k: GAUGE_CELL)
    monkeypatch.setattr(solver_extract, "resolve_time_index", lambda *_a, **_k: TIMES)
    declaration = {"variable": "discharge", "observes": "NANCON"}

    with pytest.raises(NotImplementedError, match=message):
        extract_outputs(SimpleNamespace(), {"gauge": CalibOutputPoint.model_validate(declaration)})


def test_gauge_baseflow_gets_runoff(gauge_run):
    _adapter, seen, extracted = gauge_run(includes_runoff=False, observes="NANCON")

    assert seen["area_m2"] == pytest.approx(AREA_M2)
    assert extracted.series["gauge"].to_numpy() == pytest.approx(BASEFLOW + RUNOFF_ADDED)
    # The positional values the block scores carry the same correction.
    assert np.asarray(extracted.values["gauge"]) == pytest.approx(BASEFLOW + RUNOFF_ADDED)
    observable = extracted.observables["gauge"]
    assert observable.values == pytest.approx(BASEFLOW + RUNOFF_ADDED)
    assert observable.times.equals(TIMES)
    assert observable.units == "m3 s-1"
    assert observable.includes_runoff is True


def test_routed_discharge_is_left_alone(gauge_run):
    # SFR injected the runoff into the reaches; adding it again counts it twice.
    _adapter, seen, extracted = gauge_run(includes_runoff=True, observes="NANCON")

    assert "area_m2" not in seen
    assert extracted.series["gauge"].to_numpy() == pytest.approx(BASEFLOW)


def test_drained_fraction_published(gauge_run):
    # No universal threshold exists to veto on, so the share is stated beside the
    # cost on every run: a station two cells off the talweg is then visible.
    _adapter, _seen, extracted = gauge_run(includes_runoff=False, observes="NANCON")

    assert extracted.diagnostics["gauge.drained_fraction"] == pytest.approx(
        (AREA_M2 / 1e6) / CATCHMENT_KM2
    )


def test_gauge_without_cell_uses_catchment(gauge_run):
    # A discharge station is not located by its coordinate, so where no loader
    # wrote its cell the series scored is the whole catchment's, which is what an
    # outlet gauge measures.
    adapter, seen, extracted = gauge_run(
        includes_runoff=False, observes="NANCON", station_cell=None
    )

    assert ("discharge", "domain") in adapter.asked
    assert ("upstream_area", "cell") not in adapter.asked
    # The runoff is still owed, and the basin's own forcing needs no area.
    assert seen["area_m2"] is None
    assert extracted.series["gauge"].to_numpy() == pytest.approx(BASEFLOW + RUNOFF_ADDED)
    assert "gauge.drained_fraction" not in extracted.diagnostics


RUNOFF_AREAS = [
    pytest.param(
        {"station_cell": None, "basin": descent_basin("near_point")},
        BASIN_M2,
        id="catchment series scaled by its basin",
    ),
    pytest.param(
        {"station_cell": None, "basin": descent_basin("largest_basin")},
        None,
        id="synthetic domain keeps the old area",
    ),
    pytest.param(
        {"basin": descent_basin("near_point")}, AREA_M2, id="gauge cell keeps its own area"
    ),
]


@pytest.mark.parametrize(("setup", "area_m2"), RUNOFF_AREAS)
def test_area_the_runoff_is_scaled_by(gauge_run, setup, area_m2):
    _adapter, seen, extracted = gauge_run(includes_runoff=False, observes="NANCON", **setup)

    assert seen["area_m2"] == (None if area_m2 is None else pytest.approx(area_m2))
    assert extracted.series["gauge"].to_numpy() == pytest.approx(BASEFLOW + RUNOFF_ADDED)


def test_model_without_a_basin_warns(gauge_run, caplog):
    with caplog.at_level(logging.WARNING):
        _adapter, seen, _extracted = gauge_run(
            includes_runoff=False, observes="NANCON", station_cell=None
        )

    assert seen["area_m2"] is None
    assert (
        "Calibration discharge: the model carries no basin of D, so the runoff is scaled by "
        "the old support 'catch_area' (64.600 km2)." in caplog.text
    )


def test_largest_basin_no_warning(gauge_run, caplog):
    with caplog.at_level(logging.WARNING):
        gauge_run(
            includes_runoff=False,
            observes="NANCON",
            station_cell=None,
            basin=descent_basin("largest_basin"),
        )

    assert "carries no basin of D" not in caplog.text


def test_output_without_record_unchanged(gauge_run):
    # Nothing says the vector typed into the file is what a gauge measures.
    adapter, seen, extracted = gauge_run(includes_runoff=False, observes=None)

    assert "area_m2" not in seen
    assert ("upstream_area", "cell") not in adapter.asked
    assert extracted.series["gauge"].to_numpy() == pytest.approx(BASEFLOW)


# Two nested gauges are each scored on their own cell and their own area.
# On these numbers a downstream gauge draining 64 km2 would feed its runoff into a
# headwater gauge draining 15 km2, over four times too much, if the two were mixed.

CELL_DOWN = (0, 2, 10)
CELL_UP = (0, 9, 4)
AREA_DOWN_M2 = 6.4e7
AREA_UP_M2 = 1.5e7
BASEFLOW_DOWN = np.array([1.0, 2.0, 3.0])  # m3/s
BASEFLOW_UP = np.array([10.0, 20.0, 30.0])  # m3/s


class NestedGaugeAdapter:
    """Serves each gauge's own discharge and the area its own cell drains."""

    def __init__(self, *, baseflow: dict[str, np.ndarray], areas: dict[str, float]) -> None:
        self.baseflow = baseflow
        self.areas = areas

    def observables(self, _run_ctx, requests, time_index=None):
        out = {}
        for request in requests:
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


def nested_gauge_output(cell: tuple[int, int, int], station: str) -> CalibOutputCell:
    layer, row, col = cell
    return CalibOutputCell.model_validate(
        {
            "variable": "discharge",
            "support": "cell",
            "layer": layer,
            "row": row,
            "col": col,
            "observes": station,
        }
    )


@pytest.fixture
def nested_gauges(monkeypatch):
    adapter = NestedGaugeAdapter(
        baseflow={"gauge_down": BASEFLOW_DOWN, "gauge_up": BASEFLOW_UP},
        areas={"gauge_down": AREA_DOWN_M2, "gauge_up": AREA_UP_M2},
    )
    monkeypatch.setattr(
        solver_extract,
        "resolve_flow_adapter",
        lambda _ctx: (adapter, SimpleNamespace(solver_run=None)),
    )
    monkeypatch.setattr(solver_extract, "resolve_time_index", lambda *_a, **_k: TIMES)

    def add_runoff(series, _ctx, *, area_m2=None):
        # Distinct areas give distinct additions, so a swap between gauges shows.
        scale = 0.0 if area_m2 is None else float(area_m2) / 1e6
        return series + scale

    monkeypatch.setattr(solver_extract, "add_runoff_to_discharge", add_runoff)
    outputs = {
        "gauge_down": nested_gauge_output(CELL_DOWN, "NANCON_DOWN"),
        "gauge_up": nested_gauge_output(CELL_UP, "NANCON_UP"),
    }
    ctx = SimpleNamespace(setup=SimpleNamespace(geographic=SimpleNamespace(catch_area=120.0)))
    return outputs, extract_outputs(ctx, outputs)


def test_runoff_uses_own_area(nested_gauges):
    _outputs, extracted = nested_gauges

    series_down = extracted.series["gauge_down"].to_numpy()
    series_up = extracted.series["gauge_up"].to_numpy()
    assert series_down == pytest.approx(BASEFLOW_DOWN + AREA_DOWN_M2 / 1e6)
    assert series_up == pytest.approx(BASEFLOW_UP + AREA_UP_M2 / 1e6)


def test_two_costs_stay_separate(nested_gauges):
    outputs, extracted = nested_gauges
    blocks = [
        objective_block("down_block", "rmse", ["gauge_down"]),
        objective_block("up_block", "rmse", ["gauge_up"]),
    ]
    # The downstream record matches its simulated series exactly and the headwater
    # one is off by 0.1 m3/s, so a merge or a swap of the blocks cannot pass both
    # assertions. Records are monthly means stamped at their month start, inside
    # the month each simulated stamp closes.
    months = pd.date_range("2015-01-01", periods=3, freq="MS")
    observed_records = {
        "gauge_down": pd.Series(BASEFLOW_DOWN + AREA_DOWN_M2 / 1e6, index=months),
        "gauge_up": pd.Series(BASEFLOW_UP + AREA_UP_M2 / 1e6 + 0.1, index=months),
    }
    scorer = ObservableScorer(outputs, blocks, observed_records=observed_records)

    _total, components = scorer.score(extracted.observables, diagnostics=extracted.diagnostics)

    assert components["down_block.raw_cost"] == pytest.approx(0.0, abs=1e-9)
    assert components["up_block.raw_cost"] == pytest.approx(0.1)


# A gauge moves onto the most accumulated cell only when its output asks.
# The grid is the 5 x 5 V-shaped valley of 100 m cells of test_metrics_gauge_snap,
# talweg in column 2. The accumulation is the solver's own: the fake adapter
# serves the upstream_area field through the shared MODFLOW extraction.

N = 5
GAUGE_XY = (140.0, 250.0)  # m


def valley_model() -> SimpleNamespace:
    rows, cols = np.mgrid[0:N, 0:N]
    top = 10.0 * np.abs(cols - 2) + (N - rows) * 1.0 + 5.0
    mesh = solver_mesh_from_structured_arrays(
        nrow=N, ncol=N, top=top, botm=np.full((1, N, N), -10.0), dx=100.0, dy=100.0
    )
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    return SimpleNamespace(solver_mesh=mesh, descent=descent)


class ValleyAdapter:
    """Serves the solver's own drained areas and cell centers, and a flat baseflow."""

    def __init__(self, model: SimpleNamespace) -> None:
        self.model = model
        self.asked: list = []

    def observables(self, _run_ctx, requests, time_index=None):
        self.asked.extend(requests)
        geometry = [r for r in requests if r.name in ("upstream_area", "cell_xy")]
        served, _ = observable_extraction.extract_common_modflow_observables(
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
def valley_adapter(monkeypatch) -> ValleyAdapter:
    model = valley_model()
    fake = ValleyAdapter(model)
    run_ctx = SimpleNamespace(
        solver_run=SimpleNamespace(solver_model=model),
        run=SimpleNamespace(id="flow", solver="modflow6"),
    )
    monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda _ctx: (fake, run_ctx))
    monkeypatch.setattr(solver_extract, "resolve_time_index", lambda *_a, **_k: TIMES)
    monkeypatch.setattr(
        observable_extraction,
        "catchment_cell_mask",
        lambda m: np.ones(m.solver_mesh.n_cells, bool),
    )
    return fake


def discharge_point(**extra) -> CalibOutputPoint:
    return CalibOutputPoint.model_validate(
        {"variable": "discharge", "x": GAUGE_XY[0], "y": GAUGE_XY[1], **extra}
    )


def hydrometry_ctx(*records: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(loaded_data=SimpleNamespace(hydrometry=SimpleNamespace(points=records)))


def test_snap_radius_too_small(valley_adapter):
    with pytest.raises(GaugeSnapError, match="'gauge'.*90.0 m away"):
        observable_request_for_output("gauge", discharge_point(snap_radius=50.0), SimpleNamespace())


def test_cell_output_snaps_from_centre(valley_adapter):
    output = CalibOutputCell.model_validate(
        {"variable": "discharge", "row": 2, "col": 1, "snap_radius": 100.0}
    )

    request = observable_request_for_output("gauge", output, SimpleNamespace())

    assert request.cell == (0, 0, 2 * N + 2)


def test_named_station_snapped(valley_adapter):
    record = SimpleNamespace(
        station_id="J0000000", location=SimpleNamespace(x=GAUGE_XY[0], y=GAUGE_XY[1])
    )
    output = CalibOutputPoint.model_validate(
        {
            "variable": "discharge",
            "observes": "J0000000",
            # Written beside the station and ignored: its record says where it is.
            "x": 450.0,
            "y": 450.0,
            "snap_radius": 120.0,
        }
    )

    request = observable_request_for_output("gauge", output, hydrometry_ctx(record))

    assert request.support == "cell"
    assert request.cell == (0, 0, 2 * N + 2)


def test_gauges_snap_to_own_cell(valley_adapter):
    outputs = {
        "upper": discharge_point(x=160.0, y=350.0, snap_radius=100.0),
        "lower": discharge_point(x=160.0, y=150.0, snap_radius=100.0),
    }

    extract_outputs(SimpleNamespace(), outputs)

    discharge = {r.id: r.cell for r in valley_adapter.asked if r.name == "discharge"}
    areas = {r.id: r.cell for r in valley_adapter.asked if r.name == "upstream_area" and r.cell}
    assert discharge == {"upper": (0, 0, 1 * N + 2), "lower": (0, 0, 3 * N + 2)}
    assert areas == {}  # no 'observes': no runoff scaling asked


def test_shared_snap_cell_warns(valley_adapter, caplog):
    outputs = {
        "a": discharge_point(x=160.0, y=350.0, snap_radius=100.0),
        "b": discharge_point(x=160.0, y=340.0, snap_radius=100.0),
    }

    with caplog.at_level(logging.WARNING):
        extract_outputs(SimpleNamespace(), outputs)

    assert any(
        f"a, b were all snapped onto cell (0, 0, {1 * N + 2})" in record.getMessage()
        for record in caplog.records
    )


def test_solver_without_area_refused(valley_adapter, monkeypatch):
    def no_field(*_args, **_kwargs):
        raise KeyError("upstream_area")

    monkeypatch.setattr(valley_adapter, "observables", no_field)

    with pytest.raises(NotImplementedError, match="serves no drained area or cell centres"):
        observable_request_for_output(
            "gauge", discharge_point(snap_radius=120.0), SimpleNamespace()
        )


def test_snap_on_talweg_and_unplaced(valley_adapter, monkeypatch, caplog):
    on_the_talweg = discharge_point(x=250.0, y=50.0, snap_radius=150.0)
    with caplog.at_level(logging.INFO):
        request = observable_request_for_output("gauge", on_the_talweg, SimpleNamespace())

    assert request.cell == (0, 0, 4 * N + 2)
    assert "already sits on the most accumulated cell within 150 m" in caplog.text

    locate = valley_adapter.locate_cell
    located = iter([locate(SimpleNamespace(solver_model=valley_adapter.model), *GAUGE_XY)])
    monkeypatch.setattr(valley_adapter, "locate_cell", lambda *_args: next(located, None))
    with pytest.raises(NotImplementedError, match="did not locate the snapped cell"):
        observable_request_for_output(
            "gauge", discharge_point(snap_radius=120.0), SimpleNamespace()
        )


def test_named_station_without_a_cell_refused():
    output = CalibOutputPoint.model_validate({"variable": "head", "observes": "P1"})
    ctx = SimpleNamespace(loaded_data=SimpleNamespace())

    with pytest.raises(NotImplementedError, match="'P1', whose cell the project could not resolve"):
        observable_request_for_output("piezometer", output, ctx)


def test_snap_without_solver_refused(monkeypatch):
    monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda _ctx: None)
    output = CalibOutputCell.model_validate(
        {"variable": "discharge", "layer": 0, "row": 2, "col": 1, "snap_radius": 100.0}
    )

    with pytest.raises(NotImplementedError, match="no flow solver adapter is available"):
        observable_request_for_output("gauge", output, SimpleNamespace())


def test_station_without_position_snaps(valley_adapter):
    ctx = hydrometry_ctx(SimpleNamespace(station_id="J0000000"))

    request = observable_request_for_output(
        "gauge", discharge_point(observes="J0000000", snap_radius=120.0), ctx
    )

    assert request.cell == (0, 0, 2 * N + 2)


def test_snap_without_position_refused(valley_adapter):
    ctx = hydrometry_ctx(SimpleNamespace(station_id="J0000000"))
    output = CalibOutputPoint.model_validate(
        {"variable": "discharge", "observes": "J0000000", "snap_radius": 120.0}
    )

    with pytest.raises(NotImplementedError, match="no cell could be resolved to snap from"):
        observable_request_for_output("gauge", output, ctx)


def test_solver_serves_cell_centres():
    served, unserved = observable_extraction.extract_common_modflow_observables(
        Path("."),
        "model",
        valley_model(),
        [
            ObservableRequest(id="all", name="cell_xy", support="cells"),
            ObservableRequest(id="one", name="cell_xy", support="cell", cell=(0, 2, 1)),
        ],
    )

    assert unserved == []
    assert served["all"].values.shape == (N * N, 2)
    assert served["all"].units == "m"
    np.testing.assert_allclose(served["one"].values, served["all"].values[2 * N + 1])


# Declarations of points, cells and snaps.

DECLARATION_REFUSALS = [
    pytest.param(
        CalibOutputPoint,
        {"variable": "head", "support": "point"},
        "requires both 'x' and 'y'",
        id="point without coordinates",
    ),
    pytest.param(
        CalibOutputPoint,
        {"variable": "head", "x": 0.0, "y": 0.0, "snap_radius": 100.0},
        "not a discharge",
        id="snap radius on a head",
    ),
    pytest.param(
        CalibOutputCell,
        {"variable": "discharge", "row": 0, "col": 0, "snap_radius": 0.0},
        r"must be > 0 m",
        id="zero snap radius",
    ),
]


@pytest.mark.parametrize(("model", "declaration", "message"), DECLARATION_REFUSALS)
def test_declaration_refusals(model, declaration, message):
    with pytest.raises((ValidationError, ValueError), match=message):
        model.model_validate(declaration)


# A station's position lives on its record, in `PointRecord.location`.
# On a real Nancon run no station resolved to a cell because that field was never
# read, so every gauge was scored on the whole-catchment discharge.

STATION_XY = (389285.91, 6816518.749)  # m
STATION_CELL = (0, 4, 9)


def point_record(station_id: str, *, located: bool) -> PointRecord:
    location = StationLocation(id=station_id, x=STATION_XY[0], y=STATION_XY[1], crs="EPSG:2154")
    return PointRecord(
        station_id=station_id,
        variable="discharge",
        source="file",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame(
            {"datetime": pd.date_range("2015-01-01", periods=2), "value": [1.0, 2.0]}
        ),
        date_start=pd.Timestamp("2015-01-01").to_pydatetime(),
        date_end=pd.Timestamp("2015-01-02").to_pydatetime(),
        location=location if located else None,
    )


@pytest.fixture
def located_at(monkeypatch):
    seen: dict[str, tuple[float, float]] = {}

    def find(_ctx, x, y):
        seen["xy"] = (float(x), float(y))
        return STATION_CELL

    monkeypatch.setattr(solver_extract, "find_cell_at_point", find)
    return seen


def station_ctx(record: PointRecord) -> SimpleNamespace:
    return SimpleNamespace(
        loaded_data=SimpleNamespace(
            hydrometry=SimpleNamespace(points=[record]),
            piezometry=SimpleNamespace(points=[record]),
        ),
        setup=SimpleNamespace(geographic=None),
    )


def test_piezometer_located_at_its_record_coordinates(located_at):
    cell = cell_for_station(station_ctx(point_record("P1", located=True)), "P1", variable="head")

    assert cell == STATION_CELL
    assert located_at["xy"] == pytest.approx(STATION_XY)


def test_record_without_location(located_at):
    # Refusing to guess is the point: the caller then says so instead of
    # substituting a different quantity without a word.
    ctx = station_ctx(point_record("P1", located=False))

    assert cell_for_station(ctx, "P1", variable="head") is None


def test_batch_resolver_uses_the_same_lookup(located_at):
    series = [ObservedSeries(station_id="P1", variable="head", series=pd.Series(dtype=float))]

    cells = resolve_station_cells(
        station_ctx(point_record("P1", located=True)), series, variable="head"
    )

    assert cells == {"P1": STATION_CELL}


CELL_ATTRIBUTES = [
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
]


@pytest.mark.parametrize(("attributes", "expected"), CELL_ATTRIBUTES)
def test_station_cell_from_record(attributes, expected):
    ctx = SimpleNamespace(
        loaded_data=SimpleNamespace(
            piezometry=SimpleNamespace(points=[SimpleNamespace(station_id="S", **attributes)])
        )
    )

    assert cell_for_station(ctx, "S", variable="head") == expected
    assert cell_for_station(ctx, "other", variable="head") is None
    assert cell_for_station(ctx, "S", variable="lake_level") is None
    assert resolve_station_cells(ctx, [], variable="lake_level") == {}


STATION_COORDINATES = [
    ({"location": SimpleNamespace(x=1, y=2)}, (1.0, 2.0)),
    ({"easting": 3, "northing": 4}, (3.0, 4.0)),
    ({"geometry": SimpleNamespace(x=5, y=6)}, (5.0, 6.0)),
    ({"location": SimpleNamespace(x=None, y=None)}, None),
]


@pytest.mark.parametrize(("attributes", "expected"), STATION_COORDINATES)
def test_station_coordinates(attributes, expected):
    ctx = hydrometry_ctx(SimpleNamespace(station_id="S", **attributes))

    assert solver_extract.station_xy(ctx, "S", variable="discharge") == expected
    assert solver_extract.station_xy(ctx, "other", variable="discharge") is None
    assert solver_extract.station_xy(SimpleNamespace(), "S", variable="discharge") is None


class Length:
    """A quantity that converts to metres, or fails to, and whose float is off by 1."""

    def __init__(self, metres: float, *, fails: bool = False) -> None:
        self.metres, self.fails = metres, fails

    def to(self, unit: str):
        if self.fails:
            raise ValueError(unit)
        return SimpleNamespace(magnitude=self.metres)

    def __float__(self) -> float:
        return self.metres + 1.0


POINT_COORDINATES = [
    pytest.param(SimpleNamespace(x=Length(3.0), y=4, geometry=None), (3.0, 4.0), id="quantity"),
    pytest.param(SimpleNamespace(x=None, y=None, geometry=None), None, id="none"),
    pytest.param(
        SimpleNamespace(x=None, y=None, geometry={"type": "Point", "coordinates": [5, 6, 7]}),
        (5.0, 6.0),
        id="geojson point",
    ),
]


@pytest.mark.parametrize(("output", "expected"), POINT_COORDINATES)
def test_point_read_from_coordinates_or_geometry(output, expected):
    assert solver_extract.point_xy_from_output(output) == expected
    assert solver_extract._coerce_length_to_m(Length(2.0, fails=True)) == 3.0


GEOMETRY_REFUSALS = [
    ({"type": "Polygon"}, "must be a GeoJSON Point"),
    ({"type": "Point", "coordinates": [1]}, "two coordinates"),
]


@pytest.mark.parametrize(("geometry", "message"), GEOMETRY_REFUSALS)
def test_non_point_geometry_refused(geometry, message):
    output = SimpleNamespace(x=None, y=None, geometry=geometry)

    with pytest.raises(ValueError, match=message):
        solver_extract.point_xy_from_output(output)


def test_support_and_position_refusals():
    declared = {"time": "all", "snap_radius": None, "observes": None, "variable": "head"}

    with pytest.raises(ValueError, match="Unknown calibration output support 'weird'"):
        observable_request_for_output("n", SimpleNamespace(support="weird", **declared), None)
    with pytest.raises(ValueError, match="requires x/y or geometry"):
        point = SimpleNamespace(support="point", x=None, y=None, geometry=None, **declared)
        observable_request_for_output("n", point, None)


def execution_ctx(models, plan) -> SimpleNamespace:
    solver_runs = {run_id: SimpleNamespace(solver_model=model) for run_id, model in models.items()}
    return SimpleNamespace(execution=SimpleNamespace(solver_runs=solver_runs, simulation_plan=plan))


def flow_plan(**run) -> SimpleNamespace:
    return SimpleNamespace(runs=[SimpleNamespace(id="f", **run)])


NO_FLOW_SOLVER = [
    pytest.param(SimpleNamespace(), id="no execution"),
    pytest.param(execution_ctx({}, None), id="no model"),
    pytest.param(execution_ctx({"f": object()}, None), id="no plan"),
    pytest.param(
        execution_ctx({"f": object()}, flow_plan(process_type="transport")), id="no flow run"
    ),
    pytest.param(
        execution_ctx({"f": object()}, flow_plan(process_type="flow", solver="nowhere")),
        id="unknown solver",
    ),
    pytest.param(
        execution_ctx({"f": None}, flow_plan(process_type="flow", solver="modflow6")),
        id="released model",
    ),
]


@pytest.mark.parametrize("ctx", NO_FLOW_SOLVER)
def test_no_flow_solver(ctx):
    assert solver_extract.resolve_flow_adapter(ctx) is None


def test_find_cell_at_point(monkeypatch):
    run_ctx = SimpleNamespace(solver_run=object())
    adapter = SimpleNamespace(locate_cell=lambda run, x, y: (run is run_ctx.solver_run, x, y))
    monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda _ctx: None)
    assert solver_extract.find_cell_at_point(SimpleNamespace(), 1.0, 2.0) is None

    monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, run_ctx))
    assert solver_extract.find_cell_at_point(SimpleNamespace(), 1.0, 2.0) == (True, 1.0, 2.0)

    monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda _ctx: (object(), run_ctx))
    assert solver_extract.find_cell_at_point(SimpleNamespace(), 1.0, 2.0) is None


# Lake stage (m) and volume (m3) of a MODFLOW 6 LAK lake.
# The solver writes an obs CSV and a JSON sidecar. A head file gives the stamps.


def write_lake_outputs(
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
    write_head_file(output_dir / f"{model_name}.hds", n_periods=len(stages))


def write_head_file(path: Path, *, n_periods: int) -> None:
    """Write a one-cell MODFLOW 6 head file, one record per period of one day."""
    with path.open("wb") as handle:
        for kper in range(n_periods):
            np.array([1, kper + 1], dtype="<i4").tofile(handle)
            np.array([1.0, float(kper + 1)], dtype="<f8").tofile(handle)
            handle.write(b"HEAD".rjust(16))
            np.array([1, 1, 1], dtype="<i4").tofile(handle)
            np.array([0.0], dtype="<f8").tofile(handle)


DAYS = [1.0, 2.0, 3.0]
LAKE_SERIES = [
    pytest.param((86.97, 87.01, 87.05), DAYS, {}, [86.97, 87.01, 87.05], "stage", id="stage"),
    pytest.param((10.0,), [1.0], {"quantity": "volume"}, [10000.0], "volume", id="volume"),
]


@pytest.mark.parametrize(("stages", "times", "kwargs", "expected", "name"), LAKE_SERIES)
def test_lake_series_read_by_column(tmp_path, stages, times, kwargs, expected, name):
    write_lake_outputs(tmp_path, "m", stages=stages)

    series = extract_lake_series(tmp_path, "m", lake_id="lac0", times=times, **kwargs)

    assert list(series.values) == pytest.approx(expected)
    assert series.name == name


def test_lake_series_time_index(tmp_path):
    write_lake_outputs(tmp_path, "m")
    index = pd.DatetimeIndex(["2007-01-01", "2007-01-02", "2007-01-03"])

    series = extract_lake_series(tmp_path, "m", lake_id="lac0", times=DAYS, time_index=index)

    assert series.index.equals(index)
    assert series.loc["2007-01-02"] == pytest.approx(87.01)


LAKE_REFUSALS = [
    pytest.param(
        {"lake_id": "other_lake"}, ObservableNotAvailableError, "other_lake", id="unknown lake"
    ),
    pytest.param(
        {"lake_id": "lac0", "quantity": "inflow"},
        NotImplementedError,
        "Lake calibration supports",
        id="unsupported quantity",
    ),
]


@pytest.mark.parametrize(("fields", "error", "match"), LAKE_REFUSALS)
def test_lake_series_refusals(tmp_path, fields, error, match):
    write_lake_outputs(tmp_path, "m")

    with pytest.raises(error, match=match):
        extract_lake_series(tmp_path, "m", times=DAYS, **fields)


def test_lake_series_needs_sidecar(tmp_path):
    with pytest.raises(ObservableNotAvailableError, match="sidecar"):
        extract_lake_series(tmp_path, "m", lake_id="lac0", times=DAYS)


def lake_observables(tmp_path: Path, *requests: ObservableRequest):
    write_lake_outputs(tmp_path, "m", stages=(86.0, 87.0))
    run = solved_run(
        tmp_path, solver_model=SimpleNamespace(model_output_name="m", solver_mesh=None)
    )
    return Modflow6FlowAdapter().observables(run, list(requests))


def lake_request(name: str, **fields) -> ObservableRequest:
    return ObservableRequest(id=name, name=name, support="lake", key="lac0", **fields)


def test_lake_request_needs_a_lake_key():
    with pytest.raises(ValueError, match="needs a key"):
        ObservableRequest(id="l", name="stage", support="lake")


LAKE_STATES = [
    pytest.param("stage", [86.0, 87.0], "m", id="stage column"),
    pytest.param("volume", [86000.0, 87000.0], "m3", id="volume column"),
]


@pytest.mark.parametrize(("name", "values", "units"), LAKE_STATES)
def test_request_name_selects_the_lake_state(tmp_path, name, values, units):
    results = lake_observables(tmp_path, lake_request(name))

    assert list(results[name].values) == pytest.approx(values)
    assert results[name].units == units


def test_two_lake_states_from_one_call(tmp_path):
    results = lake_observables(tmp_path, lake_request("stage"), lake_request("volume"))

    assert sorted(results) == ["stage", "volume"]
    assert list(results["stage"].values) == pytest.approx([86.0, 87.0])
    assert list(results["volume"].values) == pytest.approx([86000.0, 87000.0])


def test_unknown_lake_state_is_refused(tmp_path):
    with pytest.raises(ObservableNotAvailableError, match="inflow"):
        lake_observables(tmp_path, lake_request("inflow"))


def test_last_timestep_only(tmp_path):
    results = lake_observables(tmp_path, lake_request("stage", times="last"))

    assert list(results["stage"].values) == pytest.approx([87.0])


class FixedLakeAdapter:
    """Serves any lake request with a fixed series."""

    def observables(self, ctx, requests, *, time_index=None):
        return {
            request.id: adapter_result(request.id, np.array([1.0, 2.0, 3.0]), "m")
            for request in requests
        }


class NoLakeAdapter:
    """Refuses lake observables, as MODFLOW-NWT does."""

    def observables(self, ctx, requests, *, time_index=None):
        for request in requests:
            if request.support == "lake":
                raise ObservableNotAvailableError(
                    f"this backend does not produce observable {request.name!r} on support "
                    f"{request.support!r}."
                )
        return {}


def use_adapter(monkeypatch, adapter, solver: str) -> None:
    run_ctx = SimpleNamespace(run=SimpleNamespace(solver=solver), solver_run=None)
    monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda ctx: (adapter, run_ctx))


def test_lake_output_keeps_the_last_step(monkeypatch):
    use_adapter(monkeypatch, FixedLakeAdapter(), "modflow6")
    out = validate_calib_output(
        {"support": "lake", "lake_id": "lac0", "time": "last", "reducer": "last"}
    )

    extracted = extract_outputs(SimpleNamespace(), {"lake": out})

    assert extracted.values == {"lake": [3.0]}
    assert extracted.diagnostics == {}


def test_backend_without_lakes_refuses_by_name(monkeypatch):
    use_adapter(monkeypatch, NoLakeAdapter(), "modflow_nwt")
    out = validate_calib_output({"support": "lake", "lake_id": "lac0"})

    with pytest.raises(ObservableNotAvailableError, match="on support 'lake'"):
        extract_outputs(SimpleNamespace(), {"lake": out})


def lake_levels_ctx(station_id: str = "lac0"):
    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]),
            "value": [10.0, 11.0, 12.0],
        }
    )
    record = SimpleNamespace(station_id=station_id, variable="lake_level", data=df)
    return SimpleNamespace(
        setup=SimpleNamespace(time_grid=None),
        loaded_data=SimpleNamespace(lake_levels=SimpleNamespace(points=[record])),
    )


def test_lake_level_records():
    observed = load_observed(lake_levels_ctx(), "lake_level")

    assert len(observed) == 1
    assert observed[0].station_id == "lac0"
    assert observed[0].variable == "lake_level"
    assert list(observed[0].series.values) == pytest.approx([10.0, 11.0, 12.0])


def test_unknown_variable_loads_nothing():
    assert load_observed(lake_levels_ctx(), "salinity") == []


def test_lake_level_metric(monkeypatch):
    ctx = lake_levels_ctx()
    metric_fn = build_metric_extractor(
        "lake_level", "rmse", ctx, outputs=None, objective_blocks=None
    )
    observed_dates = pd.DatetimeIndex(["2020-01-01", "2020-01-02", "2020-01-03"])

    class AlignedAdapter:
        def observables(self, ctx, requests, *, time_index=None):
            # Observed is [10, 11, 12]; offset by 0.5 m gives an rmse of 0.5. A lake
            # stage is the state AT its stamp, so it pairs with the reading taken
            # at that instant, not with the day its stamp closes.
            return {
                request.id: adapter_result(
                    request.id, np.array([10.5, 11.5, 12.5]), "m", times=observed_dates
                )
                for request in requests
            }

    run_ctx = SimpleNamespace(run=SimpleNamespace(solver="modflow6"), solver_run=None)
    monkeypatch.setattr(composite, "resolve_flow_adapter", lambda ctx: (AlignedAdapter(), run_ctx))

    total, components = metric_fn(ctx, objective="rmse", variable="lake_level")

    assert total == pytest.approx(0.5)
    assert components["rmse@lac0.raw_cost"] == pytest.approx(0.5)


# The sub-modules of `metrics` and the metric extractor they build.


def test_observable_scoring_exposes_the_block_scorers():
    assert callable(observable_scoring.ObservableScorer)
    assert callable(observable_scoring.StationBlockScorer)
    step_days = observable_scoring.sampling_step_days(
        pd.date_range("2020-01-01", periods=3, freq="D")
    )
    assert step_days == pytest.approx(1.0)


def test_series_exposes_observed_series_and_helpers():
    from hydromodpy.calibration.metrics import series

    assert hasattr(series, "ObservedSeries")
    assert callable(series.load_observed)
    assert callable(series.resolve_time_index)
    assert callable(series.add_runoff_to_discharge)


def test_composite_exposes_the_metric_extractor():
    assert callable(composite.build_metric_extractor)


def test_solver_extract_exposes_extractors():
    assert callable(solver_extract.resolve_flow_adapter)
    assert callable(solver_extract.extract_outputs)
    assert callable(solver_extract.observable_request_for_output)
    assert callable(solver_extract.resolve_station_cells)
    assert callable(solver_extract.find_cell_at_point)


def empty_ctx():
    """A context with no flow run and no loaded data."""
    return SimpleNamespace(
        setup=SimpleNamespace(cell_mesh=None, domain=None, time_grid=None),
        loaded_data=SimpleNamespace(piezometry=None, hydrometry=None),
        execution=None,
    )


def head_output_and_block():
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
    return outputs, [objective_block("head_block", "rmse", ["head_A"])]


@pytest.mark.parametrize(
    ("outputs", "blocks"),
    [
        pytest.param(None, None, id="no outputs"),
        pytest.param({}, [], id="empty outputs"),
    ],
)
def test_single_metric_without_a_flow_run(outputs, blocks):
    ctx = empty_ctx()
    metric_fn = build_metric_extractor(
        "head", "rmse", ctx, outputs=outputs, objective_blocks=blocks
    )

    with pytest.raises(NotImplementedError, match="No flow solver adapter"):
        metric_fn(ctx, objective="rmse", variable="head")


def test_composite_route_no_solver():
    outputs, blocks = head_output_and_block()
    ctx = empty_ctx()
    metric_fn = build_metric_extractor(None, None, ctx, outputs=outputs, objective_blocks=blocks)

    # Extraction is one batch, so a context with no flow run fails once for the batch.
    with pytest.raises(NotImplementedError, match="No flow solver adapter"):
        metric_fn(ctx)


def test_composite_total_matches_the_block_cost():
    outputs, blocks = head_output_and_block()
    config = SimpleNamespace(outputs=dict(outputs), objective_blocks=list(blocks))

    result = build_objective_from_config(config).evaluate({"head_A": [1.5, 2.5, 3.5]})

    # rmse([1, 2, 3], [1.5, 2.5, 3.5]) = 0.5
    assert result.total == pytest.approx(0.5)


def test_slice_time_first_last_all():
    values = [1.0, 2.0, 3.0, 4.0]

    assert slice_time(values, "all", "none") == [1.0, 2.0, 3.0, 4.0]
    assert slice_time(values, "first", "none") == [1.0]
    assert slice_time(values, "last", "none") == [4.0]
    assert slice_time(values, "all", "mean")[0] == pytest.approx(2.5)
    assert slice_time(values, "all", "sum")[0] == pytest.approx(10.0)
    assert slice_time(values, "all", "last") == [4.0]


def test_disjoint_series_refused():
    observed = pd.Series([1.0], index=pd.DatetimeIndex(["2020-01-01"]))
    simulated = pd.Series([1.0], index=pd.DatetimeIndex(["2021-01-01"]))
    scorer = StationBlockScorer("head", "rmse", [ObservedSeries("S", "head", observed)])
    answer = ObservableResult("S", simulated.to_numpy(), "-", simulated.index)

    with pytest.raises(ValueError, match="share no timestamp"):
        scorer.score({"S": answer})


def test_wrong_declaration_named(monkeypatch):
    class UnreachedAdapter:
        def observables(self, ctx, requests, *, time_index=None):
            raise AssertionError("must not be reached")

    use_adapter(monkeypatch, UnreachedAdapter(), "fake_solver")
    out = validate_calib_output({"variable": "head", "support": "point", "x": 0.0, "y": 0.0})

    with pytest.raises(RuntimeError, match="Output 'h' extraction failed"):
        extract_outputs(empty_ctx(), {"h": out})


# Network output, from the declaration down to the scored pair.
# The trial context is faked. The mesh is the V-valley bench, the mapped network is
# a geometry read off disk, and the criterion is the one a calibration runs.


def geometry_of_bench(bench, observed, **extra):
    vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
    return build_network_geometry(
        topography=bench.elevation,
        face_node_connectivity=connectivity,
        vertices=vertices,
        observed=observed,
        cell_area_m2=np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
        mean_recharge_m_s=1e-8,
        tau_specific_ratio=1e-4,
        **extra,
    )


def test_outlet_is_the_largest_drained_area(bench):
    assert resolve_outlet(bench.metric) == cell_id(N_ROWS - 1, AXIS_COL)


def test_data_diagnostics_are_reported(bench):
    geometry = geometry_of_bench(bench, observed_network("aligned"), diagonal_neighbors=True)

    # A network exactly on the talwegs has an alpha of one and nothing unreachable,
    # which says the surface was pre-treated.
    assert geometry.alpha_obs_closure == pytest.approx(1.0)
    assert geometry.frac_reachable_obs_raw == pytest.approx(1.0)
    assert geometry.diagnostics["n_outlet_sealed"] == 0.0
    assert geometry.h_obs_m == pytest.approx(CELL_SIZE)
    assert geometry.validity_length().length_m == pytest.approx(2.0 * CELL_SIZE)


def test_declared_accuracy_validity_length(bench):
    geometry = geometry_of_bench(
        bench,
        observed_network("aligned"),
        diagonal_neighbors=True,
        observed_position_accuracy_m=75.0,
    )

    # The error floor comes from the network's own precision, which a finer mesh
    # does not improve. It widens Eq. 4, and r_optim keeps h_obs.
    assert geometry.h_obs_m == pytest.approx(CELL_SIZE)
    validity = geometry.validity_length()
    assert validity.length_m == pytest.approx(150.0)
    assert validity.provenance == "declared_accuracy"


def test_empty_projection_is_refused(bench):
    with pytest.raises(ValueError, match="projects onto no active cell"):
        geometry_of_bench(bench, np.zeros(N_CELLS, dtype=bool))


def test_union_projection():
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


# Under `drawn_by = "heads"` no cell is projected from the mapped lines. On the
# V-valley bench the mapped talweg starts on row 12, which drains 169 cells of
# 100 m2. The default 0.02 km2 first holds on row 14, so the scored map is the
# axis from row 14 to the outlet.

LANDING_ROW = 14


def trace_mask() -> np.ndarray:
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[[cell_id(row, AXIS_COL) for row in range(LANDING_ROW, N_ROWS)]] = True
    return mask


def test_heads_output_trace():
    lines = gpd.GeoDataFrame(geometry=[axis_line()], crs=CRS)
    network = SimpleNamespace(vector_path="/fake/streams.gpkg", crs=CRS, read_vector=lambda: lines)
    run_ctx = make_trial_ctx(build_bench(), networks={"reference": network, "generated": None})
    output = validate_calib_output(
        {
            "support": "network",
            "map": {"complete": "data.hydrography", "drawn_by": "heads"},
            "model": {"neighbours": "D8", "seepage_threshold": 0.0},
        }
    )

    maps = network_maps_from_run(run_ctx, output)

    np.testing.assert_array_equal(maps.maximal.observed, trace_mask())
    assert maps.maximal_projection.rasterization == "heads"
    np.testing.assert_array_equal(maps.maximal_projection.mask, trace_mask())
    assert maps.maximal.heads is not None
    assert maps.maximal.heads.indices["n_heads"] == 1.0
    assert maps.maximal.heads.indices["head_snap_p90_m"] == pytest.approx(
        (LANDING_ROW - FIRST_OBSERVED_ROW) * CELL_SIZE
    )


class ReleaseAdapter:
    """Returns the bench pattern as a per-cell release flux (m3/s)."""

    def __init__(self, threshold: float, units: str = "m3 s-1") -> None:
        self.threshold = threshold
        self.units = units

    def observables(self, ctx, requests, *, time_index=None):
        pattern = simulated_network(build_bench(), self.threshold)
        return {
            request.id: adapter_result(request.id, np.where(pattern, 1e-06, 0.0), self.units)
            for request in requests
        }


def extract_network(monkeypatch, bench, stream_file, threshold, units="m3 s-1", **overrides):
    """Drive one network output through the real extraction, with a faked adapter."""
    adapter = ReleaseAdapter(threshold, units=units)
    run_ctx = make_trial_ctx(bench)
    monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda ctx: (adapter, run_ctx))
    outputs = {"net": network_output(stream_file, **overrides)}
    extracted = extract_outputs(run_ctx, outputs)
    return extracted.values, extracted.diagnostics


def test_network_pair_and_diagnostics(monkeypatch, bench, stream_file):
    simulated, diagnostics = extract_network(monkeypatch, bench, stream_file, 200.0)

    d_so, d_os = simulated["net"]
    assert np.isfinite(d_so) and np.isfinite(d_os)
    # The pair reproduces the residual the bracket reads, always.
    assert d_so - d_os == pytest.approx(diagnostics["net.J_signed"])
    assert diagnostics["net.J"] == pytest.approx(abs(d_so - d_os))


def test_cell_spacing_published(monkeypatch, bench, stream_file):
    # The default width of an interval on this criterion, read off the geometry
    # the trial built, so the runner never asks the mesh.
    _, diagnostics = extract_network(monkeypatch, bench, stream_file, 200.0)

    assert diagnostics["net.cell_spacing_m"] == pytest.approx(CELL_SIZE)


def test_residual_changes_sign_across_the_sweep(monkeypatch, bench, stream_file):
    low = extract_network(monkeypatch, bench, stream_file, 20.0)[1]["net.J_signed"]
    high = extract_network(monkeypatch, bench, stream_file, 900.0)[1]["net.J_signed"]

    assert low > 0.0 > high


def test_ratio_and_verdict(monkeypatch, bench, stream_file):
    _, diagnostics = extract_network(
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


def test_auto_validity_length_ratio(monkeypatch, bench, stream_file):
    _, diagnostics = extract_network(monkeypatch, bench, stream_file, 200.0)

    assert diagnostics["net.validity_length_m"] == pytest.approx(2.0 * CELL_SIZE)
    assert diagnostics["net.validity_length_provenance"] == 0.0
    assert diagnostics["net.r_optim"] == pytest.approx(diagnostics["net.D_optim"] / CELL_SIZE)
    assert diagnostics["net.r_optim_valid"] == float(diagnostics["net.D_optim"] <= 2.0 * CELL_SIZE)


SECONDARY_DIAGNOSTICS = [
    "net.D_so_over_D_os",
    "net.n_neither",
    "net.overlap_Ea",
    "net.overlap_Sa",
    "net.overlap_Na",
    "net.overlap_E",
    "net.L_sim_m",
    "net.L_obs_m",
]


def test_secondary_diagnostics_travel_beside_the_pair(monkeypatch, bench, stream_file):
    _, diagnostics = extract_network(
        monkeypatch, bench, stream_file, 200.0, map={"drawn_by": "crossing"}
    )

    for key in SECONDARY_DIAGNOSTICS:
        assert key in diagnostics, key
    assert diagnostics["net.D_so_over_D_os"] == pytest.approx(
        diagnostics["net.D_so"] / diagnostics["net.D_os"]
    )


# The seepage threshold is a recharge in m/s times a cell area, so a volumetric
# flow in m3/s, and the field it is compared to has to be one too.

BAD_RELEASE_UNITS = [
    pytest.param("L/s", id="litres per second"),
    pytest.param("m3/day", id="cubic metres per day"),
    pytest.param("m", id="a head served by mistake"),
    pytest.param("", id="no unit"),
]


@pytest.mark.parametrize("units", BAD_RELEASE_UNITS)
def test_release_units_refused(monkeypatch, bench, stream_file, units):
    with pytest.raises(ObjectiveError) as excinfo:
        extract_network(monkeypatch, bench, stream_file, 200.0, units=units)

    message = str(excinfo.value)
    assert "'net'" in message
    assert repr(units) in message
    assert "m3/s" in message


# Network output in one state: the date it names picks the row scored.
# The criterion is real, the backend serves the whole monthly stack and the
# extraction hands it the one row of that date.

MONTHS = pd.date_range("2000-01-01", periods=37, freq="MS")


def test_toml_date_iso_spelling():
    output = CalibOutputNetwork(map={"complete": "n.gpkg"}, time=datetime.date(2002, 10, 15))

    assert output.time == "2002-10-15"


@pytest.mark.parametrize("time", ["all", ["2002-01-01"], "October"])
def test_multi_state_time_refused(time):
    with pytest.raises(ValidationError, match="network"):
        CalibOutputNetwork(map={"complete": "n.gpkg"}, time=time)


def monthly_stack() -> ObservableResult:
    values = np.arange(36, dtype=float)[:, None] * np.ones((1, 4))
    return adapter_result("net", values, "m3 s-1", times=MONTHS[1:])


def test_stamps_date_the_stack():
    output = CalibOutputNetwork(map={"complete": "n.gpkg"}, time="2001-03-31")

    row, index = network_state_row("net", output, monthly_stack(), None)

    assert index == 14
    assert np.asarray(row.values)[0, 0] == 14.0


def test_undated_stack_refused():
    output = CalibOutputNetwork(map={"complete": "n.gpkg"}, time="2002-10-15")
    undated = adapter_result("net", np.ones((3, 4)), "m3 s-1")

    with pytest.raises(ObjectiveError, match="Output 'net': time = '2002-10-15'"):
        network_state_row("net", output, undated, None)


def score_state(monkeypatch, bench, stream_file, stack, bounds, time):
    outputs = {"net": one_state(stream_file, time)}
    return run_extraction(monkeypatch, bench, outputs, stack, bounds)[0].diagnostics


def test_date_picks_its_month(monkeypatch, bench, stream_file):
    thresholds = seasonal_thresholds(3, wet_first_year=True)
    october = 12 + 9  # October 2001, the 22nd month of the run

    dated = score_state(
        monkeypatch,
        bench,
        stream_file,
        release_stack(bench, thresholds),
        SPIN_UP_RUN,
        "2001-10-15",
    )
    alone = score_state(
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


def test_date_outside_run_refused(monkeypatch, bench, stream_file):
    with pytest.raises(ObjectiveError, match="outside the record"):
        score_state(
            monkeypatch,
            bench,
            stream_file,
            release_stack(bench, seasonal_thresholds(3, wet_first_year=True)),
            SPIN_UP_RUN,
            "2005-06-01",
        )


# Network output scored against a minimal and a maximal map.
# The mesh is the V-valley, the maps are read off disk, and a transient release
# stack moves the head of the network up and down the valley over the year.

MINIMAL_FIRST_ROW = 36


@pytest.fixture(scope="module")
def maps(tmp_path_factory):
    directory = tmp_path_factory.mktemp("maps")
    return SimpleNamespace(
        maximal=axis_file(directory, "complete.gpkg", FIRST_OBSERVED_ROW),
        minimal=axis_file(directory, "permanent.gpkg", MINIMAL_FIRST_ROW),
        straying=axis_file(directory, "straying.gpkg", MINIMAL_FIRST_ROW, extra_col=AXIS_COL - 6),
    )


def run_network(monkeypatch, bench, output, stack, bounds):
    extracted, adapter = run_extraction(monkeypatch, bench, {"net": output}, stack, bounds)
    return extracted.values["net"], extracted.diagnostics, adapter


SCHEMA_REFUSALS = [
    pytest.param(
        {"model": {"extent": {}}, "time": "first"}, "drop 'time'", id="state beside two bounds"
    ),
    pytest.param(
        {"model": {"extent": {"visible_flow": "2"}}}, "no unit", id="visible flow without unit"
    ),
    pytest.param({"model": {"extent": {"flowing_at_least": "0 d"}}}, None, id="zero flowing"),
    pytest.param({"model": {"extent": {"dry_at_most": "-1 d"}}}, None, id="negative dry"),
    pytest.param({"model": {"extent": {"year_quorum": 0.0}}}, None, id="zero quorum"),
]


@pytest.mark.parametrize(("fields", "message"), SCHEMA_REFUSALS)
def test_schema_refusals(maps, fields, message):
    with pytest.raises(ValidationError, match=message):
        network_output(maps.maximal, **fields)


def test_state_on_permanent_map(monkeypatch, bench, maps):
    stack = release_stack(bench, [200.0])
    output = network_output(maps.maximal, permanent=maps.minimal)
    alone_output = network_output(maps.maximal, map={"complete": str(maps.minimal)})

    pair, diagnostics, _ = run_network(monkeypatch, bench, output, stack, None)
    _, alone, _ = run_network(monkeypatch, bench, alone_output, stack, None)

    assert diagnostics["net.J_signed"] == pytest.approx(alone["net.J_signed"])
    assert diagnostics["net.J_signed_minimal"] == diagnostics["net.J_signed"]
    assert pair[0] - pair[1] == pytest.approx(diagnostics["net.J_signed"])
    # The complete map is scored beside the cost, under a name no search reads.
    assert "net.J_signed_maximal" not in diagnostics
    assert "net.J_signed_maximal_validation" in diagnostics
    assert diagnostics["net.J_signed_maximal_validation"] != diagnostics["net.J_signed"]
    assert diagnostics["net.frac_minimal_outside_maximal"] == 0.0


def test_calibrate_on_complete_map(monkeypatch, bench, maps):
    stack = release_stack(bench, [200.0])
    runs = {
        role: run_network(
            monkeypatch,
            bench,
            network_output(maps.maximal, permanent=maps.minimal, calibrate_on=role),
            stack,
            None,
        )
        for role in ("permanent", "complete")
    }
    (_, permanent, _), (pair, complete, _) = runs["permanent"], runs["complete"]

    assert complete["net.J_signed"] == pytest.approx(permanent["net.J_signed_maximal_validation"])
    assert complete["net.J_signed_maximal"] == complete["net.J_signed"]
    assert complete["net.J_signed_minimal_validation"] == pytest.approx(permanent["net.J_signed"])
    assert pair[0] - pair[1] == pytest.approx(complete["net.J_signed"])
    assert "net.J_signed_minimal" not in complete


def test_minimal_outside_maximal_union(monkeypatch, bench, maps):
    stack = release_stack(bench, [200.0])
    output = network_output(maps.maximal, permanent=maps.straying, map={"drawn_by": "crossing"})
    alone_output = network_output(maps.maximal, map={"drawn_by": "crossing"})

    _, diagnostics, _ = run_network(monkeypatch, bench, output, stack, None)
    _, alone, _ = run_network(monkeypatch, bench, alone_output, stack, None)

    assert diagnostics["net.frac_minimal_outside_maximal"] > 0.0
    assert diagnostics["net.n_network_obs_maximal_validation"] > alone["net.n_network_obs"]
    # The cells counted beside the maximal bound are the union it was scored on.
    added = diagnostics["net.n_network_obs_maximal_validation"] - alone["net.n_network_obs"]
    assert (
        diagnostics["net.n_observed_cells_maximal_validation"]
        == alone["net.n_observed_cells"] + added
    )


BOUNDS = monthly_bounds(2001, 3)
NO_VISIBLE_FLOW = {"visible_flow": "0 L/s"}
HALF_AND_HALF = {"permanent": 0.5, "complete": 0.5}


def run_year(monkeypatch, bench, output, *, thresholds=None):
    thresholds = seasonal_thresholds(3) if thresholds is None else thresholds
    return run_network(monkeypatch, bench, output, release_stack(bench, thresholds), BOUNDS)


def test_maximal_map_alone_is_one_bound(monkeypatch, bench, maps):
    output = network_output(maps.maximal, model={"extent": NO_VISIBLE_FLOW})

    pair, diagnostics, adapter = run_year(monkeypatch, bench, output)

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


def weighted_two_bounds(maps):
    return network_output(
        maps.maximal,
        permanent=maps.minimal,
        calibrate_on={"permanent": 0.25, "complete": 0.75},
        model={"extent": NO_VISIBLE_FLOW},
    )


def test_two_maps_two_bounds(monkeypatch, bench, maps):
    pair, diagnostics, _ = run_year(monkeypatch, bench, weighted_two_bounds(maps))

    assert diagnostics["net.n_bounds_scored"] == 2.0
    # A single-root search must not silently close on one of the two.
    assert "net.J_signed" not in diagnostics
    assert "net.r_optim" not in diagnostics
    for key in ("J_signed", "J", "D_so", "D_os", "D_optim", "r_optim"):
        assert f"net.{key}_minimal" in diagnostics
        assert f"net.{key}_maximal" in diagnostics
    assert diagnostics["net.J_minimal"] == pytest.approx(abs(diagnostics["net.J_signed_minimal"]))
    assert (diagnostics["net.weight_minimal"], diagnostics["net.weight_maximal"]) == (0.25, 0.75)
    assert len(pair) == 4
    assert pair[0] - pair[1] == pytest.approx(0.25 * diagnostics["net.J_signed_minimal"])
    assert pair[2] - pair[3] == pytest.approx(0.75 * diagnostics["net.J_signed_maximal"])
    # The permanent mask is the smaller one, year by year.
    for year in (2001, 2002, 2003):
        minimal_cells = diagnostics[f"net.n_network_sim_minimal_y{year}"]
        assert minimal_cells <= diagnostics[f"net.n_network_sim_maximal_y{year}"]
    assert diagnostics["net.n_network_sim_minimal"] < diagnostics["net.n_network_sim_maximal"]


def test_weighted_sum_of_gaps(monkeypatch, bench, maps):
    pair, diagnostics, _ = run_year(monkeypatch, bench, weighted_two_bounds(maps))

    scored = criterion_for("distance_gap").score(pair)

    expected = 0.25 * diagnostics["net.J_minimal"] + 0.75 * diagnostics["net.J_maximal"]
    assert scored.cost == pytest.approx(expected)
    assert scored.signed_residual is None


def test_constant_run_equals_state(monkeypatch, bench, maps):
    # Every cell flows all year or never: both masks are the state itself.
    output = network_output(
        maps.maximal,
        permanent=maps.maximal,
        calibrate_on=HALF_AND_HALF,
        model={"extent": NO_VISIBLE_FLOW},
    )
    _, diagnostics, _ = run_year(monkeypatch, bench, output, thresholds=np.full(36, 200.0))
    _, state, _ = run_network(
        monkeypatch,
        bench,
        network_output(maps.maximal),
        release_stack(bench, [200.0]),
        None,
    )

    assert diagnostics["net.J_signed_minimal"] == pytest.approx(state["net.J_signed"])
    assert diagnostics["net.J_signed_maximal"] == pytest.approx(state["net.J_signed"])


def test_visible_flow_shrinks_both_masks(monkeypatch, bench, maps):
    fields = {"permanent": maps.minimal, "calibrate_on": HALF_AND_HALF}
    geometric_output = network_output(maps.maximal, **fields, model={"extent": NO_VISIBLE_FLOW})
    visible_output = network_output(
        maps.maximal, **fields, model={"extent": {"visible_flow": "0.02 L/s"}}
    )

    _, geometric, _ = run_year(monkeypatch, bench, geometric_output)
    _, visible, _ = run_year(monkeypatch, bench, visible_output)

    for bound in ("minimal", "maximal"):
        assert visible[f"net.n_network_sim_{bound}"] < geometric[f"net.n_network_sim_{bound}"]
    assert visible["net.visible_flow_m3_s"] == pytest.approx(2.0e-5)


YEAR_REFUSALS = [
    pytest.param({}, [200.0], None, "single period", id="steady run"),
    pytest.param(
        {},
        np.full(6, 50.0),
        list(pd.date_range("2001-03-01", periods=7, freq="MS")),
        "no complete",
        id="no complete year",
    ),
    pytest.param(
        {"flowing_at_least": "30 months"},
        seasonal_thresholds(3),
        BOUNDS,
        "flowing_at_least = '30 months'",
        id="rule longer than the year",
    ),
    pytest.param({}, np.full(24, 50.0), None, "carry no date", id="undated stack"),
]


@pytest.mark.parametrize(("extent", "thresholds", "bounds", "message"), YEAR_REFUSALS)
def test_year_refusals(monkeypatch, bench, maps, extent, thresholds, bounds, message):
    output = network_output(maps.maximal, model={"extent": extent})

    with pytest.raises(ObjectiveError, match=message):
        run_network(monkeypatch, bench, output, release_stack(bench, thresholds), bounds)


def test_run_without_timestep_refused(monkeypatch, bench, maps):
    adapter = StackAdapter(release_stack(bench, seasonal_thresholds(3)))
    ctx = make_trial_ctx(bench, bounds=BOUNDS)
    del ctx.setup.time_grid.window
    monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, ctx))

    with pytest.raises(ObjectiveError, match="no time window"):
        extract_outputs(ctx, {"net": network_output(maps.maximal, model={"extent": {}})})


DURATIONS = [
    pytest.param("1 month", "1 month", (1, 1), id="one month"),
    pytest.param("45 d", "45 d", (2, 1), id="45 days"),
    pytest.param("1 d", "1 d", (1, 0), id="one day"),
    pytest.param(None, None, (1, 1), id="default"),
]


@pytest.mark.parametrize(("flowing", "dry", "steps"), DURATIONS)
def test_durations_in_timesteps(monkeypatch, bench, maps, flowing, dry, steps):
    extent = {"flowing_at_least": flowing, "dry_at_most": dry}
    output = network_output(maps.maximal, model={"extent": extent})

    _, diagnostics, _ = run_year(monkeypatch, bench, output)

    counted = (diagnostics["net.maximal_flowing_steps"], diagnostics["net.minimal_dry_steps"])
    assert counted == steps
    assert diagnostics["net.step_days"] == pytest.approx(30.4375)


def permanent_layer_ctx(bench, permanent):
    ctx = make_trial_ctx(bench)
    networks = SimpleNamespace(reference_permanent=permanent)
    ctx.state.setup.geographic_features = SimpleNamespace(hydrographic_networks=networks)
    return ctx


def test_loader_permanent_reaches(monkeypatch, bench, maps):
    permanent = SimpleNamespace(
        vector_path=str(maps.minimal),
        crs=CRS,
        read_vector=lambda: gpd.read_file(maps.minimal),
    )
    ctx = permanent_layer_ctx(bench, permanent)
    adapter = StackAdapter(release_stack(bench, [200.0]))
    monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, ctx))
    output = network_output(maps.maximal, permanent="data.hydrography")

    from_layer = extract_outputs(ctx, {"net": output}).diagnostics

    file_output = network_output(maps.maximal, permanent=maps.minimal)
    _, from_file, _ = run_network(
        monkeypatch, bench, file_output, release_stack(bench, [200.0]), None
    )
    assert from_layer["net.J_signed"] == pytest.approx(from_file["net.J_signed"])
    assert from_layer["net.observed_network_clipped_minimal"] == 1.0


def test_project_without_permanent_reaches_is_refused(monkeypatch, bench, maps):
    ctx = permanent_layer_ctx(bench, None)
    adapter = StackAdapter(release_stack(bench, [200.0]))
    monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, ctx))
    output = network_output(maps.maximal, permanent="data.hydrography")

    with pytest.raises(UnresolvedObservedNetwork, match="map.permanent"):
        extract_outputs(ctx, {"net": output})


# Scoring window: only the complete years the phase window holds are scored.


def score_two_bounds(monkeypatch, bench, stream_file, stack, bounds, window=None):
    output = network_output(stream_file, model={"extent": {"visible_flow": "0 L/s"}})
    extracted, _ = run_extraction(monkeypatch, bench, {"net": output}, stack, bounds, window=window)
    return extracted.diagnostics


def test_window_drops_spin_up(monkeypatch, bench, stream_file):
    thresholds = seasonal_thresholds(3, wet_first_year=True)
    windowed = score_two_bounds(
        monkeypatch, bench, stream_file, release_stack(bench, thresholds), SPIN_UP_RUN, WINDOW
    )
    trimmed = score_two_bounds(
        monkeypatch,
        bench,
        stream_file,
        release_stack(bench, thresholds[12:]),
        monthly_bounds(2001, 2),
    )
    whole = score_two_bounds(
        monkeypatch, bench, stream_file, release_stack(bench, thresholds), SPIN_UP_RUN
    )

    assert windowed["net.J_signed_maximal"] == pytest.approx(trimmed["net.J_signed_maximal"])
    # Left in, the wet spin-up year is a year of its own that the quorum counts.
    assert whole["net.n_years_required"] == 2.0
    assert windowed["net.n_years_required"] == 1.0
    assert whole["net.n_network_sim_maximal_y2000"] > windowed["net.n_network_sim_maximal_y2001"]


def test_window_time_zone_utc(monkeypatch, bench, stream_file):
    window = (pd.Timestamp("2001-01-01", tz="UTC"), pd.Timestamp("2002-12-31", tz="UTC"))

    scored = score_two_bounds(
        monkeypatch,
        bench,
        stream_file,
        release_stack(bench, seasonal_thresholds(3, wet_first_year=True)),
        SPIN_UP_RUN,
        window,
    )

    assert scored["net.n_years_scored"] == 2.0


def test_window_without_whole_year(monkeypatch, bench, stream_file):
    window = (pd.Timestamp("2001-02-01"), pd.Timestamp("2001-11-30"))

    with pytest.raises(ObjectiveError, match=r"window .* leaves out 2000, 2001, 2002"):
        score_two_bounds(
            monkeypatch,
            bench,
            stream_file,
            release_stack(bench, seasonal_thresholds(3, wet_first_year=True)),
            SPIN_UP_RUN,
            window,
        )


# Saturated thickness (m) published beside the network distances.
# `d_sat_m` is the saturated thickness averaged by area over the catchment at the
# state the network is read from. It never enters the scored pair, and a backend
# that serves no such field loses it alone.


def saturation_run(*, top, botm, closed=None):
    mesh = SimpleNamespace(top=np.asarray(top, dtype=float), botm=np.asarray(botm, dtype=float))
    model = SimpleNamespace(solver_mesh=mesh)
    if closed is not None:
        model.inactive_mask = np.asarray(closed, dtype=bool)
    return SimpleNamespace(solver_run=SimpleNamespace(solver_model=model))


def catchment_cells(catchment, areas):
    return SimpleNamespace(
        catchment=np.asarray(catchment, dtype=bool),
        cell_area_m2=np.asarray(areas, dtype=float),
    )


def test_area_weighted_thickness():
    run_ctx = saturation_run(top=[100.0] * 4, botm=[[90.0] * 4, [70.0] * 4])
    geometry = catchment_cells([True, True, False, True], [1.0, 3.0, 50.0, 1.0])
    # Two timesteps: only the last is read. The third cell lies outside the
    # catchment and weighs fifty times the others.
    thickness = SimpleNamespace(values=np.array([[0.0] * 4, [10.0, 20.0, 99.0, np.nan]]))

    out = catchment_saturation(run_ctx, geometry, thickness)

    assert out["d_sat_m"] == pytest.approx((10.0 * 1.0 + 20.0 * 3.0) / 4.0)
    assert out["d_sat_unset_fraction"] == pytest.approx(1.0 / 5.0)
    assert out["d_aquifer_m"] == pytest.approx(30.0)
    assert out["d_sat_over_d"] == pytest.approx(17.5 / 30.0)


def test_unset_share_dry_inactive():
    # MODFLOW writes HDRY on a dry cell and HNOFLO on one it never computed, and
    # both come back NaN. The closed columns of the model tell them apart. A lake
    # footprint is one such cell, and it is not a dry state.
    run_ctx = saturation_run(
        top=[100.0] * 4, botm=[[90.0] * 4, [70.0] * 4], closed=[False, False, True, False]
    )
    geometry = catchment_cells([True] * 4, [1.0, 2.0, 3.0, 4.0])
    thickness = SimpleNamespace(values=np.array([10.0, np.nan, np.nan, 20.0]))

    out = catchment_saturation(run_ctx, geometry, thickness)

    assert out["d_sat_dry_fraction"] == pytest.approx(2.0 / 10.0)
    assert out["d_sat_inactive_fraction"] == pytest.approx(3.0 / 10.0)
    assert "d_sat_unset_fraction" not in out
    assert out["d_sat_m"] == pytest.approx((10.0 * 1.0 + 20.0 * 4.0) / 5.0)


def test_mask_on_other_mesh():
    run_ctx = saturation_run(top=[100.0] * 2, botm=[[70.0] * 2], closed=[False] * 3)
    thickness = SimpleNamespace(values=np.array([10.0, np.nan]))

    out = catchment_saturation(run_ctx, catchment_cells([True, True], [1.0, 1.0]), thickness)

    assert out["d_sat_unset_fraction"] == pytest.approx(0.5)
    assert "d_sat_dry_fraction" not in out


def test_no_thickness_gives_nothing():
    run_ctx = saturation_run(top=[100.0], botm=[[70.0]])

    assert catchment_saturation(run_ctx, catchment_cells([True], [1.0]), None) == {}


def test_field_on_other_mesh_warns(caplog):
    run_ctx = saturation_run(top=[100.0, 100.0], botm=[[70.0, 70.0]])
    thickness = SimpleNamespace(values=np.array([10.0, 20.0, 30.0]))

    with caplog.at_level(logging.WARNING):
        out = catchment_saturation(run_ctx, catchment_cells([True, True], [1.0, 1.0]), thickness)

    assert out == {}
    assert "holds 3 cells" in caplog.text


def test_no_base_no_aquifer_thickness():
    mesh = SimpleNamespace(botm=None, top=np.array([100.0, 100.0]))
    run_ctx = SimpleNamespace(
        solver_run=SimpleNamespace(solver_model=SimpleNamespace(solver_mesh=mesh))
    )
    thickness = SimpleNamespace(values=np.array([10.0, 20.0]))

    out = catchment_saturation(run_ctx, catchment_cells([True, True], [1.0, 1.0]), thickness)

    assert out == {"d_sat_m": 15.0, "d_sat_unset_fraction": 0.0}


def test_backend_without_thickness():
    class NoThicknessAdapter:
        def observables(self, _solver_run, _requests, *, time_index=None):
            raise ObservableNotAvailableError("no saturated thickness here")

    output = SimpleNamespace(time="all")
    run_ctx = SimpleNamespace(solver_run=object())

    result = solver_extract._saturated_thickness_or_none(
        NoThicknessAdapter(), run_ctx, "network", output, None
    )

    assert result is None


THICKNESS_STATES = [
    pytest.param(np.ones(4), 2, None, id="one row for two steps"),
    pytest.param(np.ones((3, 4)), 2, None, id="three rows for two steps"),
    pytest.param(np.arange(8.0).reshape(2, 4), 2, [4.0, 5.0, 6.0, 7.0], id="last of two"),
]


@pytest.mark.parametrize(("field", "n_times", "kept"), THICKNESS_STATES)
def test_thickness_at_scored_state(field, n_times, kept, caplog):
    thickness = adapter_result("d", field, "m")

    with caplog.at_level(logging.WARNING):
        result = solver_extract._thickness_at("net", thickness, 1, n_times)

    assert (result if result is None else result.values.ravel().tolist()) == kept
    assert ("No d_sat_m for output net" in caplog.text) is (kept is None)


TIMESTEP_EDGES = [
    pytest.param(
        None,
        pd.date_range("2000-01-01", periods=4, tz="Europe/Paris"),
        "1999-12-31T23",
        id="bounds in Paris time",
    ),
    pytest.param(
        pd.date_range("2000-01-11", periods=3, freq="10D"), None, "2000-01-01T00", id="stamps"
    ),
]


@pytest.mark.parametrize(("times", "bounds", "expected"), TIMESTEP_EDGES)
def test_timestep_edges(times, bounds, expected):
    result = adapter_result("r", np.ones(3), "m3 s-1", times=times)

    edges = solver_extract._timestep_edges("net", result, 3, bounds)

    assert str(edges[0])[:13] == expected
    assert edges.size == 4
    with pytest.raises(ObjectiveError, match="carry no date"):
        solver_extract._timestep_edges("net", adapter_result("r", np.ones(3), "m"), 3, None)


def test_complete_map_mismatch(monkeypatch):
    maps_of_run = SimpleNamespace(maximal=SimpleNamespace(catchment_mismatch=np.float32(0.25)))
    monkeypatch.setattr(solver_extract, "network_maps_from_run", lambda _run, _output: maps_of_run)

    assert solver_extract.scored_catchment_mismatch(None, None) == 0.25
