"""Conformance suite for the data-source port, run against every source.

The port is only worth its name if adapters that agree on nothing else answer
the same questions the same way, so the six sources parametrized here
were picked for how much they disagree:

================== ============ ============= ========= ==============
source             payload kind extent CRS    period    writes out_dir
================== ============ ============= ========= ==============
hubeau-piezometry  ``points``   EPSG:4326     required  no
bdtopage           ``features`` EPSG:4326     refused   no
ign-bdalti         ``files``    **EPSG:2154** refused   **yes**
sim2-precipitation ``fields``   **EPSG:2154** required  no
================== ============ ============= ========= ==============

Two CRS, all four payload kinds, both values of ``PeriodNeed`` and both answers
on writing. A member that only makes sense for one of them cannot survive this
file, and :func:`test_the_suite_spans_the_vocabularies` fails if a future edit
collapses that spread.

Two layers, and why both are needed
-----------------------------------
**Layer A** records the provider entry point each adapter delegates to and
reads the arguments off it. It is uniform over the six sources and it is
where the declarations are compared against a real call. A source that reached
the network behind its own provider function would be caught by
the ``no_network`` fixture, which makes every transport of this tree raise.

**Layer B** lets the real adapter run all the way to the wire with only the
HTTP transport stubbed, and reads the bounding box out of the query string that
was about to be sent. Layer A alone would prove the adapter passes *something*
to a function; Layer B proves the reprojected metres are what the provider
receives. It covers ``bdtopage`` and ``hubeau``, which both go through
``hydromodpy.core.io.http_client.HTTPClient.request``.

``ign-bdalti`` has no Layer B row, and not by omission: its downloader builds
its own ``requests.Session`` instead of the shared client
(``geoplateforme_download.py:299``), and reaching the wire would mean
downloading and extracting a 7z archive. What replaces it is stronger than a
stub -- ``test_reprojection_is_what_makes_the_request_answerable`` runs the
real department resolver on both the caller's box and the reprojected one, and
shows the first resolves nothing at all.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.core.exceptions import (
    DataCapabilityError,
    DataProductError,
    DataRequestError,
)
from hydromodpy.data.source import (
    ALL_PAYLOAD_KINDS,
    ALL_PERIOD_NEEDS,
    ALL_SELECTORS,
    SOURCE_MEMBERS,
    BdTopageSource,
    DataSource,
    EuHydroSource,
    Extent,
    FetchRequest,
    FetchResult,
    HubeauPiezometrySource,
    IgnDemSource,
    OsmSource,
    Period,
    Sim2PrecipitationSource,
    missing_source_members,
    registry,
)

pyproj = pytest.importorskip("pyproj")

# A basin-sized box over eastern Brittany, in the CRS no source of this suite
# declares: every adapter has to convert it, one of them by 300 kilometres.
CALLER_EXTENT = Extent(xmin=-2.0, ymin=48.0, xmax=-1.5, ymax=48.4, crs="EPSG:4326")
CALLER_EXTENT_L93 = Extent(
    xmin=317000.0, ymin=6780000.0, xmax=354000.0, ymax=6826000.0, crs="EPSG:2154"
)
PERIOD = Period(start=datetime(2020, 1, 1), end=datetime(2020, 3, 31))


def _expected_bbox(extent: Extent, crs: str) -> tuple[float, float, float, float]:
    """Reproject with pyproj directly, so the port is not its own reference."""
    source = pyproj.CRS.from_user_input(extent.crs)
    target = pyproj.CRS.from_user_input(crs)
    if source.equals(target):
        return extent.bbox
    transformer = pyproj.Transformer.from_crs(source, target, always_xy=True)
    return tuple(transformer.transform_bounds(*extent.bbox))


# --------------------------------------------------------------------------- #
# The sources under test, and where each one delegates
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SourceCase:
    """One source, plus how to intercept the provider call it makes."""

    name: str
    build: Callable[[], Any]
    provider_module: str
    provider_attr: str
    read_bbox: Callable[[tuple, dict], tuple | None]
    canned: Callable[[], Any]

    def request(self, out_dir: Path, *, extent: Extent | None = CALLER_EXTENT) -> FetchRequest:
        """A request this source accepts, with the period it needs and no other."""
        source = self.build()
        period = PERIOD if source.period_need == "required" else None
        return FetchRequest(out_dir=out_dir, extent=extent, period=period)


def _empty_frame() -> Any:
    import geopandas as gpd

    return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")


CASES: tuple[SourceCase, ...] = (
    SourceCase(
        name="hubeau-piezometry",
        build=lambda: HubeauPiezometrySource(product="level"),
        provider_module="hydromodpy.data.variables.piezometry.apis.hubeau",
        provider_attr="fetch",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=list,
    ),
    SourceCase(
        name="bdtopage",
        build=BdTopageSource,
        provider_module="hydromodpy.data.variables.hydrography.apis.bdtopage",
        provider_attr="fetch",
        read_bbox=lambda args, kwargs: args[1] if len(args) > 1 else kwargs.get("bbox_wgs84"),
        canned=_empty_frame,
    ),
    SourceCase(
        name="osm",
        build=OsmSource,
        provider_module="hydromodpy.data.variables.hydrography.apis.osm",
        provider_attr="fetch",
        read_bbox=lambda args, kwargs: args[1] if len(args) > 1 else kwargs.get("bbox_wgs84"),
        canned=_empty_frame,
    ),
    SourceCase(
        name="euhydro",
        build=EuHydroSource,
        provider_module="hydromodpy.data.variables.hydrography.apis.euhydro",
        provider_attr="fetch",
        read_bbox=lambda args, kwargs: args[1] if len(args) > 1 else kwargs.get("bbox_wgs84"),
        canned=_empty_frame,
    ),
    SourceCase(
        name="ign-bdalti",
        build=IgnDemSource,
        provider_module="hydromodpy.data.variables.dem.apis.ign_dem_fr",
        provider_attr="fetch_ign_dem",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=lambda: Path("dem_ign_geoplateforme_bdalti_25m_stub.tif"),
    ),
    SourceCase(
        name="sim2-precipitation",
        build=lambda: Sim2PrecipitationSource(components=("total",)),
        provider_module="hydromodpy.data.variables.precipitation.apis.sim2",
        provider_attr="fetch",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=list,
    ),
)

CASE_PARAMS = [pytest.param(case, id=case.name) for case in CASES]


@dataclass
class ProviderCall:
    """What the adapter handed its provider."""

    args: tuple
    kwargs: dict


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every HTTP transport of this tree raise.

    Anti-vacuity for layer A: an adapter that ignored its provider function and
    reached out on its own would be indistinguishable from one that behaved,
    because the provider stub would record nothing either way.
    """
    import requests

    from hydromodpy.core.io.http_client import HTTPClient

    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a source reached the network outside its provider function")

    monkeypatch.setattr(HTTPClient, "request", _refuse)
    monkeypatch.setattr(requests.Session, "request", _refuse)


