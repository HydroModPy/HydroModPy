"""The precipitation and ETP grids (mm/day) that the soil reservoir reads, in `compute_soil_forcings`.

The orchestrator opens a file-backed grid itself and leaves the shared record untouched.
Every grid it cannot use, and every soil that never settles, stops the run with a message that
names the fix.
"""

from __future__ import annotations

import cftime
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.core.exceptions import ConfigError, DataContractViolation, MissingForcingError
from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.model.forcing.soil_config import SoilReservoirConfig
from hydromodpy.model.forcing.soil_forcing import compute_soil_forcings

CRS = "EPSG:2154"
X = np.array([0.0, 100.0])
Y = np.array([100.0, 0.0])
DAYS = pd.date_range("2015-01-01", periods=10, freq="D")


def dataset(variable, values, *, days=DAYS, x=X, y=Y) -> xr.Dataset:
    return xr.Dataset(
        {variable: (("time", "y", "x"), values)}, coords={"time": days, "y": y, "x": x}
    )


def record(variable, data, *, crs=CRS, days=DAYS) -> FieldRecord:
    return FieldRecord(
        variable=variable,
        source="sim2",
        unit="mm/day",
        data=data,
        bbox=(0.0, 0.0, 100.0, 100.0),
        crs=crs,
        date_start=days[0],
        date_end=days[-1],
    )


def grid(variable, value, *, days=DAYS, x=X, y=Y, crs=CRS, edit=None) -> LoadResult:
    """A daily grid of one constant value in mm/day, with one cell changed by `edit`."""
    values = np.full((len(days), len(y), len(x)), value)
    if edit is not None:
        values[edit[0]] = edit[1]
    data = dataset(variable, values, days=days, x=x, y=y)
    return LoadResult(fields=[record(variable, data, crs=crs, days=days)])


def window_of(days) -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=days[0], end=days[-1], step_value=1, step_unit="day", coverage_policy="error"
    )


def compute(*, precipitation=None, etp=None, window=None, config=None):
    return compute_soil_forcings(
        precipitation=grid("precipitation", 5.0) if precipitation is None else precipitation,
        etp=grid("etp", 2.0) if etp is None else etp,
        config=SoilReservoirConfig(ru=100.0, spinup="none") if config is None else config,
        window=window_of(DAYS) if window is None else window,
        model_crs=CRS,
    )


def test_a_file_backed_record_stays_a_path(tmp_path):
    days = pd.date_range("2015-01-01", periods=15, freq="D")
    records = {}
    for variable, value in (("precipitation", 5.0), ("etp", 2.0)):
        path = tmp_path / f"{variable}.nc"
        dataset(variable, np.full((len(days), 2, 2), value), days=days).to_netcdf(path)
        records[variable] = record(variable, path, days=days)

    compute_soil_forcings(
        precipitation=LoadResult(fields=[records["precipitation"]]),
        etp=LoadResult(fields=[records["etp"]]),
        config=SoilReservoirConfig(ru=100.0, spinup="none"),
        window=window_of(days),
        model_crs=CRS,
    )

    assert records["precipitation"].data == tmp_path / "precipitation.nc"
    assert records["etp"].data == tmp_path / "etp.nc"


def station_only() -> LoadResult:
    data = pd.DataFrame({"datetime": DAYS, "value": np.full(len(DAYS), 5.0)})
    station = PointRecord(
        station_id="X1",
        variable="precipitation",
        source="hubeau",
        unit="mm/day",
        frequency="D",
        data=data,
        date_start=DAYS[0],
        date_end=DAYS[-1],
    )
    return LoadResult(points=[station])


def two_grids() -> LoadResult:
    good = grid("precipitation", 5.0).fields[0]
    return LoadResult(fields=[good, good])


def two_unnamed_variables() -> LoadResult:
    values = np.full((len(DAYS), 2, 2), 5.0)
    data = xr.Dataset(
        {"foo": (("time", "y", "x"), values), "bar": (("time", "y", "x"), values)},
        coords={"time": DAYS, "y": Y, "x": X},
    )
    return LoadResult(fields=[record("precipitation", data)])


