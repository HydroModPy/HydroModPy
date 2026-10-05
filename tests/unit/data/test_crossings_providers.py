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
import math
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import DataSourceError
from hydromodpy.data.variables.crossings import records
from hydromodpy.data.variables.crossings.apis import bdtopo, roe, wfs

SAMPLES = Path(__file__).parent / "samples" / "crossings"
URN = "urn:ogc:def:crs:EPSG::2154"
BOX = (340000.0, 6800000.0, 350000.0, 6810000.0)


def _features(name: str) -> list[dict]:
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))["features"]


# --- BD TOPO ----------------------------------------------------------------


def test_bdtopo_kinds_follow_the_layer_and_the_position_to_the_ground() -> None:
    frame = bdtopo.to_records(_features("bdtopo_route.json"), _features("bdtopo_voie_ferree.json"))

    assert list(frame.columns) == [*records.ATTRIBUTES, "geometry"]
    assert frame.crs.to_epsg() == 2154
    # Six roads: a stair is dropped. Position 0 stays a road, 1 and 2 are bridges.
    assert frame["kind"].tolist() == [
        "road",
        "road",
        "road",
        "bridge",
        "bridge",
        # Four rails: ground, above the ground, and two metro segments below it.
        "railway",
        "bridge",
        "other",
        "other",
    ]
    assert set(frame["source"]) == {"bdtopo"}
    assert frame["drop_m"].isna().all()


def test_bdtopo_geometries_are_two_dimensional_lines() -> None:
    frame = bdtopo.to_records(_features("bdtopo_route.json"), _features("bdtopo_voie_ferree.json"))

    assert not frame.geometry.has_z.any()
    assert set(frame.geom_type) == {"LineString"}


def test_bdtopo_a_road_takes_the_name_a_side_gives() -> None:
    frame = bdtopo.to_records(_features("bdtopo_route.json"), [])

    assert frame["name"].iloc[0] == "R DE RENNES"
    assert frame["name"].iloc[1] == ""


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


def test_roe_keeps_the_existing_obstacles_and_names_their_kind() -> None:
    rows = roe.parse_page((SAMPLES / "roe_obstacles.gml").read_bytes())
    frame = roe.to_records(rows)

    assert len(rows) == 11
    # Destroyed obstacles go: five existing ones remain.
    assert frame["kind"].tolist() == ["dam", "dam", "dam", "weir", "weir"]
    assert list(frame.columns) == [*records.ATTRIBUTES, "geometry"]
    assert frame.crs.to_epsg() == 2154
    assert set(frame["source"]) == {"roe"}


def test_roe_reads_the_drop_in_metres_and_leaves_nan_when_unknown() -> None:
    frame = roe.to_records(roe.parse_page((SAMPLES / "roe_obstacles.gml").read_bytes()))

    by_name = dict(zip(frame["name"], frame["drop_m"], strict=True))
    assert by_name["Etang du Saut du Bois"] == 2.5
    assert by_name["Ecluse de Cicé"] == 1.8
    assert math.isnan(by_name["Etang de Hédé"])


def test_roe_the_point_is_the_gml_position_easting_first() -> None:
    frame = roe.to_records(roe.parse_page((SAMPLES / "roe_obstacles.gml").read_bytes()))

    point = frame.geometry.iloc[0]
    assert (round(point.x, 3), round(point.y, 3)) == (344213.703, 6809625.189)


@pytest.mark.parametrize(
    ("code", "kind"),
    [
        ("1.1", "dam"),
        ("1.1.7", "dam"),
        ("1.2", "weir"),
        ("1.2.1", "weir"),
        ("1.2.X", "weir"),
        ("1.4", "weir"),
        ("1.4.1", "weir"),
        ("1.3", "other"),
        ("1.5", "other"),
        ("1.6", "other"),
        ("", "other"),
        (None, "other"),
    ],
)
def test_roe_kind_is_read_from_the_first_two_levels_of_the_code(
    code: str | None, kind: str
) -> None:
    assert roe.kind_of(code) == kind


def test_the_roe_sample_holds_an_obstacle_without_a_type_code() -> None:
    rows = roe.parse_page((SAMPLES / "roe_obstacles.gml").read_bytes())

    assert "" in {row["CdTypeOuvrage"] for row in rows}


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
    from hydromodpy.core.io.http_client import HTTPClient

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


def _source(**fields: object):
    from types import SimpleNamespace

    return SimpleNamespace(page_size=2, force_refresh=False, **fields)


