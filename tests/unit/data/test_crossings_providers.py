"""The two crossings providers parse what the live services answered.

The samples under ``samples/crossings/`` are real answers recorded on
2026-10-05 over the upper Ille (x 340000 to 350000, y 6800000 to 6810000), cut
to a few features. The Geoplateforme holds no railway in that box, so the rail
sample comes from Rennes; the ROE holds no existing bridge there either, so
three obstacles come from the 50 km box around it. Only the transport is
canned.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import DataSourceError
from hydromodpy.core.io.fetch import HTTPClient
from hydromodpy.data.variables.crossings.apis import bdtopo, roe, wfs

SAMPLES = Path(__file__).parent / "samples" / "crossings"
URN = "urn:ogc:def:crs:EPSG::2154"
BOX = (340000.0, 6800000.0, 350000.0, 6810000.0)


def _features(name: str) -> list[dict]:
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))["features"]


# --- BD TOPO ----------------------------------------------------------------


def test_bdtopo_skips_what_is_not_in_service_or_not_real() -> None:
    template = _features("bdtopo_route.json")[0]

    def variant(**props: object) -> dict:
        return {**template, "properties": {**template["properties"], **props}}

    frame = bdtopo.to_records(
        [
            variant(),
            variant(etat_de_l_objet="En construction"),
            variant(fictif=True),
            variant(nature="Bac ou liaison maritime"),
            variant(position_par_rapport_au_sol=None),
        ],
        [],
    )

    assert frame["kind"].tolist() == ["road", "road"]


# --- ROE --------------------------------------------------------------------


# --- The WFS paging ---------------------------------------------------------


@dataclass
class _Reply:
    content: bytes
    status_code: int = 200


@dataclass
class _Server:
    """Answers a hits request with the total and a page request with its slice."""

    pages: list[bytes]
    total: int
    sent: list[dict] = field(default_factory=list)
    refuse_with: bytes | None = None


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> _Server:
    from hydromodpy.core.io.fetch import HTTPClient

    canned = _Server(pages=[], total=0)

    def _get(_self: object, url: str, **kwargs: object) -> _Reply:
        params = dict(kwargs["params"])  # type: ignore[arg-type]
        canned.sent.append({"url": url, **params})
        if canned.refuse_with is not None:
            return _Reply(canned.refuse_with)
        if params.get("RESULTTYPE") == "hits":
            return _Reply(f'<wfs:FeatureCollection numberMatched="{canned.total}"/>'.encode())
        return _Reply(canned.pages[int(params["STARTINDEX"]) // int(params["COUNT"])])

    monkeypatch.setattr(HTTPClient, "get", _get)
    return canned


def _json_page(features: list[dict]) -> bytes:
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


def test_roe_asks_the_sandre_layer_in_gml(server: _Server) -> None:
    server.total = 0

    list(roe.fetch_pages(bbox=BOX, page_size=2, client=HTTPClient()))

    assert server.sent[0]["url"] == roe.WFS_URL
    assert server.sent[0]["TYPENAMES"] == "sa:ObstEcoul_FXX"


def test_a_box_without_a_feature_gives_no_page(server: _Server) -> None:
    server.total = 0

    pages = list(roe.fetch_pages(bbox=BOX, page_size=2, client=HTTPClient()))

    assert pages == []


def test_pages_that_do_not_add_up_to_the_total_are_refused(server: _Server) -> None:
    roads = _features("bdtopo_route.json")
    server.total = len(roads) + 1
    server.pages = [_json_page(roads[i : i + 2]) for i in range(0, len(roads), 2)]
    server.pages += [_json_page([])] * 3

    with pytest.raises(DataSourceError, match="announced"):
        list(bdtopo.layer_pages(bdtopo.ROAD_LAYER, BOX, 2, client=HTTPClient()))


def test_a_feature_served_twice_is_refused(server: _Server) -> None:
    roads = _features("bdtopo_route.json")[:2]
    server.total = 4
    server.pages = [_json_page(roads), _json_page(roads)]

    with pytest.raises(DataSourceError, match="repeated"):
        list(bdtopo.layer_pages(bdtopo.ROAD_LAYER, BOX, 2, client=HTTPClient()))


def test_a_refusal_sent_with_http_200_is_raised_by_name(server: _Server) -> None:
    server.refuse_with = (
        b'<?xml version="1.0"?><ows:ExceptionReport>no such layer</ows:ExceptionReport>'
    )

    with pytest.raises(DataSourceError, match="refused a request on 'BDTOPO_V3:troncon_de_route'"):
        list(bdtopo.layer_pages(bdtopo.ROAD_LAYER, BOX, 2, client=HTTPClient()))


def test_bdtopo_asks_only_the_attributes_it_reads(server: _Server) -> None:
    roads = _features("bdtopo_route.json")
    server.total = len(roads)
    server.pages = [_json_page(roads[i : i + 2]) for i in range(0, len(roads), 2)]

    list(bdtopo.layer_pages(bdtopo.ROAD_LAYER, BOX, 2, client=HTTPClient()))
    list(bdtopo.layer_pages(bdtopo.RAILWAY_LAYER, BOX, 2, client=HTTPClient()))

    asked = {
        entry["TYPENAMES"]: entry["PROPERTYNAME"].split(",")
        for entry in server.sent
        if "PROPERTYNAME" in entry
    }
    assert "geometrie" in asked[bdtopo.ROAD_LAYER]
    assert "fictif" in asked[bdtopo.ROAD_LAYER]
    assert "geometrie" in asked[bdtopo.RAILWAY_LAYER]
    assert "fictif" not in asked[bdtopo.RAILWAY_LAYER]
    assert "date_creation" not in asked[bdtopo.ROAD_LAYER]


def test_the_pages_of_bdtopo_become_records_one_by_one(server: _Server) -> None:
    roads = _features("bdtopo_route.json")
    server.total = len(roads)
    server.pages = [_json_page(roads[i : i + 2]) for i in range(0, len(roads), 2)]

    frames = list(bdtopo.fetch_pages(bbox=BOX, page_size=2, client=HTTPClient()))

    # Three pages of two features for each of the two layers, the server answering both
    # with the same sample.
    assert len(frames) == 6
    assert all(len(frame) <= 2 for frame in frames)