@pytest.fixture
def record_provider(monkeypatch: pytest.MonkeyPatch) -> Callable[[SourceCase], list[ProviderCall]]:
    """Replace a case's provider entry point with a recorder."""

    def install(case: SourceCase, *, result: Any | None = None) -> list[ProviderCall]:
        import importlib

        module = importlib.import_module(case.provider_module)
        calls: list[ProviderCall] = []
        payload = case.canned() if result is None else result

        def _record(*args: object, **kwargs: object) -> Any:
            calls.append(ProviderCall(args=args, kwargs=kwargs))
            return payload

        monkeypatch.setattr(module, case.provider_attr, _record)
        return calls

    return install


# --------------------------------------------------------------------------- #
# Anti-vacuity
# --------------------------------------------------------------------------- #


def test_the_suite_covers_every_source_this_build_ships() -> None:
    """An adapter added to the registry and not here would be untested by omission."""
    assert {case.name for case in CASES} == set(registry.builtin_source_ids())


def test_the_suite_spans_the_vocabularies() -> None:
    """A suite of three lookalikes would pass every assertion below for free."""
    sources = [case.build() for case in CASES]
    assert {s.payload_kind for s in sources} == set(ALL_PAYLOAD_KINDS)
    assert len({s.extent_crs for s in sources}) >= 2
    assert {s.period_need for s in sources} == set(ALL_PERIOD_NEEDS)
    assert len({s.writes_out_dir for s in sources}) == 2
    assert {s.source_id for s in sources} == {case.name for case in CASES}


