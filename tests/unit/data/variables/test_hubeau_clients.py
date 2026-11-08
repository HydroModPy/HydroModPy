"""Hub'Eau clients of piezometry, intermittency, hydrometry and water quality, over a fake HTTP layer.

The plain ``fetch`` functions below prove what each client downloads. The
four ``Hubeau...`` classes prove what the port asks of them: one selector per
request, the station list before the box, and the result carrying what the
class declares.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.core.exceptions import DataCapabilityError, DataRequestError
from hydromodpy.data.common import api_client
from hydromodpy.data.source.port import (
    DataSource,
    Extent,
    FetchRequest,
    Period,
    missing_source_members,
)
from hydromodpy.data.source.registry import build_from_section
from hydromodpy.schema.sources import source_entry

START, END = datetime(2020, 1, 1), datetime(2020, 1, 31)
BBOX = (-2.0, 47.0, -1.0, 48.0)
IN_A, IN_B = (-1.5, 47.5), (-1.2, 47.9)
JUST_OUT = (-0.9, 47.5)


@dataclass(frozen=True)
class Spec:
    """How one client talks to its fake endpoints."""

    module: str
    base: dict
    stations: str
    loc_param: str
    obs: str
    obs_param: str
    station_row: Any
    obs_row: Any
    variable: str
    unit: str


SPECS = {
    "piezometry": Spec(
        "piezometry",
        {"product": "level"},
        "/stations",
        "code_bss",
        "/chroniques",
        "code_bss",
        lambda i, lon, lat: {"code_bss": i, "geometry": {"coordinates": [lon, lat]}},
        lambda d, v: {"date_mesure": d, "niveau_nappe_eau": v},
        "groundwater_level",
        "m",
    ),
    "intermittency": Spec(
        "intermittency",
        {},
        "/stations",
        "code_station",
        "/observations",
        "code_station",
        lambda i, lon, lat: {"code_station": i, "longitude": lon, "latitude": lat},
        lambda d, v: {"date_observation": d, "code_ecoulement": "1"},
        "flow_state",
        "code",
    ),
    "hydrometry": Spec(
        "hydrometry",
        {"product": "QmnJ"},
        "/referentiel/stations",
        "code_station",
        "/obs_elab",
        "code_entite",
        lambda i, lon, lat: {
            "code_station": i,
            "longitude_station": lon,
            "latitude_station": lat,
        },
        lambda d, v: {"date_obs_elab": d, "resultat_obs_elab": v},
        "discharge",
        "m3/s",
    ),
    "water_quality": Spec(
        "water_quality",
        {},
        "/station_pc",
        "code_station",
        "/analyse_pc",
        "code_station",
        lambda i, lon, lat: {"code_station": i, "longitude": lon, "latitude": lat},
        lambda d, v: {
            "date_prelevement": d,
            "libelle_parametre": "pH",
            "resultat": v,
            "symbole_unite": "u",
        },
        "pH",
        "u",
    ),
}
ALL = list(SPECS)
STATION_ID = {"piezometry": "BSS1", "intermittency": "S1", "hydrometry": "J000000001"}
STATION_ID["water_quality"] = "W1"


def _mod(name):
    return import_module(f"hydromodpy.data.variables.{name}.apis.hubeau")


class World:
    """Canned stations and observations behind a fake ``get_json``."""

    def __init__(self, spec, stations, obs):
        self.spec, self.stations, self.obs, self.calls = spec, stations, obs, []

    def __call__(self, url, *, params=None, **_kw):
        spec, params = self.spec, dict(params or {})
        self.calls.append((url, params))
        if url.endswith(spec.stations):
            if "bbox" in params:
                x0, y0, x1, y1 = (float(v) for v in params["bbox"].split(","))
                hits = [
                    (i, lon, lat)
                    for i, (lon, lat) in self.stations.items()
                    if x0 <= lon <= x1 and y0 <= lat <= y1
                ]
            else:
                sid = params[spec.loc_param]
                hits = [(sid, *self.stations[sid])] if sid in self.stations else []
            return {"data": [spec.station_row(*h) for h in hits]}
        if url.endswith(spec.obs):
            rows = self.obs.get(params[spec.obs_param], [])
            return {"data": [spec.obs_row(d, v) for d, v in rows], "count": len(rows)}
        raise AssertionError(url)


@pytest.fixture
def install(monkeypatch):
    """Patch ``get_json`` in the client module and in the paginator, return the world."""

    def _install(name, stations, obs):
        world = World(SPECS[name], stations, obs)
        monkeypatch.setattr(_mod(name), "get_json", world)
        monkeypatch.setattr(api_client, "get_json", world)
        return world

    return _install


def _fetch(name, **kw):
    return _mod(name).fetch(**SPECS[name].base, **_window(kw))


def _window(kw):
    return {"date_start": START, "date_end": END, **kw}


def _data(n=3):
    return [(f"2020-01-{day:02d}", 1000.0 + day) for day in range(1, n + 1)]


def _ids(records):
    return [r.station_id for r in records]


@pytest.mark.fast
@pytest.mark.parametrize("name", ALL)
def test_bbox_discovery_keeps_stations_inside_and_builds_records(install, name):
    sid = STATION_ID[name]
    spec = SPECS[name]
    world = install(name, {sid: IN_A, "OUT": (5.0, 40.0)}, {sid: _data(3), "OUT": _data(3)})
    records = _fetch(name, bbox=BBOX)
    assert _ids(records) == [sid]
    rec = records[0]
    assert (rec.variable, rec.unit, len(rec.data)) == (spec.variable, spec.unit, 3)
    assert (rec.location.x, rec.location.y) == IN_A
    assert any("bbox" in p for _, p in world.calls)


@pytest.mark.fast
@pytest.mark.parametrize("name", ALL)
@pytest.mark.parametrize(("radius", "expected"), [(None, []), (50.0, True)])
def test_fallback_radius_expands_the_bbox_once(install, name, radius, expected):
    sid = STATION_ID[name]
    install(name, {sid: JUST_OUT}, {sid: _data(2)})
    records = _fetch(name, bbox=BBOX, fallback_search_radius_km=radius)
    assert (_ids(records) == [sid]) if expected is True else records == []


@pytest.mark.fast
@pytest.mark.parametrize("name", ALL)
def test_station_ids_skip_discovery(install, name):
    sid = STATION_ID[name]
    world = install(name, {sid: IN_A}, {sid: _data(2)})
    records = _fetch(name, station_ids=[sid])
    assert _ids(records) == [sid]
    assert all("bbox" not in p for _, p in world.calls)


@pytest.mark.fast
@pytest.mark.parametrize("name", ALL)
def test_no_station_found_returns_empty_list(install, name):
    install(name, {}, {})
    assert _fetch(name, bbox=BBOX) == []


@pytest.mark.fast
@pytest.mark.parametrize("name", ALL)
def test_station_without_observations_is_skipped(install, name):
    sid = STATION_ID[name]
    other = sid[:-1] + "9"
    install(name, {sid: IN_A, other: IN_B}, {sid: _data(2)})
    assert _ids(_fetch(name, bbox=BBOX)) == [sid]


@pytest.mark.fast
@pytest.mark.parametrize("name", ALL)
def test_bbox_or_station_ids_is_required(install, name):
    install(name, {}, {})
    with pytest.raises(ValueError, match="bbox"):
        _fetch(name)


@pytest.mark.fast
@pytest.mark.parametrize(
    ("name", "target", "expected"),
    [
        ("piezometry", IN_A, "BSS1"),
        ("piezometry", IN_B, "BSS2"),
        ("water_quality", IN_A, "W1"),
        ("water_quality", IN_B, "W2"),
    ],
)
def test_nearest_to_keeps_one_station(install, name, target, expected):
    a, b = STATION_ID[name], STATION_ID[name][:-1] + "2"
    install(name, {a: IN_A, b: IN_B}, {a: _data(2), b: _data(2)})
    assert _ids(_fetch(name, bbox=BBOX, nearest_to=target)) == [expected]


@pytest.mark.fast
@pytest.mark.parametrize("name", ["piezometry", "water_quality"])
def test_nearest_to_without_any_coordinates_returns_empty(install, name):
    sid = STATION_ID[name]
    install(name, {}, {sid: _data(2)})
    assert _fetch(name, station_ids=[sid], nearest_to=IN_A) == []


@pytest.mark.fast
@pytest.mark.parametrize("name", ["piezometry", "hydrometry"])
def test_closed_station_is_dropped_only_when_observations_are_required(install, monkeypatch, name):
    key = "date_debut_mesure" if name == "piezometry" else "date_ouverture_station"
    end_key = "date_fin_mesure" if name == "piezometry" else "date_fermeture_station"
    spec = SPECS[name]
    sid = STATION_ID[name]
    world = install(name, {sid: IN_A}, {sid: _data(2)})

    def closed_row(i, lon, lat):
        return {**spec.station_row(i, lon, lat), key: "2000-01-01", end_key: "2010-01-01"}

    monkeypatch.setattr(
        world, "spec", SimpleNamespace(**{**spec.__dict__, "station_row": closed_row})
    )
    assert _fetch(name, bbox=BBOX) == []
    assert _ids(_fetch(name, bbox=BBOX, require_observations=False)) == [sid]


# --------------------------------------------------------------------------- #
# The four classes behind the data-source port
# --------------------------------------------------------------------------- #

OUT = Path("out")
"""A request's out_dir: the Hub'Eau sources declare they never write one."""


def _class(name):
    """The port class of one client's module."""
    class_names = {
        "hydrometry": "HubeauHydrometry",
        "piezometry": "HubeauPiezometry",
        "water_quality": "HubeauWaterQuality",
        "intermittency": "HubeauIntermittency",
    }
    return getattr(_mod(name), class_names[name])


