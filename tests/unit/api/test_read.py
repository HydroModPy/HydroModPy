"""Unit tests for ``hmp.read``."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

import hydromodpy as hmp
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.run import Run

pytestmark = pytest.mark.fast


class _FakeBackend:
    """Backend stub with a configurable ``query`` result."""

    def __init__(self, *, has_timeseries: bool = False) -> None:
        self._has_ts = has_timeseries

    def query(self, sql: str, params: Any) -> pd.DataFrame:
        if self._has_ts:
            return pd.DataFrame({"x": [1]})
        return pd.DataFrame()


class _FakeCatalog:
    """Catalog stub exposing ``backend`` and feature listing hooks."""

    def __init__(
        self,
        *,
        has_timeseries: bool = False,
        geographic_features: list[str] | None = None,
    ) -> None:
        self.backend = _FakeBackend(has_timeseries=has_timeseries)
        self._features = geographic_features or []

    def list_geographic_features(self, sim_id: str) -> list[str]:
        return list(self._features)


class _FakeRun(Run):
    """Run subclass with controlled ``field``, ``timeseries`` and ``geographic`` methods."""

    def __init__(
        self,
        sim_id: str = "sim-x",
        *,
        catalog: _FakeCatalog | None = None,
    ) -> None:
        self._sim_id = sim_id
        self._catalog = catalog or _FakeCatalog()
        self.recorded: dict = {}

    def field(self, var, *, timestep=None, layer=None, bbox=None):
        self.recorded["field"] = {
            "var": var,
            "timestep": timestep,
            "layer": layer,
            "bbox": bbox,
        }
        return "ndarray_field"

    def timeseries(self, var, *, station=None, period=None):
        self.recorded["timeseries"] = {
            "var": var,
            "station": station,
            "period": period,
        }
        return pd.Series([1, 2, 3], name=var)

    def geographic(self, var):
        self.recorded["geographic"] = {"var": var}
        return "gdf"


def test_read_rejects_non_run() -> None:
    """``hmp.read`` raises TypeError when ``sim`` is not a Run."""
    with pytest.raises(TypeError, match="Run object"):
        hmp.read("not_a_run", "head")


def test_read_zarr_field_eager_when_time_is_int(monkeypatch) -> None:
    """Single timestep with default lazy returns the eager field array."""
    monkeypatch.setattr(
        "hydromodpy.results.field_registry.has",
        lambda name: name == "head",
    )
    run = _FakeRun()
    result = hmp.read(run, "head", time=2, layer=0)
    assert result == "ndarray_field"
    assert run.recorded["field"] == {
        "var": "head",
        "timestep": 2,
        "layer": 0,
        "bbox": None,
    }


def test_read_timeseries_dispatch(monkeypatch) -> None:
    """A non-field variable falls back to timeseries."""
    monkeypatch.setattr("hydromodpy.results.field_registry.has", lambda name: False)
    run = _FakeRun(catalog=_FakeCatalog(has_timeseries=True))
    result = hmp.read(run, "discharge", sel={"station": "outlet"})
    assert isinstance(result, pd.Series)
    assert run.recorded["timeseries"] == {
        "var": "discharge",
        "station": "outlet",
        "period": None,
    }


def test_read_geographic_feature_dispatch(monkeypatch) -> None:
    """A geographic-only variable goes through ``Run.geographic``."""
    monkeypatch.setattr("hydromodpy.results.field_registry.has", lambda name: False)
    run = _FakeRun(
        catalog=_FakeCatalog(geographic_features=["watershed_polygon"]),
    )
    result = hmp.read(run, "watershed_polygon")
    assert result == "gdf"
    assert run.recorded["geographic"] == {"var": "watershed_polygon"}


def test_read_raises_when_variable_unknown(monkeypatch) -> None:
    """``FieldNotFoundError`` is raised when nothing matches."""
    monkeypatch.setattr("hydromodpy.results.field_registry.has", lambda name: False)
    monkeypatch.setattr(
        "hydromodpy.results.field_registry.all_names",
        lambda: ["head", "drawdown"],
    )
    run = _FakeRun()
    with pytest.raises(FieldNotFoundError):
        hmp.read(run, "unknown_var")
