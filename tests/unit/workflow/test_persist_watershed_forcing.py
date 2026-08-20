"""step_persist_forcings: watershed-mean station series for gridded forcings."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pandas as pd
import xarray as xr

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.workflow.steps.prepare_solver.prepare import step_persist_forcings
from tests._helpers.fixtures_catalog import simulation_catalog


@dataclass
class _Loaded:
    runoff: object | None = None
    precipitation: object | None = None


def _runoff_field_record(
    values: np.ndarray,
    times: pd.DatetimeIndex,
    variable: str = "runoff",
) -> FieldRecord:
    ds = xr.Dataset(
        {variable: (("time", "y", "x"), np.asarray(values, dtype="float64"))},
        coords={"time": times, "y": [0.0, 1.0], "x": [0.0, 1.0]},
    )
    return FieldRecord(
        variable=variable,
        source="sim2",
        unit="mm/day",
        data=ds,
        bbox=(0.0, 0.0, 1.0, 1.0),
        crs="EPSG:2154",
        date_start=times[0].to_pydatetime(),
        date_end=times[-1].to_pydatetime(),
        frequency="D",
    )


def _register_sim(catalog) -> str:
    sid = str(uuid4())
    reg = catalog.register_simulation(
        sid,
        project="test",
        solver="modflow6",
        n_cells=4,
        n_layers=1,
        n_timesteps=3,
    )
    if reg.zarr is not None:
        reg.zarr.close()
    return sid


def _ctx(catalog, sid: str, loaded: _Loaded) -> SimpleNamespace:
    return SimpleNamespace(store=catalog, sim_id=sid, loaded_data=loaded)


def test_gridded_runoff_persists_watershed_mean(tmp_path):
    times = pd.date_range("2020-01-01", periods=3, freq="D")
    frames = np.arange(12, dtype="float64").reshape(3, 2, 2)
    loaded = _Loaded(runoff=LoadResult(fields=[_runoff_field_record(frames, times)]))

    with simulation_catalog(tmp_path / "ws") as catalog:
        sid = _register_sim(catalog)
        step_persist_forcings(_ctx(catalog, sid, loaded))

        sz = catalog.open_zarr(sid)
        try:
            station = sz.root["forcing"]["runoff"]["_watershed"]
            values = np.asarray(station["values"][:], dtype="float64")
            # Spatial mean of each 2x2 frame.
            np.testing.assert_allclose(values, [1.5, 5.5, 9.5])
            stamps = np.asarray(station["timestamps"][:]).view("datetime64[ns]")
            assert pd.DatetimeIndex(stamps).equals(times)
            assert station.attrs["unit"] == "mm/day"
        finally:
            sz.close()


def test_station_backed_runoff_skips_watershed_mean(tmp_path):
    # Point records already persist per station; no _watershed duplicate.
    times = pd.date_range("2020-01-01", periods=3, freq="D")
    df = pd.DataFrame({"datetime": times, "value": [1.0, 2.0, 3.0]})
    point = PointRecord(
        station_id="sta1",
        variable="runoff",
        source="custom",
        unit="mm/day",
        frequency="D",
        data=df,
        date_start=times[0].to_pydatetime(),
        date_end=times[-1].to_pydatetime(),
    )
    loaded = _Loaded(runoff=LoadResult(points=[point]))

    with simulation_catalog(tmp_path / "ws") as catalog:
        sid = _register_sim(catalog)
        step_persist_forcings(_ctx(catalog, sid, loaded))

        sz = catalog.open_zarr(sid)
        try:
            runoff_grp = sz.root["forcing"]["runoff"]
            assert "sta1" in runoff_grp
            assert "_watershed" not in runoff_grp
        finally:
            sz.close()


def test_non_allowlisted_family_keeps_field_only(tmp_path):
    # precipitation is not in the watershed-mean allowlist: field array only.
    times = pd.date_range("2020-01-01", periods=2, freq="D")
    frames = np.ones((2, 2, 2), dtype="float64")
    rec = _runoff_field_record(frames, times, variable="precipitation")
    loaded = _Loaded(precipitation=LoadResult(fields=[rec]))

    with simulation_catalog(tmp_path / "ws") as catalog:
        sid = _register_sim(catalog)
        step_persist_forcings(_ctx(catalog, sid, loaded))

        sz = catalog.open_zarr(sid)
        try:
            forcing = sz.root["forcing"]
            assert "precipitation" not in forcing or "_watershed" not in forcing["precipitation"]
        finally:
            sz.close()


def test_watershed_mean_failure_is_non_fatal(tmp_path, monkeypatch):
    # A reduction failure must not break the persist step.
    import hydromodpy.spatial.field.aggregation as agg

    def _boom(_obj):
        raise RuntimeError("boom")

    monkeypatch.setattr(agg, "extract_homogeneous_series_from_fields", _boom)
    times = pd.date_range("2020-01-01", periods=2, freq="D")
    frames = np.ones((2, 2, 2), dtype="float64")
    loaded = _Loaded(runoff=LoadResult(fields=[_runoff_field_record(frames, times)]))

    with simulation_catalog(tmp_path / "ws") as catalog:
        sid = _register_sim(catalog)
        step_persist_forcings(_ctx(catalog, sid, loaded))

        sz = catalog.open_zarr(sid)
        try:
            forcing = sz.root["forcing"]
            assert "runoff" not in forcing or "_watershed" not in forcing["runoff"]
        finally:
            sz.close()
