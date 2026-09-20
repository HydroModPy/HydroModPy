"""A block fitted to a gauge has to be scored on the gauge's own quantity.

Measured on a real Nancon run before this was fixed: the single-metric route
returned a cost of 0.259 and the weighted-block route 82.97 on the same
simulation, the same twelve monthly samples and the same parameter. The pairing
was right, 12 of 12 with nothing clipped; the quantity was not. A drain budget is
baseflow alone, and a gauge measures the whole streamflow, so the runoff forcing
is owed on both routes or neither.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.config import CalibOutputPoint
from hydromodpy.calibration.metrics import solver_extract as _solver_extract
from hydromodpy.calibration.metrics.solver_extract import extract_outputs
from hydromodpy.core.contracts.observables import ObservableResult

CELL = (0, 7)
AREA_M2 = 6.4e7
TIMES = pd.date_range("2015-01-31", periods=3, freq="ME")
BASEFLOW = np.array([1.0, 2.0, 3.0])
RUNOFF_ADDED = 0.5
CATCHMENT_KM2 = 64.6


class _Adapter:
    """Serves a dated discharge at a cell and the area that cell drains."""

    def __init__(self, *, includes_runoff: bool) -> None:
        self.includes_runoff = includes_runoff
        self.asked: list[tuple[str, str]] = []

    def extract_observables(self, _run_ctx, _unused, requests, time_index=None):
        out = {}
        for request in requests:
            self.asked.append((request.name, request.support))
            if request.name == "upstream_area":
                out[request.id] = ObservableResult(
                    request_id=request.id, values=np.array([AREA_M2]), units="m2"
                )
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
    def _wire(*, includes_runoff: bool, observes: str | None):
        adapter = _Adapter(includes_runoff=includes_runoff)
        monkeypatch.setattr(
            _solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, object())
        )
        monkeypatch.setattr(_solver_extract, "find_cell_at_point", lambda *_: CELL)
        monkeypatch.setattr(_solver_extract, "cell_for_station", lambda *_a, **_k: CELL)
        monkeypatch.setattr(_solver_extract, "resolve_time_index", lambda *_a, **_k: TIMES)
        seen: dict[str, float] = {}

        def _add_runoff(series, _ctx, *, area_m2=None):
            seen["area_m2"] = float(area_m2)
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


def test_an_output_fitted_to_no_record_is_left_alone(wired) -> None:
    # Nothing says the vector typed into the file is what a gauge measures.
    adapter, seen, extracted = wired(includes_runoff=False, observes=None)
    assert "area_m2" not in seen
    assert ("upstream_area", "cell") not in adapter.asked
    assert extracted.series["gauge"].to_numpy() == pytest.approx(BASEFLOW)
