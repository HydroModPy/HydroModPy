"""A station's position lives on its record, and the resolver has to read it.

Measured on a real Nancon run: no station resolved to a cell, so every gauge was
scored on the whole-catchment discharge whatever its position. The cause was one
lookup that read ``x``/``y``, ``easting``/``northing``, ``longitude``/``latitude``
and a geometry, and never ``PointRecord.location``, which is where every loader
puts it. Right for a gauge at the outlet, silently wrong for any other.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.calibration.metrics import solver_extract as _solver_extract
from hydromodpy.calibration.metrics.series import ObservedSeries
from hydromodpy.calibration.metrics.solver_extract import cell_for_station, resolve_station_cells
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord

GAUGE_XY = (389285.91, 6816518.749)
CELL = (0, 4, 9)


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
            StationLocation(id=station_id, x=GAUGE_XY[0], y=GAUGE_XY[1], crs="EPSG:2154")
            if located
            else None
        ),
    )


@pytest.fixture
def ctx(monkeypatch):
    seen: dict[str, tuple[float, float]] = {}

    def _find(_ctx, x, y):
        seen["xy"] = (float(x), float(y))
        return CELL

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


def test_a_piezometer_is_located_at_the_coordinates_its_record_carries(ctx) -> None:
    cell = cell_for_station(_ctx_with(_record("P1", located=True)), "P1", variable="head")
    assert cell == CELL
    assert ctx["xy"] == pytest.approx(GAUGE_XY)


def test_a_gauge_is_not_located_by_a_coordinate_at_all(ctx) -> None:
    # A head is read at the cell the point falls in; a discharge is the flow
    # accumulated over everything draining to it, and the cell a coordinate lands
    # in was measured on Nancon to drain two tenths of a per cent of the basin.
    assert (
        cell_for_station(_ctx_with(_record("NANCON", located=True)), "NANCON", variable="discharge")
        is None
    )
    assert "xy" not in ctx


def test_a_record_with_no_location_resolves_to_nothing(ctx) -> None:
    # Refusing to guess is the point: the caller then says so instead of
    # substituting a different quantity without a word.
    assert cell_for_station(_ctx_with(_record("P1", located=False)), "P1", variable="head") is None


def test_the_batch_resolver_uses_the_same_lookup(ctx) -> None:
    cells = resolve_station_cells(
        _ctx_with(_record("P1", located=True)),
        [ObservedSeries(station_id="P1", variable="head", series=pd.Series(dtype=float))],
        variable="head",
    )
    assert cells == {"P1": CELL}


def test_an_unknown_station_resolves_to_nothing(ctx) -> None:
    assert (
        cell_for_station(_ctx_with(_record("OTHER", located=True)), "P1", variable="head") is None
    )
