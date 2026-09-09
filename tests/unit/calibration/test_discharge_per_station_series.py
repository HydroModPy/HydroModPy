"""Each gauge is scored against the simulated discharge AT ITS OWN cell.

The whole-catchment series answers for the outlet gauge alone. A station upstream
closes a smaller catchment, so it gets its own routed series and its own upstream
area for the runoff.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.metrics.composite import (
    _area_id,
    _cell_id,
    _simulated_discharge_by_station,
)
from hydromodpy.calibration.metrics.series import ObservedSeries

_INDEX = pd.date_range("2000-01-01", periods=3, freq="D")


def _result(values, *, includes_runoff: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        values=np.asarray(values, dtype=float),
        units="m3 s-1",
        times=_INDEX[: np.asarray(values).size] if np.asarray(values).ndim else None,
        includes_runoff=includes_runoff,
    )


def _observed(*station_ids: str) -> list[ObservedSeries]:
    return [
        ObservedSeries(
            station_id=sid,
            variable="discharge",
            series=pd.Series([1.0, 1.0, 1.0], index=_INDEX),
        )
        for sid in station_ids
    ]


class _Adapter:
    """Serves whatever the request ids ask for, and records what was asked."""

    def __init__(self, served: dict, *, fail_on_cell: bool = False) -> None:
        self._served = served
        self._fail_on_cell = fail_on_cell
        self.requested: list[list[str]] = []

    def extract_observables(self, run_ctx, _unused, requests, *, time_index=None):
        del run_ctx, time_index
        self.requested.append([r.id for r in requests])
        if self._fail_on_cell and any(r.support == "cell" for r in requests):
            raise RuntimeError("this backend serves no per-cell discharge")
        return {r.id: self._served[r.id] for r in requests}


def _ctx(station_cells: dict[str, tuple[int, int, int]]) -> SimpleNamespace:
    points = [
        SimpleNamespace(station_id=sid, cell_ij=(cell[1], cell[2], cell[0]))
        for sid, cell in station_cells.items()
    ]
    return SimpleNamespace(
        setup=SimpleNamespace(mesh_planar=None, domain=None, geographic=None),
        loaded_data=SimpleNamespace(
            hydrometry=SimpleNamespace(points=points),
            piezometry=None,
            runoff=None,
        ),
    )


_RUN_CTX = SimpleNamespace(run=SimpleNamespace(solver="fake_solver"))


def test_a_station_with_a_cell_gets_its_own_routed_series():
    served = {
        "_catchment": _result([9.0, 9.0, 9.0]),
        _cell_id("UP"): _result([2.0, 2.0, 2.0]),
        _area_id("UP"): _result(1.0e6),
    }
    adapter = _Adapter(served)

    out = _simulated_discharge_by_station(
        adapter, _RUN_CTX, _ctx({"UP": (0, 1, 2)}), _observed("UP"), time_index=_INDEX
    )

    assert out["UP"].to_numpy() == pytest.approx([2.0, 2.0, 2.0])


def test_two_stations_get_two_different_series():
    served = {
        "_catchment": _result([9.0, 9.0, 9.0]),
        _cell_id("UP"): _result([2.0, 2.0, 2.0]),
        _area_id("UP"): _result(1.0e6),
        _cell_id("DOWN"): _result([8.0, 8.0, 8.0]),
        _area_id("DOWN"): _result(9.0e6),
    }
    adapter = _Adapter(served)

    out = _simulated_discharge_by_station(
        adapter,
        _RUN_CTX,
        _ctx({"UP": (0, 1, 2), "DOWN": (0, 3, 4)}),
        _observed("UP", "DOWN"),
        time_index=_INDEX,
    )

    assert out["UP"].to_numpy() == pytest.approx([2.0, 2.0, 2.0])
    assert out["DOWN"].to_numpy() == pytest.approx([8.0, 8.0, 8.0])


def test_an_upstream_area_is_requested_for_every_placed_station():
    """The runoff a gauge sees must be the runoff of the area it drains."""
    served = {
        "_catchment": _result([9.0, 9.0, 9.0]),
        _cell_id("UP"): _result([2.0, 2.0, 2.0]),
        _area_id("UP"): _result(1.0e6),
    }
    adapter = _Adapter(served)

    _simulated_discharge_by_station(
        adapter, _RUN_CTX, _ctx({"UP": (0, 1, 2)}), _observed("UP"), time_index=_INDEX
    )

    assert _area_id("UP") in adapter.requested[0]


def test_a_station_without_a_cell_falls_back_to_the_catchment_series():
    served = {"_catchment": _result([9.0, 9.0, 9.0])}
    adapter = _Adapter(served)

    out = _simulated_discharge_by_station(
        adapter, _RUN_CTX, _ctx({}), _observed("NOWHERE"), time_index=_INDEX
    )

    assert out["NOWHERE"].to_numpy() == pytest.approx([9.0, 9.0, 9.0])
    assert adapter.requested[0] == ["_catchment"]


def test_a_backend_without_per_cell_discharge_falls_back_and_warns(caplog):
    served = {"_catchment": _result([9.0, 9.0, 9.0])}
    adapter = _Adapter(served, fail_on_cell=True)

    with caplog.at_level("WARNING"):
        out = _simulated_discharge_by_station(
            adapter, _RUN_CTX, _ctx({"UP": (0, 1, 2)}), _observed("UP"), time_index=_INDEX
        )

    assert out["UP"].to_numpy() == pytest.approx([9.0, 9.0, 9.0])
    assert "only right for the outlet one" in caplog.text


def test_an_empty_catchment_series_is_refused():
    adapter = _Adapter({"_catchment": _result([])})

    with pytest.raises(NotImplementedError, match="no discharge calibration series"):
        _simulated_discharge_by_station(
            adapter, _RUN_CTX, _ctx({}), _observed("NOWHERE"), time_index=_INDEX
        )


def test_a_routed_reach_series_is_not_given_the_runoff_twice(monkeypatch):
    """A reach already carries the runoff injected into the network."""
    calls: list[float | None] = []

    def _spy(series, ctx, *, area_m2=None):
        del ctx
        calls.append(area_m2)
        return series

    monkeypatch.setattr("hydromodpy.calibration.metrics.composite.add_runoff_to_discharge", _spy)
    served = {
        "_catchment": _result([9.0, 9.0, 9.0], includes_runoff=True),
        _cell_id("UP"): _result([2.0, 2.0, 2.0], includes_runoff=True),
        _area_id("UP"): _result(1.0e6),
    }

    _simulated_discharge_by_station(
        _Adapter(served), _RUN_CTX, _ctx({"UP": (0, 1, 2)}), _observed("UP"), time_index=_INDEX
    )

    # The catchment series is routed, so it is not given the runoff. The station
    # series is routed too and must not be either.
    assert calls == []
