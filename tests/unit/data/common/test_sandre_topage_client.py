"""The Sandre WFS client answers what the server holds, or raises.

Each test replays one behavior measured on the live service on 2026-09-27:
short pages, an empty page mid-way, a refusal sent with HTTP 200, a zip whose
member is named ``%TYPENAME%.gpkg``, missing text sent as ``''``. Only the
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
    """A GPKG page zipped as the server zips it, member name included."""
    frame = gpd.GeoDataFrame(
        {"gid": gids, **columns},
        geometry=[LineString([(350000.0 + i, 6800000.0), (350010.0 + i, 6800010.0)]) for i in gids],
        crs="EPSG:2154",
    )
    path = tmp_path / f"page_{gids[0] if gids else 'empty'}_{len(gids)}.gpkg"
    frame.to_file(path, driver="GPKG")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("%TYPENAME%.gpkg", path.read_bytes())
    return _Reply(buffer.getvalue())


def _empty_page(tmp_path: Path) -> _Reply:
    frame = gpd.GeoDataFrame({"gid": []}, geometry=[], crs="EPSG:2154")
    path = tmp_path / f"empty_{len(list(tmp_path.iterdir()))}.gpkg"
    frame.to_file(path, driver="GPKG", geometry_type="LineString")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("%TYPENAME%.gpkg", path.read_bytes())
    return _Reply(buffer.getvalue())


def test_an_empty_page_before_the_total_is_walked_past(server: _Server, tmp_path: Path) -> None:
    server.replies = [
        _hits(3),
        _page(tmp_path, [1, 2]),
        _empty_page(tmp_path),
        _page(tmp_path, [3]),
    ]

    frame = sandre_topage.get_features(TYPENAME, BOX, page_size=2, client=HTTPClient())

    assert sorted(frame["gid"]) == [1, 2, 3]


def test_pages_that_never_reach_the_total_raise(server: _Server, tmp_path: Path) -> None:
    server.replies = [_hits(5), _page(tmp_path, [1, 2])] + [_empty_page(tmp_path)] * 3

    with pytest.raises(DataSourceError, match="announced 5 features"):
        sandre_topage.get_features(TYPENAME, BOX, page_size=2, client=HTTPClient())


def test_a_feature_sent_twice_raises(server: _Server, tmp_path: Path) -> None:
    server.replies = [_hits(2), _page(tmp_path, [7]), _page(tmp_path, [7])]

    with pytest.raises(DataSourceError, match="repeated"):
        sandre_topage.get_features(TYPENAME, BOX, page_size=1, client=HTTPClient())


def test_no_feature_in_the_box_asks_for_no_page(server: _Server) -> None:
    server.replies = [_hits(0)]

    frame = sandre_topage.get_features(TYPENAME, BOX, page_size=10, client=HTTPClient())

    assert frame.empty
    assert str(frame.crs) == "EPSG:2154"
    assert len(server.sent) == 1


def test_an_exception_report_sent_with_http_200_is_raised(server: _Server) -> None:
    server.replies = [
        _Reply(
            b'<?xml version="1.0"?><ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1">'
            b"<ows:Exception><ows:ExceptionText>TYPENAME Nope does not exist"
            b"</ows:ExceptionText></ows:Exception></ows:ExceptionReport>"
        )
    ]

    with pytest.raises(DataSourceError, match="TYPENAME Nope does not exist"):
        sandre_topage.count_features(TYPENAME, BOX, client=HTTPClient())


def test_a_mapserver_error_page_is_raised(server: _Server) -> None:
    server.replies = [
        _hits(1),
        _Reply(b"<HTML><BODY>MapServer Message: msOWSPreParseRequest(): OWS error.</BODY></HTML>"),
    ]

    with pytest.raises(DataSourceError, match="msOWSPreParseRequest"):
        sandre_topage.get_features(TYPENAME, BOX, page_size=10, client=HTTPClient())


def test_a_page_that_is_not_a_zip_is_raised(server: _Server) -> None:
    server.replies = [_hits(1), _Reply(b'{"type": "FeatureCollection", "features": []}')]

    with pytest.raises(DataSourceError, match="not a zip"):
        sandre_topage.get_features(TYPENAME, BOX, page_size=10, client=HTTPClient())


def test_an_http_error_is_raised(server: _Server) -> None:
    server.replies = [_Reply(b"Service Unavailable", status_code=503)]

    with pytest.raises(DataSourceError, match="HTTP 503"):
        sandre_topage.count_features(TYPENAME, BOX, client=HTTPClient())


def test_missing_text_arrives_as_none(server: _Server, tmp_path: Path) -> None:
    server.replies = [_hits(2), _page(tmp_path, [1, 2], TopoOH=["", "la Truite"])]

    frame = sandre_topage.get_features(TYPENAME, BOX, page_size=10, client=HTTPClient())

    assert frame.sort_values("gid")["TopoOH"].tolist() == [None, "la Truite"]


def test_an_overseas_layer_is_refused_before_any_request(server: _Server) -> None:
    with pytest.raises(DataRequestError, match="REU"):
        sandre_topage.count_features(
            "sa:TronconHydrographique_REU_Topage2026", BOX, client=HTTPClient()
        )

    assert server.sent == []