def _period() -> Period:
    return Period(start=START, end=END)


def _extent_request() -> FetchRequest:
    return FetchRequest(out_dir=OUT, extent=Extent(*BBOX, crs="EPSG:4326"), period=_period())


def _station_request(sid: str) -> FetchRequest:
    return FetchRequest(out_dir=OUT, station_ids=(sid,), period=_period())


SECTION_MODELS = {
    "hydrometry": ("HydrometrySourceConfig", {"source": "hubeau", "product": "QmM"}),
    "piezometry": ("PiezometrySourceConfig", {"source": "hubeau", "product": "level"}),
    "water_quality": ("WaterQualitySourceConfig", {"source": "hubeau", "parameters": ["pH"]}),
    "intermittency": (
        "IntermittencySourceConfig",
        {"source": "hubeau", "code_departement": ["35"]},
    ),
}
SECTION_FIELD_CALLS = {
    "hydrometry": {"product": "QmM"},
    "piezometry": {"product": "level"},
    "water_quality": {"parameters": ["pH"], "variables": ("pH",)},
    "intermittency": {"code_departement": ["35"], "variables": ("flow_state",)},
}


@pytest.mark.fast
@pytest.mark.parametrize("name", ALL)
def test_each_client_is_a_class_of_the_port(name):
    source = _class(name)(**SPECS[name].base)
    assert missing_source_members(source) == ()
    assert isinstance(source, DataSource)
    assert source.source_id == "hubeau"
    assert source.section == name
    assert source.payload_kind == "points"
    assert source.extent_crs == "EPSG:4326"
    assert source.selectors == ("extent", "station_ids")
    assert source.period_need == "required"
    assert source.writes_out_dir is False
    assert source.variables, "a source that names no variable serves nothing askable"
    assert source.hosts == source_entry("hubeau").hosts


