"""SIM2 EDR client: requests to the GeoSAS service, and the NetCDF it sends back."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hydromodpy.core.io.fetch import HTTPClient
from hydromodpy.data.common.clients.sim2_edr import BASE_URL, Sim2EDRClient


def test_endpoint_is_geosas():
    assert "api.geosas.fr" in BASE_URL
    assert "meteo.data.gouv.fr" not in BASE_URL


@patch("hydromodpy.core.io.fetch.HTTPClient.get")
def test_cube_request_names_the_parameters(mock_get):
    mock_get.return_value = MagicMock(status_code=200, json=lambda: {"ranges": {}})
    client = Sim2EDRClient(
        bbox=(333482, 6794494, 350629, 6813081),
        crs="EPSG:2154",
        date_range="2020-01-01/2020-12-31",
        output_format="CoverageJSON",
        http_client=HTTPClient(),
    )
    client.fetch_cube(parameters=["DRAINC_Q", "T_Q"])

    params = mock_get.call_args.kwargs["params"]
    assert "api.geosas.fr" in mock_get.call_args.args[0]
    assert params["parameter-name"] == "DRAINC_Q,T_Q"
    assert params["crs"] == "EPSG:2154"


@patch("hydromodpy.core.io.fetch.HTTPClient.get")
def test_point_request_names_the_parameter(mock_get):
    mock_get.return_value = MagicMock(status_code=200, json=lambda: {"ranges": {}})
    client = Sim2EDRClient(
        bbox=(0, 0, 1, 1), date_range="2020-01-01/2020-01-02", http_client=HTTPClient()
    )
    client.fetch_point(x=350000.0, y=6780000.0, parameters=["FF_Q"])

    assert mock_get.call_args.kwargs["params"]["parameter-name"] == "FF_Q"


def test_a_temporary_netcdf_that_cannot_be_removed_is_not_an_error(tmp_path, monkeypatch):
    import xarray as xr

    source = tmp_path / "cube.nc"
    xr.Dataset({"v": ("x", [1.0, 2.0])}).to_netcdf(source)
    real_unlink = Path.unlink

    def locked(self: Path, missing_ok: bool = False) -> None:
        if self.suffix == ".nc" and self != source:
            raise OSError("file in use")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", locked)

    dataset = Sim2EDRClient._load_netcdf_from_bytes(source.read_bytes())

    assert float(dataset["v"].sum()) == 3.0
