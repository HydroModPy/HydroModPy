"""Two nested gauges must each be scored on their own cell, not on either's.

The per-cell discharge path of ``observable_request_for_output`` (explicit
row/col/layer, ``observes`` naming a station, never a call to
``cell_for_station``) let two ``CalibOutputCell`` discharge outputs be declared
side by side, but nothing ever built two of them and checked they stay apart.
Two ways for that to go wrong silently: a request builder that lets the second
output's cell fall back to the first's would score both gauges on the same
reach, and an ``upstream_area`` companion keyed by the wrong output would scale
one gauge's runoff by the other's catchment. On the numbers here, a downstream
gauge draining 64 km2 would feed its runoff into a headwater gauge draining
15 km2, over four times too much, and the composite objective would still
return two numbers and call it a calibration.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.config import CalibObjectiveBlockDecl, CalibOutputCell
from hydromodpy.calibration.metrics import solver_extract as _solver_extract
from hydromodpy.calibration.metrics.observable_scoring import ObservableScorer
from hydromodpy.calibration.metrics.solver_extract import extract_outputs
from hydromodpy.core.contracts.observables import ObservableResult

TIMES = pd.date_range("2015-01-31", periods=3, freq="ME")
CELL_DOWN = (0, 2, 10)
CELL_UP = (0, 9, 4)
AREA_DOWN_M2 = 6.4e7
AREA_UP_M2 = 1.5e7
BASEFLOW_DOWN = np.array([1.0, 2.0, 3.0])
BASEFLOW_UP = np.array([10.0, 20.0, 30.0])


class _Adapter:
    """Serves each gauge's own discharge and the area its own cell drains."""

    def __init__(self, *, baseflow: dict[str, np.ndarray], areas: dict[str, float]) -> None:
        self.baseflow = baseflow
        self.areas = areas
        self.asked: list[tuple[str, str, tuple[int, int, int] | None]] = []

    def extract_observables(self, _run_ctx, _unused, requests, time_index=None):
        out = {}
        for request in requests:
            self.asked.append((request.id, request.name, request.cell))
            if request.name == "upstream_area":
                gauge = request.id.removeprefix("_area:")
                out[request.id] = ObservableResult(
                    request_id=request.id,
                    values=np.array([self.areas[gauge]]),
                    units="m2",
                )
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
def wired(monkeypatch):
    adapter = _Adapter(
        baseflow={"gauge_down": BASEFLOW_DOWN, "gauge_up": BASEFLOW_UP},
        areas={"gauge_down": AREA_DOWN_M2, "gauge_up": AREA_UP_M2},
    )
    monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, object()))
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


def test_each_gauge_is_read_at_its_own_cell(wired) -> None:
    adapter, _outputs, _extracted = wired
    discharge_asked = {req_id: cell for req_id, name, cell in adapter.asked if name == "discharge"}
    assert discharge_asked == {"gauge_down": CELL_DOWN, "gauge_up": CELL_UP}


def test_each_gauge_s_upstream_area_is_asked_at_its_own_cell(wired) -> None:
    adapter, _outputs, _extracted = wired
    area_asked = {req_id: cell for req_id, name, cell in adapter.asked if name == "upstream_area"}
    assert area_asked == {"_area:gauge_down": CELL_DOWN, "_area:gauge_up": CELL_UP}


def test_each_gauge_s_runoff_is_scaled_by_its_own_area(wired) -> None:
    _adapter, _outputs, extracted = wired
    assert extracted.series["gauge_down"].to_numpy() == pytest.approx(
        BASEFLOW_DOWN + AREA_DOWN_M2 / 1e6
    )
    assert extracted.series["gauge_up"].to_numpy() == pytest.approx(BASEFLOW_UP + AREA_UP_M2 / 1e6)


def test_the_two_costs_stay_separate_in_the_components(wired) -> None:
    _adapter, outputs, extracted = wired
    blocks = [
        CalibObjectiveBlockDecl.model_validate(
            {"name": "down_block", "metric": "rmse", "uses_outputs": ["gauge_down"]}
        ),
        CalibObjectiveBlockDecl.model_validate(
            {"name": "up_block", "metric": "rmse", "uses_outputs": ["gauge_up"]}
        ),
    ]
    # The downstream gauge's record matches its simulated series exactly; the
    # headwater one is off by a fixed 0.1: two different costs, so a bug that
    # merges the two blocks or swaps their inputs cannot pass both assertions.
    observed_records = {
        "gauge_down": pd.Series(BASEFLOW_DOWN + AREA_DOWN_M2 / 1e6, index=TIMES),
        "gauge_up": pd.Series(BASEFLOW_UP + AREA_UP_M2 / 1e6 + 0.1, index=TIMES),
    }
    scorer = ObservableScorer(outputs, blocks, observed_records=observed_records)
    _total, components = scorer.score(extracted.observables, diagnostics=extracted.diagnostics)
    assert components["down_block.raw_cost"] == pytest.approx(0.0, abs=1e-9)
    assert components["up_block.raw_cost"] == pytest.approx(0.1)