@pytest.mark.fast
@pytest.mark.parametrize("name", ALL)
def test_a_station_request_names_no_bbox(install, name):
    sid = STATION_ID[name]
    world = install(name, {sid: IN_A}, {sid: _data(2)})
    result = _class(name)(**SPECS[name].base).fetch(_station_request(sid))
    assert _ids(list(result.points)) == [sid]
    assert result.extent is None
    assert all("bbox" not in p for _, p in world.calls), (
        "the station list wins and the box must not be named anywhere"
    )


@pytest.mark.fast
@pytest.mark.parametrize("name", ALL)
def test_an_extent_request_drives_discovery_and_is_reported(install, name):
    sid = STATION_ID[name]
    world = install(name, {sid: IN_A}, {sid: _data(2)})
    result = _class(name)(**SPECS[name].base).fetch(_extent_request())
    assert _ids(list(result.points)) == [sid]
    assert result.extent is not None
    assert result.extent.bbox == BBOX
    assert result.extent.crs == "EPSG:4326"
    assert [p for _, p in world.calls if "bbox" in p], "the discovery never saw the box"


@pytest.mark.fast
@pytest.mark.parametrize("name", ALL)
def test_two_selectors_are_refused_before_the_provider(install, name):
    sid = STATION_ID[name]
    world = install(name, {sid: IN_A}, {sid: _data(2)})
    both = FetchRequest(
        out_dir=OUT,
        extent=Extent(*BBOX, crs="EPSG:4326"),
        station_ids=(sid,),
        period=_period(),
    )
    with pytest.raises(DataCapabilityError, match="at once"):
        _class(name)(**SPECS[name].base).fetch(both)
    assert world.calls == [], "the provider was reached before the request was refused"