def test_bdtopo_pages_by_count_and_sorts_every_page(server: _Server) -> None:
    roads = _features("bdtopo_route.json")
    server.total = len(roads)
    server.pages = [_json_page(roads[i : i + 2]) for i in range(0, len(roads), 2)]

    layer = [f for page in bdtopo.layer_pages(bdtopo.ROAD_LAYER, BOX, 2) for f in page]

    assert [f["id"] for f in layer] == [f["id"] for f in roads]
    hits, *pages = server.sent
    assert hits["RESULTTYPE"] == "hits"
    assert [page["STARTINDEX"] for page in pages] == ["0", "2", "4"]
    assert {page["COUNT"] for page in pages} == {"2"}
    assert {page["SORTBY"] for page in pages} == {"cleabs"}
    assert {page["outputFormat"] for page in pages} == {"application/json"}
    assert hits["url"] == bdtopo.WFS_URL


def test_the_box_is_sent_with_its_crs_in_the_same_urn_as_srsname(server: _Server) -> None:
    server.total = 0

    list(bdtopo.layer_pages(bdtopo.ROAD_LAYER, BOX, 2))

    sent = server.sent[0]
    assert sent["BBOX"] == f"340000.0,6800000.0,350000.0,6810000.0,{URN}"
    assert sent["SRSNAME"] == URN


def test_roe_asks_the_sandre_layer_in_gml(server: _Server) -> None:
    server.total = 0

    list(roe.fetch_pages(_source(), bbox=BOX, context=None))  # type: ignore[arg-type]

    assert server.sent[0]["url"] == roe.WFS_URL
    assert server.sent[0]["TYPENAMES"] == "sa:ObstEcoul_FXX"


def test_a_box_without_a_feature_gives_no_page(server: _Server) -> None:
    server.total = 0

    pages = list(roe.fetch_pages(_source(), bbox=BOX, context=None))  # type: ignore[arg-type]

    assert pages == []


def test_pages_that_do_not_add_up_to_the_total_are_refused(server: _Server) -> None:
    roads = _features("bdtopo_route.json")
    server.total = len(roads) + 1
    server.pages = [_json_page(roads[i : i + 2]) for i in range(0, len(roads), 2)]
    server.pages += [_json_page([])] * 3

    with pytest.raises(DataSourceError, match="announced"):
        list(bdtopo.layer_pages(bdtopo.ROAD_LAYER, BOX, 2))


def test_a_feature_served_twice_is_refused(server: _Server) -> None:
    roads = _features("bdtopo_route.json")[:2]
    server.total = 4
    server.pages = [_json_page(roads), _json_page(roads)]

    with pytest.raises(DataSourceError, match="repeated"):
        list(bdtopo.layer_pages(bdtopo.ROAD_LAYER, BOX, 2))


def test_a_refusal_sent_with_http_200_is_raised_by_name(server: _Server) -> None:
    server.refuse_with = (
        b'<?xml version="1.0"?><ows:ExceptionReport>no such layer</ows:ExceptionReport>'
    )

    with pytest.raises(DataSourceError, match="refused a request on 'BDTOPO_V3:troncon_de_route'"):
        list(bdtopo.layer_pages(bdtopo.ROAD_LAYER, BOX, 2))


def test_bdtopo_asks_only_the_attributes_it_reads(server: _Server) -> None:
    roads = _features("bdtopo_route.json")
    server.total = len(roads)
    server.pages = [_json_page(roads[i : i + 2]) for i in range(0, len(roads), 2)]

    list(bdtopo.layer_pages(bdtopo.ROAD_LAYER, BOX, 2))
    list(bdtopo.layer_pages(bdtopo.RAILWAY_LAYER, BOX, 2))

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


def test_a_page_is_handed_out_before_the_next_one_is_asked(server: _Server) -> None:
    roads = _features("bdtopo_route.json")
    server.total = len(roads)
    server.pages = [_json_page(roads[i : i + 2]) for i in range(0, len(roads), 2)]

    pages = bdtopo.layer_pages(bdtopo.ROAD_LAYER, BOX, 2)
    first = next(pages)

    assert len(first) == 2
    # The hits request and the first page: the second page is not asked for yet.
    assert [entry.get("STARTINDEX") for entry in server.sent] == [None, "0"]


def test_the_pages_of_bdtopo_become_records_one_by_one(server: _Server) -> None:
    roads = _features("bdtopo_route.json")
    server.total = len(roads)
    server.pages = [_json_page(roads[i : i + 2]) for i in range(0, len(roads), 2)]

    frames = list(bdtopo.fetch_pages(_source(), bbox=BOX, context=None))  # type: ignore[arg-type]

    # Three pages of two features for each of the two layers, the server answering both
    # with the same sample.
    assert len(frames) == 6
    assert all(len(frame) <= 2 for frame in frames)
