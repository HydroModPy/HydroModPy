"""In soil mode, the calibration discharge reads the soil's own runoff.

The soil reservoir always hands back a runoff ``LoadResult`` (zero when
``impervious_fraction`` is 0), so the calibration must add that one instead of
whatever ``[data.types]`` happened to load, and never warns "Add 'runoff'" in
soil mode: R2 forbids ``[data.runoff]`` there in the first place.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.calibration.metrics import series as series_module
from hydromodpy.calibration.metrics.series import add_runoff_to_discharge
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord

# 1 mm/day over 86.4 km2 is exactly 1 m3/s: 1e-3 * 8.64e7 / 86400.
_CATCH_AREA_KM2 = 86.4
_SIM_INDEX = pd.DatetimeIndex(["2000-01-11", "2000-01-21", "2000-02-20"])


def _gridded_runoff(base_value: float) -> LoadResult:
    """A daily, single-cell runoff grid holding ``base_value`` mm/day."""
    days = pd.date_range("2000-01-01", "2000-03-05", freq="D")
    values = np.full((days.size, 1, 1), base_value)
    dataset = xr.Dataset(
        {"runoff": (("time", "y", "x"), values)},
        coords={"time": days, "y": [0.0], "x": [0.0]},
    )
    record = FieldRecord(
        variable="runoff",
        source="soil_reservoir",
        unit="mm/day",
        data=dataset,
        bbox=(0.0, 0.0, 1.0, 1.0),
        crs="EPSG:2154",
    )
    return LoadResult(fields=[record])


def _context(
    *, loaded_runoff: LoadResult | None, soil_runoff: LoadResult | None
) -> SimpleNamespace:
    soil = SimpleNamespace(runoff=soil_runoff) if soil_runoff is not None else None
    return SimpleNamespace(
        loaded_data=SimpleNamespace(runoff=loaded_runoff),
        setup=SimpleNamespace(
            geographic=SimpleNamespace(catch_area=_CATCH_AREA_KM2),
            soil_forcings=soil,
        ),
    )


@pytest.fixture(autouse=True)
def _fresh_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(series_module, "_RUNOFF_WARNING_EMITTED", set())


def test_the_soil_runoff_is_added_instead_of_the_loaded_one() -> None:
    baseflow = pd.Series(0.0, index=_SIM_INDEX, name="discharge")
    ctx = _context(loaded_runoff=None, soil_runoff=_gridded_runoff(1.0))

    scored = add_runoff_to_discharge(baseflow, ctx)

    assert scored.tolist() == pytest.approx([1.0, 1.0, 1.0])


def test_no_add_runoff_warning_fires_in_soil_mode(caplog: pytest.LogCaptureFixture) -> None:
    baseflow = pd.Series([0.4, 0.7, 1.1], index=_SIM_INDEX, name="discharge")
    ctx = _context(loaded_runoff=None, soil_runoff=_gridded_runoff(2.0))

    with caplog.at_level(logging.WARNING, logger=series_module.__name__):
        add_runoff_to_discharge(baseflow, ctx)

    assert not [r for r in caplog.records if "runoff" in r.getMessage().lower()]


def test_without_soil_forcings_the_loaded_runoff_is_used_as_before() -> None:
    baseflow = pd.Series(0.0, index=_SIM_INDEX, name="discharge")
    ctx = _context(loaded_runoff=_gridded_runoff(3.0), soil_runoff=None)

    scored = add_runoff_to_discharge(baseflow, ctx)

    assert scored.tolist() == pytest.approx([3.0, 3.0, 3.0])