# --------------------------------------------------------------------------- #
# What a source declares
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_a_source_has_every_member_the_port_asks_for(case: SourceCase) -> None:
    source = case.build()
    assert missing_source_members(source) == ()
    assert isinstance(source, DataSource)
    assert set(SOURCE_MEMBERS) <= set(dir(source))


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_the_declarations_use_the_closed_vocabularies(case: SourceCase) -> None:
    source = case.build()
    assert source.payload_kind in ALL_PAYLOAD_KINDS
    assert source.period_need in ALL_PERIOD_NEEDS
    assert source.selectors, "a source that selects by nothing cannot be asked anything"
    assert set(source.selectors) <= set(ALL_SELECTORS)
    assert len(set(source.selectors)) == len(source.selectors)
    assert source.variables, "a source that names no variable serves nothing askable"
    assert isinstance(source.writes_out_dir, bool)


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_the_declared_extent_crs_resolves(case: SourceCase) -> None:
    """A CRS nothing can resolve makes every conversion into this source fail."""
    source = case.build()
    assert pyproj.CRS.from_user_input(source.extent_crs) is not None


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_the_declared_hosts_are_bare_names(case: SourceCase) -> None:
    """A host list is what a capability publishes; a URL there would not compare."""
    source = case.build()
    assert source.hosts, "every source of this suite reaches a provider over the network"
    for host in source.hosts:
        assert host == host.strip().lower()
        assert "/" not in host and ":" not in host
        assert not host.startswith("http")


