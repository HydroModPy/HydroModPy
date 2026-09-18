"""Which SHOM gauge is read, and what says so.

``apis/shom.py`` was the last fetch function in the tree taking a
``geographic: object``, which is why F5b's ``DataSource`` port left it
unported: its selector is a point, not a box. The point is now declared --
either the gauges are named with ``station_ids``, or the extent gives the
shape whose centre the nearest gauge is searched from.

**The named station wins over an injected mask, and that is the composition
this file exists to hold.** ``_apply_default_masks`` fills ``mask_path`` on
every source whose model declares the field, so on a project run a source that
names nothing but ``station_ids`` arrives carrying a watershed it never asked
for. Refusing the pair -- which is what D116 says about two selectors on a
*request*, where both come from the caller -- makes ``station_ids`` raise on
every project run instead.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from hydromodpy.data.loading.loader import DataManagersRuntimeLoader
from hydromodpy.data.variables.oceanic.apis import shom
from hydromodpy.data.variables.oceanic.config import OceanicConfig, OceanicSourceConfig
from hydromodpy.data.variables.oceanic.manager import OceanicManager

PERIOD = (datetime(2003, 1, 1), datetime(2003, 1, 30))

# A coastal basin near Brest, in Lambert-93. Its centre is around 48.4 N, 4.5 W.
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


def _manager(source_cfg: OceanicSourceConfig, *, data_dir: Path | None = None) -> OceanicManager:
    return OceanicManager(
        config=OceanicConfig(sources=[source_cfg]),
        catalog=None,
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


@pytest.mark.fast
def test_a_named_station_wins_over_a_mask(tmp_path, monkeypatch):
    captured = _capture(monkeypatch)
    source = OceanicSourceConfig(source="shom", station_ids=["152"], mask_path=_mask(tmp_path))

    _manager(source)._fetch_shom(source)

    assert captured["station_id"] == "152"
    assert "near_lat" not in captured, captured


@pytest.mark.fast
def test_a_named_station_survives_the_mask_the_loader_injects(tmp_path, monkeypatch):
    """The composition, not the two halves: this is what the first cut got wrong.

    Each half was tested on its own -- the loader fills ``mask_path`` on every
    source that declares the field, and the manager reads a selector -- and the
    pair refused each other on every project run. A source that names a station
    and nothing else is exactly the shape the documentation recommends.
    """
    captured = _capture(monkeypatch)
    watershed = _mask(tmp_path)
    config = OceanicConfig(sources=[OceanicSourceConfig(source="shom", station_ids=["152"])])
    result = SimpleNamespace(
        setup=SimpleNamespace(geographic=SimpleNamespace(watershed_shp=watershed))
    )

    DataManagersRuntimeLoader._apply_default_masks(config, result)
    source = config.sources[0]
    assert source.mask_path == watershed, "the loader stopped injecting; this test is now vacuous"

    OceanicManager(config=config, catalog=None, project_period=PERIOD, data_dir=None)._fetch_shom(
        source
    )

    assert captured["station_id"] == "152"


@pytest.mark.fast
def test_no_selector_at_all_is_refused(monkeypatch):
    _capture(monkeypatch)
    source = OceanicSourceConfig(source="shom")
    with pytest.raises(ValueError, match="station_ids"):
        _manager(source)._fetch_shom(source)


@pytest.mark.fast
def test_a_mask_gives_the_point_to_search_from_in_degrees(tmp_path, monkeypatch):
    """Anti-vacuity: the mask is in metres, so an unconverted centre is ~6.84e6."""
    captured = _capture(monkeypatch)
    source = OceanicSourceConfig(source="shom", mask_path=_mask(tmp_path))

    _manager(source)._fetch_shom(source)

    assert "station_id" not in captured, captured
    assert captured["near_lat"] == pytest.approx(48.4, abs=0.3), captured
    assert captured["near_lon"] == pytest.approx(-4.5, abs=0.3), captured


@pytest.mark.fast
def test_named_stations_skip_the_search_and_are_read_one_by_one(tmp_path, monkeypatch):
    calls: list[dict] = []

    def fake_fetch(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(shom, "fetch", fake_fetch)
    source = OceanicSourceConfig(source="shom", station_ids=["152", "170"])

    _manager(source, data_dir=tmp_path / "data")._fetch_shom(source)

    assert [c["station_id"] for c in calls] == ["152", "170"]
    assert all(c.get("near_lat") is None for c in calls), calls
    assert all(c["cache_dir"] == tmp_path / "data" for c in calls), calls


@pytest.mark.fast
def test_the_cache_lives_in_the_variable_data_directory(tmp_path, monkeypatch):
    """Where the committed SHOM seed already sits: ``data/oceanic/``."""
    captured = _capture(monkeypatch)
    source = OceanicSourceConfig(source="shom", mask_path=_mask(tmp_path))

    _manager(source, data_dir=tmp_path / "data" / "oceanic")._fetch_shom(source)

    assert captured["cache_dir"] == tmp_path / "data" / "oceanic"


@pytest.mark.fast
@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"station_id": "152", "near_lat": 48.0, "near_lon": -4.0},
    ],
)
def test_fetch_itself_refuses_an_ambiguous_or_empty_selector(kwargs):
    """The port-level rule stays a refusal: both arguments come from the caller."""
    with pytest.raises(ValueError, match="Not both, not neither"):
        shom.fetch(date_start=PERIOD[0], date_end=PERIOD[1], **kwargs)


@pytest.mark.fast
def test_fetch_refuses_half_a_point():
    with pytest.raises(ValueError, match="near_lat and near_lon"):
        shom.fetch(date_start=PERIOD[0], date_end=PERIOD[1], near_lat=48.0)


@pytest.mark.fast
def test_the_cache_round_trips_on_a_named_file(tmp_path):
    """The filename is the contract the committed seed CSV is stored under."""
    frame = pd.DataFrame({"timestamp": pd.to_datetime(["2003-01-01T00:00:00"]), "value": [1.25]})
    shom._write_cache(tmp_path, "152", PERIOD[0], PERIOD[1], frame)

    assert (tmp_path / "sealevel_shom_152_20030101_20030130_H.csv").exists()
    back = shom._try_load_cached(tmp_path, "152", PERIOD[0], PERIOD[1])
    assert back is not None
    assert back["value"].tolist() == [1.25]
    assert shom._try_load_cached(None, "152", PERIOD[0], PERIOD[1]) is None