def wrong_dimensions() -> LoadResult:
    values = np.full((len(DAYS), 2, 2), 5.0)
    data = xr.Dataset(
        {"precipitation": (("time", "lat", "lon"), values)},
        coords={"time": DAYS, "lat": Y, "lon": X},
    )
    return LoadResult(fields=[record("precipitation", data)])


def calendar_360_day() -> LoadResult:
    times = cftime.num2date(np.arange(len(DAYS)), units="days since 2015-01-01", calendar="360_day")
    values = np.full((len(DAYS), 2, 2), 5.0)
    data = xr.Dataset(
        {"precipitation": (("time", "y", "x"), values)}, coords={"time": times, "y": Y, "x": X}
    )
    return LoadResult(fields=[record("precipitation", data)])


# A gap of 3 days after the fifth day makes the step irregular.
IRREGULAR_DAYS = pd.DatetimeIndex(
    list(DAYS[:5]) + [DAYS[4] + pd.Timedelta(days=3)] + list(DAYS[5:9])
)
# A 365-day record at 0.05 mm/day, for a window of one year.
YEAR = pd.date_range("2015-01-01", periods=365, freq="D")

# A little rain most days, a touch less than the steady demand of 0.30 mm/day. With ru = 1000 mm
# the soil stays in the linear ETR regime all year and drains a few mm per cycle, far too slowly
# to settle in 20 repetitions. The spike keeps the near-zero-rain guard from firing first.
SLOW_DRAIN = {
    "precipitation": grid("precipitation", 0.25, days=YEAR, x=X[:1], y=Y[:1], edit=(10, 5.0)),
    "etp": grid("etp", 0.30, days=YEAR, x=X[:1], y=Y[:1]),
    "window": window_of(YEAR),
    "config": SoilReservoirConfig(ru=1000.0, spinup="first_year"),
}

