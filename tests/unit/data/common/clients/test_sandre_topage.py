"""The Sandre WFS client answers what the server holds, or raises.

Each test replays one behavior measured on the live service on 2026-09-27:
short pages, an empty page mid-way, a refusal sent with HTTP 200, a page that is
not GeoJSON or not in Lambert-93, missing text sent as ``''``. Only the
transport is canned; the pages are real GeoPackages.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from hydromodpy.core.exceptions import DataRequestError, DataSourceError
from hydromodpy.core.io.fetch import HTTPClient
from hydromodpy.data.common.clients import sandre_topage

TYPENAME = "sa:TronconHydrographique_FXX_Topage2026"
BOX = (346361.0, 6797325.0, 363915.0, 6821726.0)
URN = "urn:ogc:def:crs:EPSG::2154"


@dataclass
class _Reply:
    content: bytes
    status_code: int = 200


@dataclass
class _Server:
    """The replies to hand out, in order, and every query string received."""

    replies: list[_Reply]
    sent: list[dict] = field(default_factory=list)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> _Server:
    from hydromodpy.core.io.fetch import HTTPClient

    canned = _Server(replies=[])

    def _get(_self: object, url: str, **kwargs: object) -> _Reply:
        assert url == sandre_topage.SANDRE_WFS_URL
        params = kwargs.get("params")
        canned.sent.append(dict(params) if isinstance(params, dict) else {})
        return canned.replies.pop(0)

    monkeypatch.setattr(HTTPClient, "get", _get)
    return canned


def _hits(n: int) -> _Reply:
    return _Reply(
        f'<?xml version="1.0"?><wfs:FeatureCollection numberMatched="{n}" numberReturned="0" '
        'xmlns:wfs="http://www.opengis.net/wfs/2.0"/>'.encode()
    )


def _page(tmp_path: Path, gids: list[int], **columns: list[object]) -> _Reply:
    """A GeoJSON page as the server writes it, its ``crs`` member included."""
    frame = gpd.GeoDataFrame(
        {"gid": gids, **columns},
        geometry=[LineString([(350000.0 + i, 6800000.0), (350010.0 + i, 6800010.0)]) for i in gids],
        crs="EPSG:2154",
    )
    path = tmp_path / f"page_{gids[0]}_{len(gids)}.geojson"
    frame.to_file(path, driver="GeoJSON")
    return _Reply(path.read_bytes())


def _empty_page(tmp_path: Path) -> _Reply:
    del tmp_path  # the server sends the same body for every page with no feature
    return _Reply(
        b'{"type": "FeatureCollection", "name": "TronconHydrographique_FXX_Topage2026", '
        b'"crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::2154"}}, '
        b'"features": []}'
    )


def test_empty_page_is_skipped(server: _Server, tmp_path: Path) -> None:
    server.replies = [
        _hits(3),
        _page(tmp_path, [1, 2]),
        _empty_page(tmp_path),
        _page(tmp_path, [3]),
    ]

    frame = sandre_topage.get_features(TYPENAME, BOX, page_size=2, client=HTTPClient())

    assert sorted(frame["gid"]) == [1, 2, 3]


def test_short_total_raises(server: _Server, tmp_path: Path) -> None:
    server.replies = [_hits(5), _page(tmp_path, [1, 2])] + [_empty_page(tmp_path)] * 3

    with pytest.raises(DataSourceError, match="announced 5 features"):
        sandre_topage.get_features(TYPENAME, BOX, page_size=2, client=HTTPClient())


def test_repeated_feature_raises(server: _Server, tmp_path: Path) -> None:
    server.replies = [_hits(2), _page(tmp_path, [7]), _page(tmp_path, [7])]

    with pytest.raises(DataSourceError, match="repeated"):
        sandre_topage.get_features(TYPENAME, BOX, page_size=1, client=HTTPClient())


def test_empty_box_asks_no_page(server: _Server) -> None:
    server.replies = [_hits(0)]

    frame = sandre_topage.get_features(TYPENAME, BOX, page_size=10, client=HTTPClient())

    assert frame.empty
    assert str(frame.crs) == "EPSG:2154"
    assert len(server.sent) == 1


def test_exception_report_raises(server: _Server) -> None:
    server.replies = [
        _Reply(
            b'<?xml version="1.0"?><ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1">'
            b"<ows:Exception><ows:ExceptionText>TYPENAME Nope does not exist"
            b"</ows:ExceptionText></ows:Exception></ows:ExceptionReport>"
        )
    ]

    with pytest.raises(DataSourceError, match="TYPENAME Nope does not exist"):
        sandre_topage.count_features(TYPENAME, BOX, client=HTTPClient())


def test_mapserver_error_raises(server: _Server) -> None:
    server.replies = [
        _hits(1),
        _Reply(b"<HTML><BODY>MapServer Message: msOWSPreParseRequest(): OWS error.</BODY></HTML>"),
    ]

    with pytest.raises(DataSourceError, match="msOWSPreParseRequest"):
        sandre_topage.get_features(TYPENAME, BOX, page_size=10, client=HTTPClient())


def test_a_page_that_is_not_geojson_raises(server: _Server) -> None:
    server.replies = [_hits(1), _Reply(b"PK\x03\x04 a zip, as the service sent until 2026-11")]

    with pytest.raises(DataSourceError, match="not a JSON object"):
        sandre_topage.get_features(TYPENAME, BOX, page_size=10, client=HTTPClient())


def test_a_page_in_another_crs_raises(server: _Server, tmp_path: Path) -> None:
    # A GeoJSON without its crs member reads as WGS84, which would misplace every reach.
    body = _page(tmp_path, [1]).content.replace(b'"crs"', b'"no_crs"')
    server.replies = [_hits(1), _Reply(body)]

    with pytest.raises(DataSourceError, match="not in EPSG:2154"):
        sandre_topage.get_features(TYPENAME, BOX, page_size=10, client=HTTPClient())


def test_the_pages_are_asked_as_geojson(server: _Server, tmp_path: Path) -> None:
    server.replies = [_hits(1), _page(tmp_path, [1])]

    frame = sandre_topage.get_features(TYPENAME, BOX, page_size=10, client=HTTPClient())

    assert server.sent[1]["OUTPUTFORMAT"] == "geojson" and frame.crs == "EPSG:2154"


def test_http_error_raises(server: _Server) -> None:
    server.replies = [_Reply(b"Service Unavailable", status_code=503)]

    with pytest.raises(DataSourceError, match="HTTP 503"):
        sandre_topage.count_features(TYPENAME, BOX, client=HTTPClient())


def test_missing_text_is_none(server: _Server, tmp_path: Path) -> None:
    server.replies = [_hits(2), _page(tmp_path, [1, 2], TopoOH=["", "la Truite"])]

    frame = sandre_topage.get_features(TYPENAME, BOX, page_size=10, client=HTTPClient())

    assert frame.sort_values("gid")["TopoOH"].tolist() == [None, "la Truite"]


def test_overseas_layer_refused(server: _Server) -> None:
    with pytest.raises(DataRequestError, match="REU"):
        sandre_topage.count_features(
            "sa:TronconHydrographique_REU_Topage2026", BOX, client=HTTPClient()
        )

    assert server.sent == []
