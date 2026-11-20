"""The data API client answers 404 with None, and no other error reaches back.

The Hub'Eau adapters read their stations through ``get_json``. A station the
service does not hold is a ``None``. Any other status code and any network
failure is refused, because a body that is not data is as wrong as a station
that answers empty in silence.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from hydromodpy.core.exceptions import DataSourceError
from hydromodpy.core.io.fetch import HTTPClient, NetworkError
from hydromodpy.data.common import api_client

URL = "https://hubeau.example/api/v1"


def reply(status: int) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status
    resp.json.return_value = {"data": [], "count": 0}
    return resp


def test_a_404_is_none():
    client = HTTPClient(max_retries=0)
    with patch.object(client._session, "request", return_value=reply(404)):
        assert api_client.get_json(client, URL) is None


REFUSED_STATUS = [400, 403, 409, 418, 429, 500, 502, 503, 504]


@pytest.mark.parametrize("status", REFUSED_STATUS)
def test_an_http_status_that_is_not_404_raises(status):
    client = HTTPClient(max_retries=0)
    with patch.object(client._session, "request", return_value=reply(status)):
        with pytest.raises((DataSourceError, NetworkError)):
            api_client.get_json(client, URL, timeout=1)


def test_a_network_exception_is_a_data_source_error(monkeypatch):
    client = HTTPClient(max_retries=0)

    def reset(*_a, **_k):
        raise requests.exceptions.ConnectionError("reset by peer")

    monkeypatch.setattr(client._session, "request", reset)
    with pytest.raises(DataSourceError):
        api_client.get_json(client, URL)