# --------------------------------------------------------------------------- #
# What a source refuses
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_a_source_answers_every_selector_it_declares(
    case: SourceCase,
    tmp_path: Path,
    no_network: None,
    record_provider: Callable[..., list[ProviderCall]],
) -> None:
    source = case.build()
    for selector in source.selectors:
        calls = record_provider(case)
        period = PERIOD if source.period_need == "required" else None
        if selector == "extent":
            request = FetchRequest(out_dir=tmp_path, extent=CALLER_EXTENT, period=period)
        else:
            request = FetchRequest(out_dir=tmp_path, station_ids=("BSS000XXXX",), period=period)
        source.fetch(request)
        assert len(calls) == 1, f"{source.source_id} did not serve selector {selector!r}"


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_a_source_refuses_a_selector_it_does_not_declare(
    case: SourceCase, tmp_path: Path, no_network: None
) -> None:
    source = case.build()
    undeclared = [name for name in ALL_SELECTORS if name not in source.selectors]
    if not undeclared:
        pytest.skip(f"{source.source_id} declares every selector the port knows")
    period = PERIOD if source.period_need == "required" else None
    request = FetchRequest(out_dir=tmp_path, station_ids=("X1",), period=period)
    with pytest.raises(DataCapabilityError) as excinfo:
        source.fetch(request)
    assert "station_ids" in str(excinfo.value)


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_no_source_answers_two_selectors_at_once(
    case: SourceCase,
    tmp_path: Path,
    no_network: None,
    record_provider: Callable[..., list[ProviderCall]],
) -> None:
    """The silent one: the station list wins and the extent is dropped.

    Measured in ``piezometry/apis/hubeau.py``: ``if station_ids: ... elif
    bbox:``. A caller that passed both would get exactly what it would have got
    by passing the ids alone, and nothing in the result would say the box was
    ignored. Refused for every source until a provider can intersect them.
    """
    source = case.build()
    if set(source.selectors) != set(ALL_SELECTORS):
        pytest.skip(f"{source.source_id} declares only {list(source.selectors)}")
    calls = record_provider(case)
    period = PERIOD if source.period_need == "required" else None
    request = FetchRequest(
        out_dir=tmp_path,
        extent=CALLER_EXTENT,
        station_ids=("BSS000XXXX",),
        period=period,
    )
    with pytest.raises(DataCapabilityError, match="at once"):
        source.fetch(request)
    assert calls == [], "the provider was reached before the request was refused"


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_a_source_answers_the_period_exactly_as_it_declares(
    case: SourceCase, tmp_path: Path, no_network: None
) -> None:
    source = case.build()
    if source.period_need == "refused":
        request = FetchRequest(out_dir=tmp_path, extent=CALLER_EXTENT, period=PERIOD)
        with pytest.raises(DataCapabilityError) as excinfo:
            source.fetch(request)
        assert source.source_id in str(excinfo.value)
    elif source.period_need == "required":
        request = FetchRequest(out_dir=tmp_path, extent=CALLER_EXTENT, period=None)
        with pytest.raises(DataRequestError) as excinfo:
            source.fetch(request)
        assert source.source_id in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Layer A: what reaches the provider
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_a_foreign_crs_extent_reaches_the_provider_in_the_declared_one(
    case: SourceCase,
    tmp_path: Path,
    no_network: None,
    record_provider: Callable[..., list[ProviderCall]],
) -> None:
    """The claim the whole port exists for, checked against pyproj, not itself."""
    source = case.build()
    if "extent" not in source.selectors:
        pytest.skip(f"{source.source_id} cannot be asked for an extent")
    calls = record_provider(case)
    source.fetch(case.request(tmp_path))
    assert len(calls) == 1
    served = case.read_bbox(calls[0].args, calls[0].kwargs)
    assert served is not None, "the adapter handed its provider no bounding box"
    expected = _expected_bbox(CALLER_EXTENT, source.extent_crs)
    assert tuple(served) == pytest.approx(expected, rel=0, abs=1e-6)


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_an_extent_already_in_the_declared_crs_is_passed_through_untouched(
    case: SourceCase,
    tmp_path: Path,
    no_network: None,
    record_provider: Callable[..., list[ProviderCall]],
) -> None:
    """No round trip through a transformer when there is nothing to convert."""
    source = case.build()
    if "extent" not in source.selectors:
        pytest.skip(f"{source.source_id} cannot be asked for an extent")
    native = Extent(
        xmin=CALLER_EXTENT_L93.xmin if source.extent_crs == "EPSG:2154" else CALLER_EXTENT.xmin,
        ymin=CALLER_EXTENT_L93.ymin if source.extent_crs == "EPSG:2154" else CALLER_EXTENT.ymin,
        xmax=CALLER_EXTENT_L93.xmax if source.extent_crs == "EPSG:2154" else CALLER_EXTENT.xmax,
        ymax=CALLER_EXTENT_L93.ymax if source.extent_crs == "EPSG:2154" else CALLER_EXTENT.ymax,
        crs=source.extent_crs,
    )
    calls = record_provider(case)
    result = source.fetch(case.request(tmp_path, extent=native))
    served = case.read_bbox(calls[0].args, calls[0].kwargs)
    assert tuple(served) == native.bbox

    spelled_differently = Extent(
        xmin=native.xmin,
        ymin=native.ymin,
        xmax=native.xmax,
        ymax=native.ymax,
        crs=source.extent_crs.lower(),
    )
    calls = record_provider(case)
    other = source.fetch(case.request(tmp_path, extent=spelled_differently))
    assert tuple(case.read_bbox(calls[0].args, calls[0].kwargs)) == native.bbox
    assert other.extent is not None and other.extent.crs == source.extent_crs, (
        "a result reports the CRS the source declares, not the spelling it was handed"
    )
    assert result.extent == other.extent


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_the_result_says_what_the_source_declared(
    case: SourceCase,
    tmp_path: Path,
    no_network: None,
    record_provider: Callable[..., list[ProviderCall]],
) -> None:
    source = case.build()
    record_provider(case)
    result = source.fetch(case.request(tmp_path))
    assert isinstance(result, FetchResult)
    assert result.source_id == source.source_id
    assert result.kind == source.payload_kind
    assert result.variables == source.variables, (
        "a result names exactly the variables the source it came from declares"
    )
    assert result.extent is not None
    assert result.extent.crs == source.extent_crs, (
        "the result must report the extent that was queried, not the one that was asked"
    )
    if source.period_need == "refused":
        assert result.period is None
    else:
        assert result.period == PERIOD


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_the_out_dir_reaches_the_provider_only_when_the_source_writes(
    case: SourceCase,
    tmp_path: Path,
    no_network: None,
    record_provider: Callable[..., list[ProviderCall]],
) -> None:
    """A source that declares no write never even names the directory."""
    source = case.build()
    calls = record_provider(case)
    request = case.request(tmp_path)
    source.fetch(request)
    passed = [*calls[0].args, *calls[0].kwargs.values()]
    mentions_out_dir = any(
        isinstance(value, (str, Path)) and Path(value) == request.out_dir for value in passed
    )
    assert mentions_out_dir is source.writes_out_dir


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_a_source_that_declares_no_write_leaves_the_out_dir_alone(
    case: SourceCase,
    tmp_path: Path,
    no_network: None,
    record_provider: Callable[..., list[ProviderCall]],
) -> None:
    source = case.build()
    if source.writes_out_dir:
        pytest.skip(f"{source.source_id} declares that it writes under out_dir")
    out_dir = tmp_path / "jobdir"
    out_dir.mkdir()
    record_provider(case)
    source.fetch(case.request(out_dir))
    assert list(out_dir.iterdir()) == []