@pytest.mark.fast
@pytest.mark.parametrize("name", ALL)
def test_a_request_without_a_period_is_refused(install, name):
    sid = STATION_ID[name]
    install(name, {sid: IN_A}, {sid: _data(2)})
    request = FetchRequest(out_dir=OUT, station_ids=(sid,))
    with pytest.raises(DataRequestError, match="period"):
        _class(name)(**SPECS[name].base).fetch(request)


@pytest.mark.fast
@pytest.mark.parametrize("name", ALL)
def test_a_section_binds_the_constructor_and_serves_the_station(install, name):
    sid = STATION_ID[name]
    install(name, {sid: IN_A}, {sid: _data(2)})
    model_name, section_kwargs = SECTION_MODELS[name]
    module = import_module(f"hydromodpy.data.variables.{name}.config")
    section = getattr(module, model_name).model_validate(section_kwargs)
    source = build_from_section(_class(name), section)
    for field, expected in SECTION_FIELD_CALLS[name].items():
        assert getattr(source, field) == expected, (name, field)
    records = list(source.fetch(_station_request(sid)).points)
    assert _ids(records) == [sid]


@pytest.mark.fast
@pytest.mark.parametrize("name", ["piezometry", "water_quality"])
def test_the_constructor_takes_the_nearest_point_the_manager_resolves(install, name):
    near, far = STATION_ID[name], STATION_ID[name][:-1] + "2"
    install(name, {near: IN_A, far: IN_B}, {near: _data(2), far: _data(2)})
    source = _class(name)(**SPECS[name].base, nearest_to=IN_A)
    records = list(source.fetch(_extent_request()).points)
    assert _ids(records) == [near]


@pytest.mark.fast
def test_code_departement_reaches_the_discovery_of_an_extent_request(install):
    world = install("intermittency", {"S1": IN_A}, {"S1": _data(2)})
    source = _class("intermittency")(code_departement=["35"])
    records = list(source.fetch(_extent_request()).points)
    assert _ids(records) == ["S1"]
    discovery = [p for url, p in world.calls if url.endswith("/stations")]
    assert discovery[0]["code_departement"] == "35"


@pytest.mark.fast
@pytest.mark.parametrize("name", ALL)
def test_the_result_says_what_the_class_declares(install, name):
    sid = STATION_ID[name]
    spec = SPECS[name]
    install(name, {sid: IN_A}, {sid: _data(2)})
    source = _class(name)(**spec.base)
    result = source.fetch(_extent_request())
    assert result.source_id == "hubeau"
    assert result.kind == "points"
    assert result.variables == source.variables
    assert result.period == _period()
    (record,) = result.points
    assert (record.variable, record.unit) == (spec.variable, spec.unit)


@pytest.mark.fast
def test_piezometry_depth_product_reads_the_depth_column(install):
    world = install("piezometry", {"B": IN_A}, {})
    world.spec = SimpleNamespace(
        **{
            **SPECS["piezometry"].__dict__,
            "obs_row": lambda d, v: {"date_mesure": d, "profondeur_nappe": v},
        }
    )
    world.obs["B"] = _data(2)
    (rec,) = _mod("piezometry").fetch(product="depth", station_ids=["B"], **_window({}))
    assert rec.variable == "groundwater_depth"
    assert list(rec.data["value"]) == [1001.0, 1002.0]


