"""A local DRIAS Explore2 NetCDF read as precipitation and ETP forcing.

No network. Every file is a small synthetic grid written in tmp_path in the DRIAS
layout (dims ``time, y, x``, native CRS Lambert II extended, 8 km cells, flux in
kg m-2 s-1, which is 86400 mm/day per unit).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from pydantic import ValidationError
from pyproj import Transformer

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.common.clients import explore2_files as explore2
from hydromodpy.data.provenance.sidecars import CacheIndex
from hydromodpy.data.variables.forcing_series import (
    EtpConfig,
    EtpSourceConfig,
    EtpVariable,
    PrecipitationConfig,
    PrecipitationSourceConfig,
    PrecipitationVariable,
)

NATIVE_X0_M = 60000.0
NATIVE_Y0_M = 1610000.0
CELL_M = 8000.0
PERIOD = (datetime(2015, 1, 1), datetime(2015, 1, 5))


def write_drias_file(
    tmp_path: Path,
    *,
    variable: str = "prtotAdjust",
    calendar: str = "standard",
    unit: str = "m",
    value: float = 2.0e-5,  # kg m-2 s-1
) -> Path:
    nx, ny, ntime = 12, 10, 5
    x = NATIVE_X0_M + np.arange(nx) * CELL_M
    y = NATIVE_Y0_M + np.arange(ny) * CELL_M
    if unit != "m":
        x, y = x / 100.0, y / 100.0
    data = np.full((ntime, ny, nx), value, dtype="float64")
    ds = xr.Dataset(
        {variable: (("time", "y", "x"), data)},
        coords={
            "time": (
                "time",
                np.arange(ntime),
                {"units": "days since 2015-01-01", "calendar": calendar},
            ),
            "y": ("y", y, {"units": unit}),
            "x": ("x", x, {"units": unit}),
        },
    )
    path = tmp_path / "drias.nc"
    ds.to_netcdf(path)
    return path


def bbox_around_native_cell(ix: int, iy: int, half_width_m: float = 4000.0):
    """A run bbox (EPSG:2154) centered on one cell of the synthetic native grid."""
    transformer = Transformer.from_crs(
        explore2.EXPLORE2_NATIVE_CRS, explore2.EXPLORE2_CRS, always_xy=True
    )
    cx, cy = transformer.transform(NATIVE_X0_M + ix * CELL_M, NATIVE_Y0_M + iy * CELL_M)
    return (cx - half_width_m, cy - half_width_m, cx + half_width_m, cy + half_width_m)


BBOX = bbox_around_native_cell(5, 5)

RENAMED = [
    pytest.param("precipitation", "prtotAdjust", 2.0e-5, id="precipitation"),
    pytest.param("etp", "evspsblpotAdjust", 1.0e-6, id="etp"),
]


@pytest.mark.parametrize(("variable", "drias_name", "flux"), RENAMED)
def test_variable_is_renamed_and_converted(tmp_path, variable, drias_name, flux):
    path = write_drias_file(tmp_path, variable=drias_name, value=flux)

    (record,) = explore2.read_explore2(path, variable=variable, bbox=BBOX, project_period=None)

    assert record.variable == variable
    assert record.unit == "mm/day"
    assert record.source == "explore2"
    assert record.crs == explore2.EXPLORE2_CRS
    np.testing.assert_allclose(record.data[variable].values, flux * 86400.0)


def test_hectometre_coordinates_are_read_as_metres(tmp_path):
    path = write_drias_file(tmp_path, unit="hm")

    records = explore2.read_explore2(path, variable="precipitation", bbox=BBOX, project_period=None)

    # Native coordinates in hectometres are 100x smaller than the bbox (in
    # metres). Finding the requested cells at all proves the scale was applied.
    assert records[0].data["precipitation"].values.size > 0


def test_cell_centre_is_reprojected_like_pyproj():
    transformer = Transformer.from_crs(
        explore2.EXPLORE2_NATIVE_CRS, explore2.EXPLORE2_CRS, always_xy=True
    )
    expected_x, expected_y = transformer.transform(600000.0, 2400000.0)

    x, y = explore2._reproject_grid(
        np.array([600000.0]),
        np.array([2400000.0]),
        explore2.EXPLORE2_NATIVE_CRS,
        explore2.EXPLORE2_CRS,
    )

    np.testing.assert_allclose([x[0, 0], y[0, 0]], [expected_x, expected_y])


def reach_through_sources_table(tmp_path, variable_class, config_class, source_class, drias_name):
    path = write_drias_file(tmp_path, variable=drias_name)
    config = config_class(sources=[source_class(source="explore2", path=path, extent="watershed")])
    variable = variable_class(
        config=config, index=None, project_extent=BBOX, project_period=PERIOD, data_dir=None
    )
    return variable.load()


SECTIONS = [
    pytest.param(
        PrecipitationVariable,
        PrecipitationConfig,
        PrecipitationSourceConfig,
        "prtotAdjust",
        "precipitation",
        id="precipitation",
    ),
    pytest.param(EtpVariable, EtpConfig, EtpSourceConfig, "evspsblpotAdjust", "etp", id="etp"),
]


@pytest.mark.parametrize(
    ("variable_class", "config_class", "source_class", "drias_name", "name"), SECTIONS
)
def test_variable_reaches_explore2_through_its_sources_table(
    tmp_path, variable_class, config_class, source_class, drias_name, name
):
    result = reach_through_sources_table(
        tmp_path, variable_class, config_class, source_class, drias_name
    )

    assert len(result.fields) == 1
    assert result.fields[0].variable == name


def test_second_file_over_the_same_box_is_read_not_cached(tmp_path):
    (tmp_path / "rcp45").mkdir()
    (tmp_path / "rcp85").mkdir()
    first = write_drias_file(tmp_path / "rcp45", value=2.0e-5)
    second = write_drias_file(tmp_path / "rcp85", value=8.0e-5)
    index = CacheIndex(tmp_path / "data")

    def mean_precipitation(path: Path) -> float:
        config = PrecipitationConfig(
            sources=[PrecipitationSourceConfig(source="explore2", path=path, extent="watershed")]
        )
        variable = PrecipitationVariable(
            config=config,
            index=index,
            project_extent=BBOX,
            project_period=PERIOD,
            data_dir=tmp_path / "data" / "precipitation",
        )
        record = variable.load().fields[0]
        return float(np.asarray(record.data["precipitation"].values).mean())

    mean_precipitation(first)

    np.testing.assert_allclose(mean_precipitation(second), 8.0e-5 * 86400.0)


# 365_day is the CF synonym of noleap, so the allowlist must refuse it too.
CALENDARS = [pytest.param("360_day", id="360 day"), pytest.param("365_day", id="365 day")]


@pytest.mark.parametrize("calendar", CALENDARS)
def test_calendar_refusals(tmp_path, calendar):
    path = write_drias_file(tmp_path, calendar=calendar)

    with pytest.raises(DataContractViolation, match=calendar):
        explore2.read_explore2(path, variable="precipitation", bbox=BBOX, project_period=None)


def test_explore2_source_requires_a_path():
    with pytest.raises(ValidationError, match="Explore2 source requires 'path'"):
        PrecipitationSourceConfig(source="explore2")
