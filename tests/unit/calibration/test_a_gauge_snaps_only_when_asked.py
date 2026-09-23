"""A gauge moves onto the most accumulated cell only when its output asks.

A discharge gauge coordinate is rarely on the talweg the model routes on: on the
Nancon it resolves to a cell draining 0.107 km2 of 64.6. ``snap_radius`` moves it
onto the most accumulated cell within a radius. It is opt-in, so every project
that does not write it keeps the cell it had.

The grid is a 5 x 5 V-shaped valley of 100 m cells whose talweg is column 2,
flowing towards the last row. Its drained areas, in cells, are::

    1  2   5  2  1
    1  2  10  2  1
    1  2  15  2  1
    1  2  20  2  1
    1  2  25  2  1

The accumulation is the solver's own: the fake adapter serves the
``upstream_area`` field through the shared MODFLOW extraction.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibOutputCell, CalibOutputPoint
from hydromodpy.calibration.metrics import solver_extract as _solver_extract
from hydromodpy.calibration.metrics.gauge_snap import GaugeSnapError, snap_to_most_accumulated
from hydromodpy.calibration.metrics.solver_extract import (
    extract_outputs,
    observable_request_for_output,
)
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.solver.base.cell_lookup import locate_cell_on_solver_mesh
from hydromodpy.solver.modflow_common import observable_extraction as _extraction
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

N = 5
CELL_M2 = 1.0e4
TIMES = pd.date_range("2015-01-31", periods=3, freq="ME")
GAUGE_XY = (140.0, 250.0)
"""Nearest centre is (row 2, col 1), draining 2 cells; the talweg is 110 m east."""


def _valley_model() -> SimpleNamespace:
    rows, cols = np.mgrid[0:N, 0:N]
    top = 10.0 * np.abs(cols - 2) + (N - rows) * 1.0 + 5.0
    mesh = SolverMesh.from_structured_arrays(
        nrow=N, ncol=N, top=top, botm=np.full((1, N, N), -10.0), dx=100.0, dy=100.0
    )
    return SimpleNamespace(solver_mesh=mesh)


class _Adapter:
    """Serves the solver's own drained areas and cell centres, and a flat baseflow."""

    def __init__(self, model: SimpleNamespace) -> None:
        self.model = model
        self.asked: list = []

    def extract_observables(self, _run_ctx, _store, requests, time_index=None):
        self.asked.extend(requests)
        geometry = [r for r in requests if r.name in ("upstream_area", "cell_xy")]
        served, _ = _extraction.extract_common_modflow_observables(
            Path("."), "model", self.model, geometry
        )
        for request in requests:
            if request.name == "discharge":
                served[request.id] = ObservableResult(
                    request_id=request.id,
                    values=np.ones(TIMES.size),
                    units="m3 s-1",
                    times=TIMES,
                )
        return served

    def locate_cell(self, run_ctx, x, y):
        return locate_cell_on_solver_mesh(run_ctx, x, y)


@pytest.fixture
def adapter(monkeypatch) -> _Adapter:
    model = _valley_model()
    fake = _Adapter(model)
    run_ctx = SimpleNamespace(model=model, run=SimpleNamespace(id="flow", solver="modflow6"))
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


def test_default_off_leaves_the_cell_unchanged(adapter: _Adapter) -> None:
    request = observable_request_for_output("gauge", _point(), SimpleNamespace())
    assert request.cell == (0, 2, 1)
    assert not _asked_for_the_field(adapter)


def test_a_point_snap_moves_the_cell_and_logs_both_areas(adapter: _Adapter, caplog) -> None:
    with caplog.at_level(logging.INFO):
        request = observable_request_for_output(
            "gauge", _point(snap_radius="120 m"), SimpleNamespace()
        )
    assert request.cell == (0, 2, 2)
    assert _asked_for_the_field(adapter)
    message = " ".join(record.getMessage() for record in caplog.records)
    assert "snapped 110.0 m (of 120 m allowed)" in message
    assert "draining 0.020 km2" in message
    assert "draining 0.150 km2" in message


def test_a_radius_too_small_is_refused_through_the_output(adapter: _Adapter) -> None:
    with pytest.raises(GaugeSnapError, match="'gauge'.*90.0 m away"):
        observable_request_for_output("gauge", _point(snap_radius=50.0), SimpleNamespace())


def test_a_cell_output_snaps_from_its_own_centre(adapter: _Adapter) -> None:
    output = CalibOutputCell.model_validate(
        {"variable": "discharge", "row": 2, "col": 1, "snap_radius": 100.0}
    )
    request = observable_request_for_output("gauge", output, SimpleNamespace())
    assert request.cell == (0, 2, 2)


def _station_ctx() -> SimpleNamespace:
    record = SimpleNamespace(
        station_id="J0000000", location=SimpleNamespace(x=GAUGE_XY[0], y=GAUGE_XY[1])
    )
    return SimpleNamespace(loaded_data=SimpleNamespace(hydrometry=SimpleNamespace(points=[record])))


def test_a_named_discharge_station_keeps_the_catchment_series_by_default(
    adapter: _Adapter,
) -> None:
    """The measured default: a discharge station is not placed by its coordinate."""
    output = _point(observes="J0000000")
    request = observable_request_for_output("gauge", output, _station_ctx())
    assert request.support == "domain"
    assert not _asked_for_the_field(adapter)


def test_a_named_discharge_station_is_placed_and_snapped_when_asked(adapter: _Adapter) -> None:
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
    assert request.cell == (0, 2, 2)


def test_several_gauges_each_snap_to_their_own_cell(adapter: _Adapter) -> None:
    outputs = {
        "upper": _point(x=160.0, y=150.0, snap_radius=100.0),
        "lower": _point(x=160.0, y=350.0, snap_radius=100.0),
    }
    extract_outputs(SimpleNamespace(), outputs)
    discharge = {r.id: r.cell for r in adapter.asked if r.name == "discharge"}
    areas = {r.id: r.cell for r in adapter.asked if r.name == "upstream_area" and r.cell}
    assert discharge == {"upper": (0, 1, 2), "lower": (0, 3, 2)}
    assert areas == {}  # no 'observes': no runoff scaling asked


def test_two_gauges_snapped_onto_one_cell_are_named(adapter: _Adapter, caplog) -> None:
    outputs = {
        "a": _point(x=160.0, y=150.0, snap_radius=100.0),
        "b": _point(x=160.0, y=160.0, snap_radius=100.0),
    }
    with caplog.at_level(logging.WARNING):
        extract_outputs(SimpleNamespace(), outputs)
    assert any(
        "a, b were all snapped onto cell (0, 1, 2)" in record.getMessage()
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


# --- the solver serves the centres, the calibration never reads the mesh ----


def test_the_solver_serves_the_cell_centres_a_snap_searches() -> None:
    from hydromodpy.core.contracts.observables import ObservableRequest

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
