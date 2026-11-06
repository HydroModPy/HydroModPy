"""The helpers the provider modules share: SIM2 EDR client, Hub'Eau location, BRGM files."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hydromodpy.data.common.clients.hubeau import station_location
from hydromodpy.data.common.clients.sim2_edr import BASE_URL, Sim2EDRClient
from hydromodpy.data.variables.geology.apis.fgeol import bbox_hash, find_fgeol_shp


def test_sim2_endpoint_is_geosas():
    assert "api.geosas.fr" in BASE_URL
    assert "meteo.data.gouv.fr" not in BASE_URL


@patch("hydromodpy.core.io.http_client.HTTPClient.get")
def test_sim2_cube_request_names_the_parameters(mock_get):
    mock_get.return_value = MagicMock(status_code=200, json=lambda: {"ranges": {}})
    client = Sim2EDRClient(
        bbox=(333482, 6794494, 350629, 6813081),
        crs="EPSG:2154",
        date_range="2020-01-01/2020-12-31",
        output_format="CoverageJSON",
    )
    client.fetch_cube(parameters=["DRAINC_Q", "T_Q"])

    params = mock_get.call_args.kwargs["params"]
    assert "api.geosas.fr" in mock_get.call_args.args[0]
    assert params["parameter-name"] == "DRAINC_Q,T_Q"
    assert params["crs"] == "EPSG:2154"


@patch("hydromodpy.core.io.http_client.HTTPClient.get")
def test_sim2_point_request_names_the_parameter(mock_get):
    mock_get.return_value = MagicMock(status_code=200, json=lambda: {"ranges": {}})
    client = Sim2EDRClient(bbox=(0, 0, 1, 1), date_range="2020-01-01/2020-01-02")
    client.fetch_point(x=350000.0, y=6780000.0, parameters=["FF_Q"])

    assert mock_get.call_args.kwargs["params"]["parameter-name"] == "FF_Q"


def _meta(info: dict) -> dict:
    return {"name": info.get("name")}


def test_station_location_reads_the_first_row():
    payload = {"data": [{"lon": 1.5, "lat": 48.0, "name": "A"}, {"lon": 9, "lat": 9}]}
    loc = station_location("S1", payload, lon_key="lon", lat_key="lat", metadata=_meta)
    assert (loc.id, loc.x, loc.y, loc.crs) == ("S1", 1.5, 48.0, "EPSG:4326")
    assert loc.metadata == {"name": "A"}


@pytest.mark.parametrize(
    "payload",
    [None, {}, {"data": []}, {"data": [{"lon": None, "lat": 48.0}]}, {"data": [{"lon": 1.0}]}],
)
def test_station_location_is_none_without_coordinates(payload):
    assert station_location("S1", payload, lon_key="lon", lat_key="lat", metadata=_meta) is None


def test_bbox_hash_rounds_to_two_decimals():
    assert bbox_hash((1.001, 2.0, 3.0, 4.0)) == bbox_hash((1.004, 2.0, 3.0, 4.0))
    assert bbox_hash((1.0, 2.0, 3.0, 4.0)) != bbox_hash((1.1, 2.0, 3.0, 4.0))


def test_find_fgeol_shp(tmp_path: Path):
    assert find_fgeol_shp(tmp_path) is None
    shp = tmp_path / "sub" / "x_S_FGEOL_2154.shp"
    shp.parent.mkdir()
    shp.touch()
    assert find_fgeol_shp(tmp_path) == shp


def test_a_temporary_netcdf_that_cannot_be_removed_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
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
