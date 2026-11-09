"""The data API client answers 404 with None, and no other error reaches back.

The four Hub'Eau adapters (hydrometry, piezometry, intermittency, quality)
read their stations through :func:`hydromodpy.data.common.api_client.get_json`.
A station the service does not hold is a ``None``, whatever the client asked
for, and nothing but the 404 is ever read as empty : the other codes and the
network failures are refused, because a response body that is not data is as
wrong as a station that answers empty in silence.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from hydromodpy.core.exceptions import DataSourceError
from hydromodpy.core.io.fetch import HTTPClient, NetworkError
from hydromodpy.data.common import api_client


def _client() -> HTTPClient:
    return HTTPClient(max_retries=0)


def _response(status: int) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status
    resp.json.return_value = {"data": [], "count": 0}
    return resp


@pytest.mark.parametrize("status", [400, 403, 409, 418, 429, 500, 502, 503, 504])
def test_an_http_status_that_is_not_404_raises(status: int) -> None:
    resp = _response(status)
    client = _client()
    with patch.object(client._session, "request", return_value=resp):
        with pytest.raises((DataSourceError, NetworkError)):
            api_client.get_json(client, "https://hubeau.example/api/v1", timeout=1)


def test_a_404_is_none() -> None:
    resp = _response(404)
    client = _client()
    with patch.object(client._session, "request", return_value=resp):
        assert api_client.get_json(client, "https://hubeau.example/api/v1") is None


def test_a_network_exception_quits_as_a_data_source_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()

    def raise_no_response(*_a: object, **_k: object) -> None:
        raise requests.exceptions.ConnectionError("reset by peer")

    monkeypatch.setattr(client._session, "request", raise_no_response)
    with pytest.raises(DataSourceError):
        api_client.get_json(client, "https://hubeau.example/api/v1")