# --------------------------------------------------------------------------- #
# Layer B: what reaches the wire
# --------------------------------------------------------------------------- #


class _CannedResponse:
    """The little of ``requests.Response`` the two adapters of layer B read."""

    def __init__(self, *, content: bytes = b"", payload: object | None = None) -> None:
        self.content = content
        self._payload = payload
        self.status_code = 200
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def close(self) -> None:
        return None


@dataclass
class Wire:
    """Every request the stubbed transport was handed, and what to answer with."""

    calls: list[dict]
    responses: list[_CannedResponse]


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Iterator[Wire]:
    """Stub the shared HTTP transport and record every request it was given."""
    from hydromodpy.core.io.http_client import HTTPClient

    recorded = Wire(calls=[], responses=[])

    def _request(_self: object, method: str, url: str, **kwargs: Any) -> _CannedResponse:
        recorded.calls.append({"method": method, "url": url, "params": kwargs.get("params") or {}})
        if recorded.responses:
            return recorded.responses.pop(0)
        return _CannedResponse(payload={"data": []})

    monkeypatch.setattr(HTTPClient, "request", _request)
    yield recorded


def test_the_bbox_on_the_bdtopage_wire_is_the_reprojected_one(tmp_path: Path, wire: Wire) -> None:
    """The real WFS paging code runs; only the transport is canned."""
    wire.responses.append(
        _CannedResponse(
            content=b'<?xml version="1.0"?><wfs:FeatureCollection numberMatched="0" '
            b'xmlns:wfs="http://www.opengis.net/wfs/2.0"/>'
        )
    )
    source = BdTopageSource()
    result = source.fetch(FetchRequest(out_dir=tmp_path, extent=CALLER_EXTENT))

    assert [call["url"] for call in wire.calls] == [
        "https://services.sandre.eaufrance.fr/geo/sandre"
    ], "a host outside the declaration was contacted"
    sent = wire.calls[0]["params"]["bbox"]
    lon_min, lat_min, lon_max, lat_max, urn = sent.split(",")
    expected = _expected_bbox(CALLER_EXTENT, source.extent_crs)
    assert urn == "urn:ogc:def:crs:OGC:1.3:CRS84"
    assert (float(lon_min), float(lat_min), float(lon_max), float(lat_max)) == pytest.approx(
        expected, rel=0, abs=1e-6
    )
    assert result.is_empty


def test_the_bbox_on_the_hubeau_wire_is_the_reprojected_one(tmp_path: Path, wire: Wire) -> None:
    """The real discovery call runs; only the transport is canned.

    The caller's extent is in Lambert-93 here and in WGS84 for BD Topage, so
    the pair covers the conversion in both directions.
    """
    source = HubeauPiezometrySource(product="level")
    result = source.fetch(
        FetchRequest(out_dir=tmp_path, extent=CALLER_EXTENT_L93, period=PERIOD),
    )

    assert wire.calls, "the adapter never reached its transport"
    assert all("hubeau.eaufrance.fr" in call["url"] for call in wire.calls)
    sent = wire.calls[0]["params"]["bbox"]
    expected = _expected_bbox(CALLER_EXTENT_L93, source.extent_crs)
    assert tuple(float(v) for v in sent.split(",")) == pytest.approx(expected, rel=0, abs=1e-6)
    assert result.is_empty
    assert result.extent is not None and result.extent.crs == "EPSG:4326"


def test_the_bbox_on_the_euhydro_wire_is_the_reprojected_one(tmp_path: Path, wire: Wire) -> None:
    """The real ArcGIS discovery and query run; only their transport is canned."""
    wire.responses.extend(
        [
            _CannedResponse(
                payload={
                    "layers": [
                        {"id": 12, "type": "Group Layer", "name": "River_Net_lines"},
                        {"id": 13, "type": "Feature Layer", "parentLayerId": 12},
                    ]
                }
            ),
            _CannedResponse(payload={"name": "main"}),
            _CannedResponse(payload={"features": []}),
        ]
    )
    source = EuHydroSource()
    result = source.fetch(FetchRequest(out_dir=tmp_path, extent=CALLER_EXTENT_L93))

    assert all("image.discomap.eea.europa.eu" in call["url"] for call in wire.calls)
    query = wire.calls[-1]
    sent = query["params"]["geometry"].split(",")
    expected = _expected_bbox(CALLER_EXTENT_L93, source.extent_crs)
    assert tuple(float(value) for value in sent) == pytest.approx(expected, rel=0, abs=1e-6)
    assert result.is_empty


