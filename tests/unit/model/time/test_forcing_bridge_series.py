"""Forcing series built from loaded stations and fields (values in the unit of the source)."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.model.forcing.forcing_bridge import (
    build_forcing_series,
    extract_homogeneous_series,
    resolve_forcing,
)


class LoadResult:
    def __init__(self, points=(), fields=()):
        self.points = list(points)
        self.fields = list(fields)

    @property
    def has_points(self) -> bool:
        return bool(self.points)

    @property
    def has_fields(self) -> bool:
        return bool(self.fields)


def station(values):
    # Two daily values, deliberately listed in reverse date order.
    dates = pd.to_datetime(["2020-01-02", "2020-01-01"])
    return SimpleNamespace(
        data=pd.DataFrame({"datetime": dates[: len(values)], "value": values}), location=None
    )


def test_station_series_are_averaged_by_date():
    result = LoadResult(points=[station([2.0, 4.0]), station([6.0, 8.0])], fields=[object()])

    series = extract_homogeneous_series(result)

    assert series.index.tolist() == pd.to_datetime(["2020-01-01", "2020-01-02"]).tolist()
    assert series.tolist() == [6.0, 4.0]


def test_auto_mode_converts_units_and_keeps_the_source():
    result = LoadResult(points=[station([2.0, 4.0]), station([6.0, 8.0])], fields=[object()])

    resolved = resolve_forcing(result, unit_conversion_factor=0.5, spatial_mode="auto")

    assert resolved.series.tolist() == [3.0, 2.0]
    assert resolved.heterogeneous_source is result


def test_homogeneous_mode_averages_fields(monkeypatch):
    monkeypatch.setattr(
        "hydromodpy.model.forcing.forcing_bridge.spatial_mean_from_fields",
        lambda _result: pd.Series([10.0], index=pd.to_datetime(["2020-01-01"])),
    )
    fields = LoadResult(fields=[object()])

    assert build_forcing_series(fields, force_homogeneous=True).tolist() == [10.0]
    assert resolve_forcing(fields, spatial_mode="homogeneous") is not None


def test_nothing_loaded_resolves_to_none():
    assert resolve_forcing(LoadResult(), spatial_mode="auto") is None


def test_located_points_serve_as_heterogeneous_source():
    located = SimpleNamespace(
        data=pd.DataFrame(columns=["datetime", "value"]),
        location=SimpleNamespace(x=1.0, y=2.0),
    )
    result = LoadResult(points=[located])

    resolved = resolve_forcing(result, spatial_mode="heterogeneous", interpolation_method="idw")

    assert resolved.series is None
    assert resolved.heterogeneous_source is result
    assert resolved.interpolation_method == "idw"
