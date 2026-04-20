"""Smoke tests for the INRAE SIM2 client (no network calls).

Verifies:
- Endpoint points to the INRAE GeoSAS hosting, not ``meteo.data.gouv.fr``.
- Variable name mapping matches the canonical SIM2 codes.
- HTTP calls are routed through ``requests.get`` so tests can mock them.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hydromodpy.data.common.clients import sim2_inrae
from hydromodpy.data.common.clients.sim2_inrae import (
    INRAE_SIM2_BASE_URL,
    REVERSE_VAR_MAPPING,
    VAR_MAPPING,
    Sim2InraeClient,
    sim2_to_user_names,
    user_names_to_sim2,
)


def test_inrae_endpoint_is_geosas():
    assert "api.geosas.fr" in INRAE_SIM2_BASE_URL
    assert "meteo.data.gouv.fr" not in INRAE_SIM2_BASE_URL


def test_var_mapping_round_trips():
    assert REVERSE_VAR_MAPPING == {v: k for k, v in VAR_MAPPING.items()}


def test_user_names_to_sim2_basic():
    assert user_names_to_sim2("recharge") == ["DRAINC_Q"]
    assert user_names_to_sim2(["temperature", "wind"]) == ["T_Q", "FF_Q"]


def test_user_names_to_sim2_passthrough_unknown():
    assert user_names_to_sim2("foo") == ["foo"]


def test_user_names_to_sim2_comma_split():
    result = user_names_to_sim2("recharge,temperature")
    assert result == ["DRAINC_Q", "T_Q"]


def test_sim2_to_user_names_inverse():
    assert sim2_to_user_names("DRAINC_Q,T_Q") == ["recharge", "temperature"]


@patch("hydromodpy.data.common.clients.sim2_edr.requests.get")
def test_fetch_cube_uses_inrae_url_and_translates_names(mock_get):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"ranges": {}}
    mock_get.return_value = resp

    client = Sim2InraeClient(
        bbox=(333482, 6794494, 350629, 6813081),
        crs="EPSG:2154",
        date_range="2020-01-01/2020-12-31",
        output_format="CoverageJSON",
    )
    client.fetch_cube(parameters=["recharge", "temperature"])

    assert mock_get.call_count == 1
    called_url = mock_get.call_args.args[0]
    called_params = mock_get.call_args.kwargs["params"]
    assert "api.geosas.fr" in called_url
    assert called_params["parameter-name"] == "DRAINC_Q,T_Q"
    assert called_params["crs"] == "EPSG:2154"


@patch("hydromodpy.data.common.clients.sim2_edr.requests.get")
def test_fetch_point_translates_names(mock_get):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"ranges": {}}
    mock_get.return_value = resp

    client = Sim2InraeClient(
        bbox=(0, 0, 1, 1), date_range="2020-01-01/2020-01-02",
    )
    client.fetch_point(x=350000.0, y=6780000.0, parameters=["wind"])

    called_params = mock_get.call_args.kwargs["params"]
    assert called_params["parameter-name"] == "FF_Q"
    assert "api.geosas.fr" in mock_get.call_args.args[0]


def test_module_re_exports_client_class():
    assert hasattr(sim2_inrae, "Sim2InraeClient")
    assert hasattr(sim2_inrae, "INRAE_SIM2_BASE_URL")