def test_the_bbox_on_the_osm_wire_is_the_reprojected_one(tmp_path: Path, wire: Wire) -> None:
    """The real Overpass query is built; only its HTTP request is canned."""
    wire.responses.append(_CannedResponse(content=b'{"elements": []}'))
    source = OsmSource(waterway_types=("river", "canal"))
    result = source.fetch(FetchRequest(out_dir=tmp_path, extent=CALLER_EXTENT_L93))

    assert [call["url"] for call in wire.calls] == ["https://overpass-api.de/api/interpreter"]
    query = wire.calls[0]["params"]["data"]
    lon_min, lat_min, lon_max, lat_max = _expected_bbox(CALLER_EXTENT_L93, source.extent_crs)
    bbox = f"{lat_min},{lon_min},{lat_max},{lon_max}"
    assert bbox in query
    assert 'way["waterway"="river"]' in query
    assert 'way["waterway"="canal"]' in query
    assert result.is_empty


def test_reprojection_is_what_makes_the_request_answerable() -> None:
    """What replaces a layer-B row for the IGN source, and it is stronger.

    ``fetch_ign_dem`` turns a bounding box into department codes before it
    contacts anything. Measured here offline: the caller's WGS84 box over
    eastern Brittany resolves to **no department at all**, and the same box in
    the Lambert-93 the source declares resolves to Cotes-d'Armor and
    Ille-et-Vilaine. A source that forwarded the caller's box unchanged would
    not fetch the wrong tiles, it would raise ``No department found``.
    """
    from hydromodpy.data.common.administrative.france import find_departments_in_bbox

    source = IgnDemSource()
    assert find_departments_in_bbox(CALLER_EXTENT.bbox) == []
    assert find_departments_in_bbox(CALLER_EXTENT.to_crs(source.extent_crs).bbox) == [
        "022",
        "035",
    ]


