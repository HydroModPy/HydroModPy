"""The ETP of ``[data.etp] formula``, computed on the grid of the loaded temperature."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.model.forcing.etp_computed import cell_latitudes, computed_etp
from hydromodpy.model.soil.etp import oudin


def temperature_result(crs: str | None = "EPSG:2154") -> LoadResult:
    days = pd.date_range("2021-06-01", periods=5, freq="D").values
    x = np.array([350000.0, 358000.0])
    y = np.array([6790000.0, 6782000.0])
    values = np.full((len(days), y.size, x.size), 15.0)
    dataset = xr.Dataset(
        {"temperature": (("time", "y", "x"), values)}, coords={"time": days, "y": y, "x": x}
    )
    record = FieldRecord(
        variable="temperature",
        source="sim2",
        unit="degC",
        data=dataset,
        bbox=(350000.0, 6782000.0, 358000.0, 6790000.0),
        crs=crs,
        date_start=pd.Timestamp(days[0]),
        date_end=pd.Timestamp(days[-1]),
    )
    return LoadResult(fields=[record])


def test_the_cells_of_brittany_sit_near_48_degrees_north():
    latitude = cell_latitudes(np.array([350000.0]), np.array([6790000.0]), "EPSG:2154")
    assert latitude[0] == pytest.approx(48.1, abs=0.2)


def test_the_formula_etp_is_a_grid_of_etp_named_after_its_formula():
    result = computed_etp(temperature_result(), "oudin")

    record = result.fields[0]
    assert record.variable == "etp"
    assert record.source == "oudin"
    assert record.unit == "mm/day"
    grid = record.data["etp"].values
    assert grid.shape == (5, 2, 2)
    latitude = cell_latitudes(np.array([350000.0]), np.array([6790000.0]), "EPSG:2154")
    days = pd.date_range("2021-06-01", periods=5, freq="D").values.astype("datetime64[D]")
    expected = oudin(np.full((5, 1), 15.0), latitude, days)[:, 0]
    np.testing.assert_allclose(grid[:, 0, 0], expected)


@pytest.mark.parametrize(
    ("temperature", "message"),
    [
        pytest.param(None, "loaded nothing", id="no temperature"),
        pytest.param(LoadResult(), "loaded nothing", id="empty"),
    ],
)
def test_a_formula_without_temperature_is_refused(temperature, message):
    with pytest.raises(DataContractViolation, match=message):
        computed_etp(temperature, "oudin")


def test_a_grid_without_crs_is_refused():
    with pytest.raises(DataContractViolation, match="declares no CRS"):
        computed_etp(temperature_result(crs=None), "hamon")