REFUSALS = [
    pytest.param(
        MissingForcingError,
        {"precipitation": LoadResult()},
        [
            "[data.precipitation] loaded nothing for 2015-01-01 to 2015-01-10, and the "
            "soil reservoir needs a value for every day: see the error logged above for "
            "the cause, or run hmp data get precipitation on the same extent to test the "
            "source alone."
        ],
        id="family loaded nothing",
    ),
    pytest.param(
        DataContractViolation,
        {"precipitation": station_only()},
        [
            "[data.precipitation] holds station series, and the soil reservoir reads a "
            'daily grid: use a gridded source such as source = "sim2", or a NetCDF grid '
            'with source = "file".'
        ],
        id="station points only",
    ),
    pytest.param(
        DataContractViolation,
        {"precipitation": two_grids()},
        [
            "[data.precipitation] holds 2 grids, and the soil reservoir reads one: keep "
            "a single [[data.precipitation.sources]] block."
        ],
        id="two grids in one family",
    ),
    pytest.param(
        DataContractViolation,
        {"precipitation": two_unnamed_variables()},
        [
            "[data.precipitation] file holds no variable named 'precipitation' (it "
            "holds ['foo', 'bar']): name the grid 'precipitation'."
        ],
        id="variable not named",
    ),
    pytest.param(
        DataContractViolation,
        {"precipitation": wrong_dimensions()},
        ["grid has dimensions", "rename the dimensions of the file"],
        id="wrong dimensions",
    ),
    pytest.param(
        DataContractViolation,
        {"precipitation": calendar_360_day()},
        [
            "[data.precipitation] uses the '360_day' calendar, and the soil reservoir "
            "needs real dates: convert the file to the standard calendar first."
        ],
        id="non-standard calendar",
    ),
    pytest.param(
        DataContractViolation,
        {"precipitation": grid("precipitation", 5.0, crs="EPSG:4326")},
        [
            "[data.precipitation] is in EPSG:4326 and the model in EPSG:2154: forcing "
            "grids are never reprojected, so the soil columns would land on the wrong "
            "cells. Reproject the file to EPSG:2154, or set [geographic] crs_project = "
            '"EPSG:4326".'
        ],
        id="other crs than the model",
    ),
    pytest.param(
        DataContractViolation,
        {"precipitation": grid("precipitation", 5.0, days=IRREGULAR_DAYS)},
        ["holds one value every", "give it daily values"],
        id="irregular time step",
    ),
    pytest.param(
        DataContractViolation,
        {"precipitation": grid("precipitation", 5.0, days=DAYS[:5])},
        [
            "[data.precipitation] covers 2015-01-01 to 2015-01-05, and the run needs "
            "every day from 2015-01-01 to 2015-01-10: extend the source period, or "
            "narrow [simulation.time]."
        ],
        id="grid shorter than the window",
    ),
    pytest.param(
        DataContractViolation,
        {"precipitation": grid("precipitation", 5.0, edit=((3, 1, 0), np.nan))},
        [
            "[data.precipitation] has 1 missing values between 2015-01-01 and "
            "2015-01-10, the first on 2015-01-04 in the cell at x = 0, y = 0: the soil "
            "reservoir needs a value for every day and cell. Fill the gaps, or narrow "
            "[simulation.time] to the covered days."
        ],
        id="missing value",
    ),
    pytest.param(
        DataContractViolation,
        {"precipitation": grid("precipitation", 5.0, edit=((2, 0, 1), -1.5))},
        [
            "[data.precipitation] has 1 negative values, the first -1.5 mm/day on "
            "2015-01-03: precipitation cannot be negative. Check the file and its unit."
        ],
        id="negative precipitation",
    ),
    pytest.param(
        DataContractViolation,
        {"etp": grid("etp", 2.0, edit=((0, 0, 0), -0.5))},
        ["etp cannot be negative"],
        id="negative etp",
    ),
    pytest.param(
        DataContractViolation,
        {
            "precipitation": grid("precipitation", 0.05, days=YEAR),
            "etp": grid("etp", 2.0, days=YEAR),
            "window": window_of(YEAR),
        },
        ["never exceeds 0.05 mm/day over 365 days"],
        id="a year of near-zero precipitation",
    ),
    pytest.param(
        DataContractViolation,
        {"precipitation": grid("precipitation", 5.0, edit=((1, 0, 0), 1500.0))},
        [
            "[data.precipitation] reaches 1500 mm/day on 2015-01-02, beyond any daily "
            "rainfall: check the unit of the file and convert it to mm/day."
        ],
        id="excessive precipitation",
    ),
    pytest.param(
        DataContractViolation,
        {"etp": grid("etp", 2.0, edit=((1, 0, 0), 45.0))},
        [
            "[data.etp] reaches 45 mm/day on 2015-01-02, beyond any reference "
            "evapotranspiration: check the unit of the file and convert it to mm/day."
        ],
        id="excessive etp",
    ),
    pytest.param(
        DataContractViolation,
        {"etp": grid("etp", 2.0, x=np.array([0.0, 50.0]))},
        [
            "[data.precipitation] and [data.etp] come on two grids (4 and 4 cells, or "
            "as many cells at other places): the soil reservoir pairs them cell by "
            "cell. Load both from the same provider, or regrid one file onto the other."
        ],
        id="grids on different cells",
    ),
    pytest.param(
        ConfigError,
        SLOW_DRAIN,
        [
            "still moved by",
            "after 20 repetitions of 2015-01-01 to 2015-12-31",
            'spinup = "none"',
        ],
        id="first year that keeps draining",
    ),
]


@pytest.mark.parametrize(("error", "inputs", "fragments"), REFUSALS)
def test_refusals(error, inputs, fragments):
    with pytest.raises(error) as excinfo:
        compute(**inputs)

    for fragment in fragments:
        assert fragment in str(excinfo.value)