def test_what_the_ign_source_makes_on_disk_lands_under_the_out_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The only source that declares a write, held to where it writes.

    Layer A proves the directory is *passed*; it cannot prove what is done
    with it, because it stubs the provider whole. Here the real
    ``fetch_ign_dem`` prologue runs -- department resolution, cache-key
    hashing, the ``mkdir`` of ``processed/`` -- and only the download step is
    replaced, by one that raises. Everything the function creates before
    reaching the network is then read back off disk.
    """
    from hydromodpy.data.variables.dem.apis import ign_dem_fr

    class _StopBeforeDownload(RuntimeError):
        pass

    def _refuse(**_kwargs: object) -> list[Path]:
        raise _StopBeforeDownload

    monkeypatch.setattr(ign_dem_fr, "download_ign_dem_departments", _refuse)

    workspace = tmp_path / "workspace"
    out_dir = workspace / "jobdir"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    source = IgnDemSource()
    with pytest.raises(_StopBeforeDownload):
        source.fetch(FetchRequest(out_dir=out_dir, extent=CALLER_EXTENT))

    assert out_dir.is_dir(), "the prologue never got as far as making the directory"
    assert sorted(p.name for p in workspace.iterdir()) == ["jobdir"], (
        "the prologue created something beside the directory it was given"
    )
    assert sorted(p.name for p in out_dir.rglob("*")) == ["processed"]


# --------------------------------------------------------------------------- #
# The value types of the port
# --------------------------------------------------------------------------- #


def test_an_extent_without_a_crs_is_refused() -> None:
    with pytest.raises(DataRequestError, match="carries the CRS"):
        Extent(xmin=0.0, ymin=0.0, xmax=1.0, ymax=1.0, crs="  ")


@pytest.mark.parametrize(
    "bounds",
    [(1.0, 0.0, 0.0, 1.0), (0.0, 1.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0)],
    ids=["x-inverted", "y-inverted", "x-degenerate"],
)
def test_an_empty_or_inverted_extent_is_refused(bounds: tuple[float, ...]) -> None:
    with pytest.raises(DataRequestError, match="empty or inverted"):
        Extent(xmin=bounds[0], ymin=bounds[1], xmax=bounds[2], ymax=bounds[3], crs="EPSG:4326")


def test_an_extent_with_no_image_in_the_target_crs_is_refused() -> None:
    """The far side of the globe has no image in an orthographic projection.

    Measured rather than assumed: pyproj happily **extrapolates** a conic such
    as Lambert-93 well past its area of use -- a box off New Zealand comes back
    at x = 17 435 929 m with every bound finite -- so a guard tested on that
    case would have been dead code. An orthographic projection centred on the
    basin is the one that really returns ``inf``, and it is what proves the
    branch is reachable at all.
    """
    far_side = Extent(xmin=100.0, ymin=-40.0, xmax=140.0, ymax=-20.0, crs="EPSG:4326")
    with pytest.raises(DataRequestError, match="no image in"):
        far_side.to_crs("+proj=ortho +lat_0=48 +lon_0=-2 +datum=WGS84")


def test_a_conversion_that_wraps_the_antimeridian_is_refused_as_inverted() -> None:
    """A nonsense box does not come back as a plausible one.

    Lambert-93 metres a thousand times past the planet convert to a longitude
    range that wraps: ``(163.6, -90.0, -145.5, -90.0)``. Nothing in those four
    numbers is non-finite, so the finiteness guard does not see it -- what
    refuses it is :class:`Extent` itself, on the invariant every extent holds.
    """
    nonsense = Extent(xmin=1e12, ymin=1e12, xmax=2e12, ymax=2e12, crs="EPSG:2154")
    with pytest.raises(DataRequestError, match="empty or inverted"):
        nonsense.to_crs("EPSG:4326")


def test_densifying_the_edges_is_not_the_same_as_transforming_the_corners() -> None:
    """Why :meth:`Extent.to_crs` uses ``transform_bounds``, with the number.

    Over the French mainland envelope the conic parallels of Lambert-93 bow
    south between the corners, so the image of the box is not the box of the
    images: a four-corner transform puts the southern edge 26 163 m too far
    north. At basin scale the two agree to the metre, which is why the defect
    would not have shown up in any example project of this tree.
    """
    france = Extent(xmin=-5.0, ymin=41.0, xmax=10.0, ymax=51.5, crs="EPSG:4326")
    transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)
    corners = [
        transformer.transform(x, y)
        for x, y in ((-5.0, 41.0), (10.0, 41.0), (-5.0, 51.5), (10.0, 51.5))
    ]
    corner_ymin = min(point[1] for point in corners)
    densified = france.to_crs("EPSG:2154")
    assert corner_ymin - densified.ymin == pytest.approx(26162.6, abs=1.0)

    basin = CALLER_EXTENT.to_crs("EPSG:2154")
    basin_corners = [
        transformer.transform(x, y)
        for x, y in (
            (CALLER_EXTENT.xmin, CALLER_EXTENT.ymin),
            (CALLER_EXTENT.xmax, CALLER_EXTENT.ymin),
            (CALLER_EXTENT.xmin, CALLER_EXTENT.ymax),
            (CALLER_EXTENT.xmax, CALLER_EXTENT.ymax),
        )
    ]
    assert min(point[1] for point in basin_corners) - basin.ymin == pytest.approx(0.0, abs=1.0)


def test_a_period_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(DataRequestError, match="ends"):
        Period(start=datetime(2020, 2, 1), end=datetime(2020, 1, 1))


def test_a_period_mixing_an_aware_bound_with_a_naive_one_is_refused() -> None:
    with pytest.raises(DataRequestError, match="aware"):
        Period(start=datetime(2020, 1, 1), end=datetime(2020, 2, 1, tzinfo=UTC))


def test_a_request_that_selects_nothing_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DataRequestError, match="selects nothing"):
        FetchRequest(out_dir=tmp_path)


def test_a_single_string_of_station_ids_is_refused(tmp_path: Path) -> None:
    """``station_ids="BSS1"`` would be read one character per station."""
    with pytest.raises(DataRequestError, match="single string"):
        FetchRequest(out_dir=tmp_path, station_ids="BSS1")  # type: ignore[arg-type]


def test_repeated_station_ids_are_refused(tmp_path: Path) -> None:
    with pytest.raises(DataRequestError, match="repeat"):
        FetchRequest(out_dir=tmp_path, station_ids=("A", "B", "A"))


def test_a_bare_tuple_is_not_an_extent(tmp_path: Path) -> None:
    with pytest.raises(DataRequestError, match="which CRS"):
        FetchRequest(out_dir=tmp_path, extent=(-2.0, 48.0, -1.5, 48.4))  # type: ignore[arg-type]


def test_a_result_carrying_a_payload_its_kind_does_not_name_is_refused() -> None:
    with pytest.raises(DataProductError, match="declares kind"):
        FetchResult(
            source_id="x",
            kind="points",
            variables=("v",),
            files=(Path("a.tif"),),
        )


def test_a_result_that_names_no_variable_is_refused() -> None:
    with pytest.raises(DataProductError, match="names no variable"):
        FetchResult(source_id="x", kind="files", variables=(), files=(Path("a.tif"),))


def test_an_empty_result_is_not_an_error() -> None:
    """A box over the sea holds no gauging station, and that is an answer."""
    empty = FetchResult(source_id="x", kind="points", variables=("v",))
    assert empty.is_empty


def test_a_record_the_source_does_not_declare_is_refused() -> None:
    """The check the adversarial gate found aimed one level too wide.

    ``HubeauPiezometrySource`` can serve two products, and an instance serves
    one. While ``variables`` was a class-wide constant, a ``product="level"``
    source that received a depth-labelled record passed the check in silence
    and returned a result whose own ``variables`` said ``groundwater_level``.
    ``variables`` is now the instance's, and the record is refused.
    """
    from dataclasses import dataclass as _dataclass

    from hydromodpy.data.variables.piezometry.apis import hubeau

    @_dataclass
    class _MislabelledRecord:
        variable: str

    source = HubeauPiezometrySource(product="level")
    assert source.variables == ("groundwater_level",)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            hubeau,
            "fetch",
            lambda **_kwargs: [_MislabelledRecord(variable="groundwater_depth")],
        )
        with pytest.raises(DataProductError, match="groundwater_depth"):
            source.fetch(
                FetchRequest(out_dir=Path("."), extent=CALLER_EXTENT, period=PERIOD),
            )


def test_a_numpy_scalar_is_a_coordinate() -> None:
    """An extent built straight off a geopandas ``total_bounds`` is legitimate.

    ``numpy.int64`` and ``numpy.float32`` are not subclasses of ``int`` or
    ``float`` in CPython -- only ``numpy.float64`` is -- so an ``isinstance``
    whitelist refused a real number from the one place callers get bounds.
    """
    numpy = pytest.importorskip("numpy")

    bounds = numpy.array([317000, 6780000, 354000, 6826000], dtype=numpy.int64)
    extent = Extent(xmin=bounds[0], ymin=bounds[1], xmax=bounds[2], ymax=bounds[3], crs="EPSG:2154")
    assert extent.bbox == (317000.0, 6780000.0, 354000.0, 6826000.0)
    assert all(isinstance(value, float) for value in extent.bbox)

    as_float32 = Extent(
        xmin=numpy.float32(-2.0),
        ymin=numpy.float32(48.0),
        xmax=numpy.float32(-1.5),
        ymax=numpy.float32(48.4),
        crs="EPSG:4326",
    )
    assert as_float32.crs == "EPSG:4326"

    with pytest.raises(DataRequestError, match="not a number"):
        Extent(xmin="0", ymin=0.0, xmax=1.0, ymax=1.0, crs="EPSG:4326")  # type: ignore[arg-type]
    with pytest.raises(DataRequestError, match="boolean"):
        Extent(xmin=False, ymin=0.0, xmax=1.0, ymax=1.0, crs="EPSG:4326")  # type: ignore[arg-type]
    with pytest.raises(DataRequestError, match="not finite"):
        Extent(xmin=float("nan"), ymin=0.0, xmax=1.0, ymax=1.0, crs="EPSG:4326")


def test_the_bdtopage_defaults_match_the_config_they_replace() -> None:
    """Two copies of a default drift; this is the gate that says when."""
    from hydromodpy.data.source.bdtopage import DEFAULT_PAGE_SIZE, DEFAULT_TYPENAME
    from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

    declared = HydrographySourceConfig(source="bdtopage")
    assert DEFAULT_TYPENAME == declared.typename
    assert DEFAULT_PAGE_SIZE == declared.page_size
