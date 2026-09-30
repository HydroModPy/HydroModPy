"""A local DRIAS Explore2 NetCDF becomes precipitation and ETP forcing.

No network: every fixture is a small synthetic file written in tmp_path, in
the DRIAS layout (dims ``time, y, x``, native CRS Lambert II extended,
``kg m-2 s-1``).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from pydantic import ValidationError
from pyproj import Transformer

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.common.clients import explore2_files as explore2
from hydromodpy.data.variables.etp.config import EtpConfig, EtpSourceConfig
from hydromodpy.data.variables.etp.manager import EtpManager
from hydromodpy.data.variables.precipitation.config import (
    PrecipitationConfig,
    PrecipitationSourceConfig,
)
from hydromodpy.data.variables.precipitation.manager import PrecipitationManager

_NATIVE_X0 = 60000.0
_NATIVE_Y0 = 1610000.0
_CELL = 8000.0


def _write_drias_file(
    tmp_path: Path,
    *,
    variable: str = "prtotAdjust",
    nx: int = 12,
    ny: int = 10,
    ntime: int = 5,
    calendar: str = "standard",
    x_units: str = "m",
    y_units: str = "m",
    value: float = 2.0e-5,
) -> Path:
    """A synthetic file in the DRIAS Explore2 layout: (time, y, x), kg m-2 s-1."""
    x = _NATIVE_X0 + np.arange(nx) * _CELL
    y = _NATIVE_Y0 + np.arange(ny) * _CELL
    if x_units != "m":
        x = x / 100.0
    if y_units != "m":
        y = y / 100.0
    data = np.full((ntime, ny, nx), value, dtype="float64")
    ds = xr.Dataset(
        {variable: (("time", "y", "x"), data)},
        coords={
            "time": (
                "time",
                np.arange(ntime),
                {"units": "days since 2015-01-01", "calendar": calendar},
            ),
            "y": ("y", y, {"units": y_units}),
            "x": ("x", x, {"units": x_units}),
        },
    )
    path = tmp_path / "drias.nc"
    ds.to_netcdf(path)
    return path


def _bbox_around_native_cell(
    ix: int, iy: int, half_width: float = 4000.0
) -> tuple[float, float, float, float]:
    """A run bbox (EPSG:2154) centred on one cell of the synthetic native grid."""
    x = _NATIVE_X0 + ix * _CELL
    y = _NATIVE_Y0 + iy * _CELL
    transformer = Transformer.from_crs(
        explore2.EXPLORE2_NATIVE_CRS, explore2.EXPLORE2_CRS, always_xy=True
    )
    cx, cy = transformer.transform(x, y)
    return (cx - half_width, cy - half_width, cx + half_width, cy + half_width)


def test_precipitation_is_renamed_and_converted_to_mm_per_day(tmp_path: Path) -> None:
    path = _write_drias_file(tmp_path, variable="prtotAdjust", value=2.0e-5)
    bbox = _bbox_around_native_cell(5, 5)

    records = explore2.read_explore2(path, variable="precipitation", bbox=bbox, project_period=None)

    assert len(records) == 1
    record = records[0]
    assert record.variable == "precipitation"
    assert record.unit == "mm/day"
    assert record.source == "explore2"
    assert record.crs == explore2.EXPLORE2_CRS
    assert "precipitation" in record.data.data_vars
    np.testing.assert_allclose(record.data["precipitation"].values, 2.0e-5 * 86400.0)


def test_etp_is_renamed_from_its_drias_name(tmp_path: Path) -> None:
    path = _write_drias_file(tmp_path, variable="evspsblpotAdjust", value=1.0e-6)
    bbox = _bbox_around_native_cell(5, 5)

    records = explore2.read_explore2(path, variable="etp", bbox=bbox, project_period=None)

    record = records[0]
    assert record.variable == "etp"
    assert "etp" in record.data.data_vars
    np.testing.assert_allclose(record.data["etp"].values, 1.0e-6 * 86400.0)


def test_a_noleap_calendar_is_refused_with_the_soil_reservoir_text(tmp_path: Path) -> None:
    path = _write_drias_file(tmp_path, calendar="noleap")
    bbox = _bbox_around_native_cell(5, 5)

    with pytest.raises(DataContractViolation) as excinfo:
        explore2.read_explore2(path, variable="etp", bbox=bbox, project_period=None)

    assert str(excinfo.value) == (
        "[data.etp] uses the 'noleap' calendar, and the soil reservoir needs "
        "real dates: convert the file to the standard calendar first."
    )


def test_a_360_day_calendar_is_refused(tmp_path: Path) -> None:
    path = _write_drias_file(tmp_path, calendar="360_day")
    bbox = _bbox_around_native_cell(5, 5)

    with pytest.raises(DataContractViolation, match="360_day"):
        explore2.read_explore2(path, variable="precipitation", bbox=bbox, project_period=None)


def test_a_365_day_calendar_is_refused_too(tmp_path: Path) -> None:
    """365_day is the CF synonym of noleap: the allowlist must refuse it too."""
    path = _write_drias_file(tmp_path, calendar="365_day")
    bbox = _bbox_around_native_cell(5, 5)

    with pytest.raises(DataContractViolation, match="365_day"):
        explore2.read_explore2(path, variable="precipitation", bbox=bbox, project_period=None)


def test_a_standard_calendar_file_is_read(tmp_path: Path) -> None:
    path = _write_drias_file(tmp_path, calendar="standard")
    bbox = _bbox_around_native_cell(5, 5)

    records = explore2.read_explore2(path, variable="precipitation", bbox=bbox, project_period=None)

    assert records[0].data["time"].values[0] == np.datetime64("2015-01-01")


def test_a_gregorian_calendar_file_is_read(tmp_path: Path) -> None:
    """gregorian is a CF synonym of standard: the allowlist must accept it."""
    path = _write_drias_file(tmp_path, calendar="gregorian")
    bbox = _bbox_around_native_cell(5, 5)

    records = explore2.read_explore2(path, variable="precipitation", bbox=bbox, project_period=None)

    assert records[0].data["time"].values[0] == np.datetime64("2015-01-01")


def test_hectometre_coordinates_are_read_as_metres(tmp_path: Path) -> None:
    path = _write_drias_file(tmp_path, x_units="hm", y_units="hm")
    bbox = _bbox_around_native_cell(5, 5)

    records = explore2.read_explore2(path, variable="precipitation", bbox=bbox, project_period=None)

    # Native coordinates in hectometres are 100x smaller than the bbox (in
    # metres): finding the requested cells at all proves the scale was applied.
    assert records[0].data["precipitation"].values.size > 0


def test_the_bbox_cut_happens_before_any_value_is_loaded(tmp_path: Path, monkeypatch) -> None:
    path = _write_drias_file(tmp_path, nx=80, ny=80, ntime=2)
    bbox = _bbox_around_native_cell(40, 40, half_width=2000.0)

    materialized_shapes: list[tuple[int, ...]] = []
    original = explore2._materialize

    def spy(data_array):
        materialized_shapes.append(data_array.shape)
        return original(data_array)

    monkeypatch.setattr(explore2, "_materialize", spy)

    explore2.read_explore2(path, variable="precipitation", bbox=bbox, project_period=None)

    assert materialized_shapes, "the crop-and-load boundary was never reached"
    _ntime, ny, nx = materialized_shapes[0]
    assert ny < 80
    assert nx < 80


def test_a_cell_centre_is_reprojected_like_a_direct_pyproj_call() -> None:
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

    assert x[0, 0] == pytest.approx(expected_x)
    assert y[0, 0] == pytest.approx(expected_y)


def test_explore2_source_requires_a_path() -> None:
    with pytest.raises(ValidationError, match="Explore2 source requires 'path'"):
        PrecipitationSourceConfig(source="explore2")


def test_the_precipitation_manager_reaches_explore2_through_its_sources_table(
    tmp_path: Path,
) -> None:
    path = _write_drias_file(tmp_path, variable="prtotAdjust")
    bbox = _bbox_around_native_cell(5, 5)
    config = PrecipitationConfig(
        sources=[PrecipitationSourceConfig(source="explore2", path=path, extent="watershed")]
    )
    manager = PrecipitationManager(
        config=config, catalog=None, project_extent=bbox, project_period=None, data_dir=None
    )

    result = manager.load()

    assert len(result.fields) == 1
    assert result.fields[0].variable == "precipitation"


def test_the_etp_manager_reaches_explore2_through_its_sources_table(tmp_path: Path) -> None:
    path = _write_drias_file(tmp_path, variable="evspsblpotAdjust")
    bbox = _bbox_around_native_cell(5, 5)
    config = EtpConfig(sources=[EtpSourceConfig(source="explore2", path=path, extent="watershed")])
    manager = EtpManager(
        config=config, catalog=None, project_extent=bbox, project_period=None, data_dir=None
    )

    result = manager.load()

    assert len(result.fields) == 1
    assert result.fields[0].variable == "etp"


def test_a_second_file_over_the_same_box_is_read_not_taken_from_the_cache(
    tmp_path: Path,
) -> None:
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    (tmp_path / "rcp45").mkdir()
    (tmp_path / "rcp85").mkdir()
    first = _write_drias_file(tmp_path / "rcp45", value=2.0e-5)
    second = _write_drias_file(tmp_path / "rcp85", value=8.0e-5)
    bbox = _bbox_around_native_cell(5, 5)
    catalog = DataCatalogDuckDB(tmp_path / "cache.duckdb")

    def mean_precipitation(path: Path) -> float:
        config = PrecipitationConfig(
            sources=[PrecipitationSourceConfig(source="explore2", path=path, extent="watershed")]
        )
        manager = PrecipitationManager(
            config=config,
            catalog=catalog,
            project_extent=bbox,
            project_period=None,
            data_dir=tmp_path / "data" / "precipitation",
        )
        record = manager.load().fields[0]
        return float(np.asarray(record.data["precipitation"].values).mean())

    mean_precipitation(first)

    assert mean_precipitation(second) == pytest.approx(8.0e-5 * 86400.0)