@pytest.mark.fast
def test_piezometry_location_falls_back_to_direct_fields(monkeypatch):
    rows = {"data": [{"longitude_station": -1.5, "latitude_station": 47.5, "nom_commune": "X"}]}
    mod = _mod("piezometry")
    monkeypatch.setattr(mod, "get_json", lambda *a, **k: rows)
    loc = mod._fetch_piezometer_location("B")
    assert (loc.x, loc.y, loc.metadata["station_name"]) == (-1.5, 47.5, "X")
    monkeypatch.setattr(mod, "get_json", lambda *a, **k: {"data": [{"nom_commune": "X"}]})
    assert mod._fetch_piezometer_location("B") is None
    monkeypatch.setattr(mod, "get_json", lambda *a, **k: None)
    assert mod._fetch_piezometer_location("B") is None


@pytest.mark.fast
def test_piezometry_chronicle_without_date_column_is_empty(monkeypatch):
    mod = _mod("piezometry")
    monkeypatch.setattr(mod, "get_json", lambda *a, **k: {"data": [{"niveau_nappe_eau": 1.0}]})
    assert mod._download_chronicles("B", "level", START, END).empty
    monkeypatch.setattr(mod, "get_json", lambda *a, **k: {"data": [{"date_mesure": "2020-01-01"}]})
    assert mod._download_chronicles("B", "level", START, END).empty


@pytest.mark.fast
def test_intermittency_maps_codes_and_drops_impossible_observations(install):
    world = install("intermittency", {"S1": IN_A}, {})
    codes = ["1", "1a", "1f", "2", "3", "4", "zz"]
    world.spec = SimpleNamespace(
        **{
            **SPECS["intermittency"].__dict__,
            "obs_row": lambda d, v: {"date_observation": d, "code_ecoulement": v},
        }
    )
    world.obs["S1"] = [(f"2020-01-{i + 1:02d}", c) for i, c in enumerate(codes)]
    (rec,) = _mod("intermittency").fetch(station_ids=["S1"], **_window({}))
    assert list(rec.data["value"]) == [5, 4, 3, 2, 1]


@pytest.mark.fast
def test_intermittency_department_discovery_and_frozen_station(monkeypatch):
    mod = _mod("intermittency")
    seen = {}

    def fake(url, *, params=None, **_kw):
        seen.update(params)
        return {
            "data": [
                {"code_station": "S1", "etat_station": "Active"},
                {"code_station": "S2", "etat_station": "Gelée"},
                {"code_station": ""},
            ]
        }

    monkeypatch.setattr(mod, "get_json", fake)
    ids = mod._discover_stations(
        code_departement=["35", "56"], date_start=START, date_end=END, require_observations=True
    )
    assert ids == ["S1"]
    assert seen["code_departement"] == "35,56" and "bbox" not in seen


@pytest.mark.fast
def test_intermittency_only_impossible_observations_gives_no_record(install):
    world = install("intermittency", {"S1": IN_A}, {"S1": _data(2)})
    world.spec = SimpleNamespace(
        **{
            **SPECS["intermittency"].__dict__,
            "obs_row": lambda d, v: {"date_observation": d, "code_ecoulement": "4"},
        }
    )
    assert _mod("intermittency").fetch(station_ids=["S1"], **_window({})) == []
    with pytest.raises(ValueError, match="code_departement"):
        _mod("intermittency").fetch(**_window({}))


@pytest.mark.fast
@pytest.mark.parametrize(
    ("product", "variable", "unit", "scaled"),
    [
        ("QmnJ", "discharge", "m3/s", 1.001),
        ("HIXM", "water_level", "m", 1.001),
    ],
)
def test_hydrometry_unit_conversion_by_product(install, product, variable, unit, scaled):
    install("hydrometry", {"J000000001": IN_A}, {"J000000001": [("2020-01-01", 1001.0)]})
    (rec,) = _mod("hydrometry").fetch(product=product, station_ids=["J000000001"], **_window({}))
    assert (rec.variable, rec.unit) == (variable, unit)
    assert rec.data["value"].iloc[0] == pytest.approx(scaled)


@pytest.mark.fast
def test_hydrometry_site_code_gets_the_sensor_suffix(install):
    world = install("hydrometry", {"J0000000" + "01": IN_A}, {"J000000001": _data(1)})
    (rec,) = _mod("hydrometry").fetch(product="QmnJ", station_ids=[" J0000000 "], **_window({}))
    assert rec.station_id == "J000000001"
    assert {p["code_entite"] for _, p in world.calls if "code_entite" in p} == {"J000000001"}


