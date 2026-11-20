"""Which SHOM gauge an oceanic source reads, and the files read from a folder.

A SHOM source names its gauges with station_ids, or gives a mask whose center
(degrees) is the point the nearest gauge is searched from. A named station wins
over a mask injected by the project run, because the run fills mask_path on
every source that declares it. The module also reads a custom sea level folder.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.core.io.fetch import HTTPClient
from hydromodpy.data.variables.oceanic.apis import shom
from hydromodpy.data.variables.oceanic.config import OceanicConfig, OceanicSourceConfig
from hydromodpy.data.variables.oceanic.variable import OceanicVariable

pytestmark = pytest.mark.fast

PERIOD = (datetime(2003, 1, 1), datetime(2003, 1, 30))

# A coastal basin near Brest, in Lambert-93. Its center is around 48.4 N, 4.5 W.
BREST_BASIN_2154 = Polygon(
    [
        (145000.0, 6830000.0),
        (165000.0, 6830000.0),
        (165000.0, 6850000.0),
        (145000.0, 6850000.0),
    ]
)


def _mask(tmp_path: Path) -> Path:
    path = tmp_path / "watershed.gpkg"
    gpd.GeoDataFrame(geometry=[BREST_BASIN_2154], crs="EPSG:2154").to_file(path)
    return path


def _manager(source_cfg: OceanicSourceConfig, *, data_dir: Path | None = None) -> OceanicVariable:
    return OceanicVariable(
        config=OceanicConfig(sources=[source_cfg]),
        index=None,
        project_period=PERIOD,
        data_dir=data_dir,
    )


def _capture(monkeypatch) -> dict:
    captured: dict[str, object] = {}

    def fake_fetch(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(shom, "fetch", fake_fetch)
    return captured


def test_a_named_station_wins_over_a_mask(tmp_path, monkeypatch):
    captured = _capture(monkeypatch)
    source = OceanicSourceConfig(source="shom", station_ids=["152"], mask_path=_mask(tmp_path))

    _manager(source)._fetch_from_source(source)

    assert captured["station_id"] == "152"
    assert "near_lat" not in captured, captured


def test_no_selector_at_all_is_refused(monkeypatch):
    _capture(monkeypatch)
    source = OceanicSourceConfig(source="shom")
    with pytest.raises((ValueError, DataRequestError), match="station"):
        _manager(source)._fetch_from_source(source)


def test_a_mask_gives_the_point_to_search_from_in_degrees(tmp_path, monkeypatch):
    # The mask is in meters, so an unconverted center would be ~6.84e6.
    captured = _capture(monkeypatch)
    source = OceanicSourceConfig(source="shom", mask_path=_mask(tmp_path))

    _manager(source)._fetch_from_source(source)

    assert "station_id" not in captured, captured
    assert captured["near_lat"] == pytest.approx(48.4, abs=0.3), captured
    assert captured["near_lon"] == pytest.approx(-4.5, abs=0.3), captured


def test_named_stations_skip_the_search_and_are_read_one_by_one(tmp_path, monkeypatch):
    calls: list[dict] = []

    def fake_fetch(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(shom, "fetch", fake_fetch)
    source = OceanicSourceConfig(source="shom", station_ids=["152", "170"])

    _manager(source, data_dir=tmp_path / "data")._fetch_from_source(source)

    assert [c["station_id"] for c in calls] == ["152", "170"]
    assert all(c.get("near_lat") is None for c in calls), calls
    assert all(c["cache_dir"] == tmp_path / "data" for c in calls), calls


def test_the_cache_lives_in_the_variable_data_directory(tmp_path, monkeypatch):
    # Where the committed SHOM seed already sits: data/oceanic/.
    captured = _capture(monkeypatch)
    source = OceanicSourceConfig(source="shom", mask_path=_mask(tmp_path))

    _manager(source, data_dir=tmp_path / "data" / "oceanic")._fetch_from_source(source)

    assert captured["cache_dir"] == tmp_path / "data" / "oceanic"


FETCH_REFUSALS = [
    pytest.param({}, "Not both, not neither", id="no selector"),
    pytest.param(
        {"station_id": "152", "near_lat": 48.0, "near_lon": -4.0},
        "Not both, not neither",
        id="station and point",
    ),
    pytest.param({"near_lat": 48.0}, "near_lat and near_lon", id="half a point"),
]


@pytest.mark.parametrize(("kwargs", "match"), FETCH_REFUSALS)
def test_fetch_refusals(kwargs, match):
    # The port-level rule stays a refusal: both arguments come from the caller.
    with pytest.raises(ValueError, match=match):
        shom.fetch(date_start=PERIOD[0], date_end=PERIOD[1], client=HTTPClient(), **kwargs)


def test_cache_round_trips_on_a_named_file(tmp_path):
    # The filename is the contract the committed seed CSV is stored under.
    frame = pd.DataFrame({"timestamp": pd.to_datetime(["2003-01-01T00:00:00"]), "value": [1.25]})
    shom._write_cache(tmp_path, "152", PERIOD[0], PERIOD[1], frame)

    assert (tmp_path / "sealevel_shom_152_20030101_20030130_H.csv").exists()
    back = shom._try_load_cached(tmp_path, "152", PERIOD[0], PERIOD[1])
    assert back is not None
    assert back["value"].tolist() == [1.25]
    assert shom._try_load_cached(None, "152", PERIOD[0], PERIOD[1]) is None


def load_file(cfg):
    return OceanicVariable(config=None, index=None, project_period=None).load_file(cfg)


def test_unsupported_extension_is_refused(tmp_path):
    bad_file = tmp_path / "data.xyz"
    bad_file.write_text("hello")

    with pytest.raises(ValueError, match="Unsupported custom format"):
        load_file(OceanicSourceConfig(source="file", path=bad_file))


def test_missing_directory_is_refused(tmp_path):
    with pytest.raises((FileNotFoundError, ValueError)):
        load_file(OceanicSourceConfig(source="file", path=tmp_path / "nonexistent"))


def test_folder_without_loc_file_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError, match="No oceanic_file_LOC"):
        load_file(OceanicSourceConfig(source="file", path=tmp_path))