@pytest.mark.fast
def test_hydrometry_long_period_is_downloaded_in_chunks(install, monkeypatch):
    mod = _mod("hydrometry")
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    world = install("hydrometry", {"J000000001": IN_A}, {"J000000001": [("2020-01-01", 5.0)]})
    df = mod._download_observations(
        "J000000001", "QmnJ", datetime(1900, 1, 1), datetime(2020, 1, 1)
    )
    chunks = [p for u, p in world.calls if u.endswith("/obs_elab")]
    assert len(chunks) == 3 and len(df) == 3
    assert chunks[0]["date_debut_obs_elab"] == "1900-01-01"


@pytest.mark.fast
def test_hydrometry_max_stations_counts_kept_stations(install):
    ids = {f"J00000000{i}": IN_A for i in range(1, 4)}
    install("hydrometry", ids, {"J000000002": _data(1), "J000000003": _data(1)})
    records = _mod("hydrometry").fetch(product="QmnJ", bbox=BBOX, max_stations=1, **_window({}))
    assert _ids(records) == ["J000000002"]


@pytest.mark.fast
def test_water_quality_parameters_filter_and_one_record_per_parameter(install):
    world = install("water_quality", {"W1": IN_A}, {})
    world.spec = SimpleNamespace(
        **{
            **SPECS["water_quality"].__dict__,
            "obs_row": lambda d, v: {
                "date_prelevement": d,
                "libelle_parametre": v[0],
                "resultat": v[1],
                "symbole_unite": v[2],
            },
        }
    )
    world.obs["W1"] = [
        ("2020-01-02", ("pH", 7.0, "u")),
        ("2020-01-03", ("Nitrates", 12.0, "mg/L")),
        ("2020-01-04", ("pH", 7.4, "u")),
    ]
    mod = _mod("water_quality")
    both = {r.variable: r for r in mod.fetch(station_ids=["W1"], **_window({}))}
    assert {k: (len(r.data), r.unit) for k, r in both.items()} == {
        "Nitrates": (1, "mg/L"),
        "pH": (2, "u"),
    }
    only = mod.fetch(station_ids=["W1"], parameters=["NITRATES"], **_window({}))
    assert [r.variable for r in only] == ["Nitrates"]
    assert mod.fetch(station_ids=["W1"], parameters=["absent"], **_window({})) == []


@pytest.mark.fast
def test_water_quality_groundwater_uses_bss_params_and_data_coordinates(monkeypatch):
    mod = _mod("water_quality")
    calls = []

    def fake(url, *, params=None, **_kw):
        calls.append((url, params))
        if url == mod.API_PZ_STATIONS:
            return {"data": []}
        return {
            "data": [
                {
                    "date": "2020-01-05",
                    "nom_param": "Cl",
                    "valeur": "3.5",
                    "nom_unite": "mg/L",
                    "longitude": -1.4,
                    "latitude": 47.6,
                }
            ]
        }

    monkeypatch.setattr(mod, "get_json", fake)
    (rec,) = mod.fetch(
        site_type="piezometer", station_ids=["07/123", "bss9"], date_start=START, date_end=END
    )[:1]
    assert (rec.station_id, rec.variable, rec.unit) == ("07/123", "Cl", "mg/L")
    assert (rec.location.x, rec.location.y) == (-1.4, 47.6)
    keys = {
        next(k for k in ("code_bss", "bss_id") if k in p) for u, p in calls if u == mod.API_PZ_URL
    }
    assert keys == {"code_bss", "bss_id"}


@pytest.mark.fast
def test_water_quality_discovery_dedupes_and_normalization_rejects_bad_columns(monkeypatch):
    import pandas as pd

    mod = _mod("water_quality")
    rows = [{"code_station": "A"}, {"code_station": "A"}, {"code_station": "B"}, {"bss_id": "C"}]
    monkeypatch.setattr(mod, "get_json", lambda *a, **k: {"data": rows})
    assert mod._discover_stations(BBOX, is_river=True, max_stations=2) == ["A", "B"]
    assert mod._discover_stations(BBOX, is_river=False) == ["C"]
    assert mod._normalize_dataframe(pd.DataFrame({"resultat": [1]}), is_river=True).empty
    assert mod._normalize_dataframe(pd.DataFrame({"date": ["2020-01-01"]}), is_river=True).empty
