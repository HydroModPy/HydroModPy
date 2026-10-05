"""``[data.crossings]``: the config, the custom file, the manager and the resolver.

No network: a downloading source is replaced in ``CrossingsManager.SOURCES`` by
a function that answers with a recorded sample.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from pydantic import ValidationError
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.data import DataManagersConfig
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
from hydromodpy.data.variables.crossings import records
from hydromodpy.data.variables.crossings.apis import bdtopo, roe
from hydromodpy.data.variables.crossings.config import (
    BdtopoCrossingsSource,
    CrossingsConfig,
    CustomCrossingsSource,
    RoeCrossingsSource,
)
from hydromodpy.data.variables.crossings.manager import CrossingsManager, cache_file_name
from hydromodpy.data.variables.crossings.resolver import (
    resolve_crossings_path_from_data_sources,
)

SAMPLES = Path(__file__).parent / "samples" / "crossings"


def _bdtopo_sample() -> gpd.GeoDataFrame:
    features = lambda name: json.loads((SAMPLES / name).read_text(encoding="utf-8"))["features"]  # noqa: E731
    return bdtopo.to_records(features("bdtopo_route.json"), features("bdtopo_voie_ferree.json"))


def _roe_sample() -> gpd.GeoDataFrame:
    return roe.to_records(roe.parse_page((SAMPLES / "roe_obstacles.gml").read_bytes()))


def _custom_file(path: Path, **columns: list) -> Path:
    n = len(next(iter(columns.values()))) if columns else 1
    geometry = [
        LineString([(345000.0 + i, 6805000.0), (345010.0 + i, 6805100.0)]) for i in range(n)
    ]
    gpd.GeoDataFrame(columns, geometry=geometry, crs="EPSG:2154").to_file(path, driver="GPKG")
    return path


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Replace both providers with their sample, and record the boxes they were asked.

    The sample is handed out in pages of four records, as the providers do.
    """
    asked: list[tuple] = []

    def _answer(sample):
        def fetch(source_cfg, *, bbox, context):
            asked.append(bbox)
            frame = sample()
            for start in range(0, len(frame), 4):
                yield frame.iloc[start : start + 4]

        return fetch

    monkeypatch.setitem(CrossingsManager.SOURCES, "bdtopo", _answer(_bdtopo_sample))
    monkeypatch.setitem(CrossingsManager.SOURCES, "roe", _answer(_roe_sample))
    return asked


# --- config -----------------------------------------------------------------


def test_the_section_validates_the_three_sources() -> None:
    cfg = DataManagersConfig.from_toml_section(
        {
            "types": ["crossings"],
            "crossings": {
                "sources": [
                    {"source": "bdtopo"},
                    {"source": "roe", "page_size": 500},
                    {"source": "custom", "path": "x.gpkg"},
                ]
            },
        },
        base_dir=Path("."),
    )

    kinds = [type(source) for source in cfg.crossings.sources]
    assert kinds == [BdtopoCrossingsSource, RoeCrossingsSource, CustomCrossingsSource]


def test_a_custom_source_without_a_path_is_refused() -> None:
    with pytest.raises(ValidationError, match="path"):
        CrossingsConfig(sources=[{"source": "custom"}])


def test_a_source_nobody_serves_is_refused() -> None:
    with pytest.raises(ValidationError):
        CrossingsConfig(sources=[{"source": "osm"}])


def test_an_unknown_key_of_a_source_is_refused() -> None:
    with pytest.raises(ValidationError):
        CrossingsConfig(sources=[{"source": "bdtopo", "typename": "x"}])


def test_the_section_needs_a_source() -> None:
    with pytest.raises(ValidationError):
        CrossingsConfig(sources=[])


# --- custom -----------------------------------------------------------------


def test_a_custom_file_without_kind_is_refused_by_name(tmp_path: Path) -> None:
    path = _custom_file(tmp_path / "roads.gpkg", name=["a"])
    manager = CrossingsManager(
        config=CrossingsConfig(sources=[CustomCrossingsSource(path=path)]),
        catalog=None,
        data_dir=tmp_path / "data" / "crossings",
    )

    with pytest.raises(ValueError, match=r"roads\.gpkg has no 'kind' column"):
        manager.load()


def test_a_custom_file_with_a_kind_outside_the_list_is_refused_by_name(tmp_path: Path) -> None:
    path = _custom_file(tmp_path / "roads.gpkg", kind=["road", "ford", "tunnel"])
    manager = CrossingsManager(
        config=CrossingsConfig(sources=[CustomCrossingsSource(path=path)]),
        catalog=None,
        data_dir=tmp_path / "data" / "crossings",
    )

    with pytest.raises(ValueError, match=r"\['ford', 'tunnel'\]"):
        manager.load()


def test_a_custom_file_is_normalised_and_indexed(tmp_path: Path) -> None:
    path = _custom_file(
        tmp_path / "roads.gpkg", kind=["Road", " weir"], name=["a", None], drop_m=[None, 0.8]
    )
    catalog = DataCatalogDuckDB()
    manager = CrossingsManager(
        config=CrossingsConfig(sources=[CustomCrossingsSource(path=path)]),
        catalog=catalog,
        data_dir=tmp_path / "data" / "crossings",
    )

    (record,) = manager.load().fields

    frame = gpd.read_parquet(record.data)
    assert list(frame.columns) == [*records.ATTRIBUTES, "geometry"]
    assert frame["kind"].tolist() == ["road", "weir"]
    assert frame["name"].tolist() == ["a", ""]
    assert frame["drop_m"].isna().tolist() == [True, False]
    assert set(frame["source"]) == {"custom"}
    assert "blobs" in record.data.parts
    assert record.source == "custom"
    assert catalog.find_cached(variable="crossings", source="custom", bbox=record.bbox) is not None


@pytest.mark.filterwarnings("ignore:.crs. was not provided")
def test_a_custom_file_without_crs_takes_default_crs(tmp_path: Path) -> None:
    path = tmp_path / "bare.shp"
    gpd.GeoDataFrame({"kind": ["road"]}, geometry=[Point(1.0, 2.0)]).to_file(path)
    manager = CrossingsManager(
        config=CrossingsConfig(
            sources=[CustomCrossingsSource(path=path, default_crs="EPSG:27572")]
        ),
        catalog=None,
        data_dir=tmp_path / "data" / "crossings",
    )

    (record,) = manager.load().fields

    assert record.crs == "EPSG:27572"


# --- manager ----------------------------------------------------------------


def _mask(tmp_path: Path) -> Path:
    path = tmp_path / "watershed.gpkg"
    gpd.GeoDataFrame(geometry=[Point(345000.0, 6805000.0).buffer(2000.0)], crs="EPSG:2154").to_file(
        path, driver="GPKG"
    )
    return path


def test_a_download_is_cached_under_its_source_prefix_and_served_again(
    tmp_path: Path, offline: list[tuple]
) -> None:
    config = CrossingsConfig(
        sources=[BdtopoCrossingsSource(), RoeCrossingsSource()], mask_path=_mask(tmp_path)
    )
    manager = CrossingsManager(
        config=config, catalog=DataCatalogDuckDB(), data_dir=tmp_path / "data" / "crossings"
    )

    first = manager.load().fields
    second = manager.load().fields

    assert [r.source for r in first] == ["bdtopo", "roe"]
    names = [Path(r.data).name for r in first]
    assert names[0].startswith("crossings_bdtopo_") and names[0].endswith(".gpkg")
    assert names[1].startswith("crossings_roe_")
    assert names[0] == cache_file_name("bdtopo", offline[0])
    assert all(Path(r.data).exists() for r in first)
    assert len(offline) == 2, "the second load must come from the catalog"
    assert [r.data for r in second] == [r.data for r in first]
    assert gpd.read_file(first[0].data).shape[0] == 9


def test_force_refresh_downloads_again(tmp_path: Path, offline: list[tuple]) -> None:
    config = CrossingsConfig(
        sources=[RoeCrossingsSource(force_refresh=True)], mask_path=_mask(tmp_path)
    )
    manager = CrossingsManager(config=config, catalog=DataCatalogDuckDB(), data_dir=tmp_path)

    manager.load()
    manager.load()

    assert len(offline) == 2


def test_the_box_is_the_mask_bounds_in_the_crs_the_providers_answer_in(
    tmp_path: Path, offline: list[tuple]
) -> None:
    mask = tmp_path / "watershed_wgs84.gpkg"
    gpd.GeoDataFrame(geometry=[Point(345000.0, 6805000.0).buffer(2000.0)], crs="EPSG:2154").to_crs(
        "EPSG:4326"
    ).to_file(mask, driver="GPKG")
    manager = CrossingsManager(
        config=CrossingsConfig(sources=[RoeCrossingsSource()], mask_path=mask),
        catalog=None,
        data_dir=tmp_path,
    )

    manager.load()

    xmin, ymin, xmax, ymax = offline[0]
    assert xmin == pytest.approx(343000.0, abs=1.0)
    assert xmax == pytest.approx(347000.0, abs=1.0)
    assert ymin == pytest.approx(6803000.0, abs=1.0)
    assert ymax == pytest.approx(6807000.0, abs=1.0)


def test_a_download_without_a_box_is_refused(tmp_path: Path, offline: list[tuple]) -> None:
    manager = CrossingsManager(
        config=CrossingsConfig(sources=[RoeCrossingsSource()]), catalog=None, data_dir=tmp_path
    )

    with pytest.raises(DataRequestError, match="mask_path"):
        manager.load()
    assert offline == []


# --- resolver ---------------------------------------------------------------


def _write_raster(path: Path, left: float, top: float, size: float) -> Path:
    profile = {
        "driver": "GTiff",
        "height": 4,
        "width": 4,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:2154",
        "transform": from_origin(left, top, size / 4, size / 4),
        "nodata": -9999.0,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.zeros((4, 4), dtype="float32"), 1)
    return path


def _cfg(sources: list, *, dem_init_path: Path | None = None, x_outlet: float | None = 345000.0):
    return SimpleNamespace(
        data=SimpleNamespace(crossings=SimpleNamespace(sources=sources)),
        geographic=SimpleNamespace(
            x_outlet=x_outlet,
            y_outlet=6805000.0,
            crs_project="EPSG:2154",
            dem_init_path=dem_init_path,
        ),
    )


def test_without_a_section_the_resolver_answers_none(tmp_path: Path) -> None:
    config_path = tmp_path / "p.toml"

    assert (
        resolve_crossings_path_from_data_sources(
            SimpleNamespace(data=None), config_path=config_path
        )
        is None
    )
    assert (
        resolve_crossings_path_from_data_sources(
            SimpleNamespace(data=SimpleNamespace(crossings=None)), config_path=config_path
        )
        is None
    )


def test_a_custom_source_is_resolved_against_the_toml_and_normalised(tmp_path: Path) -> None:
    _custom_file(tmp_path / "roads.gpkg", kind=["road", "bridge"], name=["a", "b"])
    cfg = _cfg([CustomCrossingsSource(path=Path("roads.gpkg"))])

    path = resolve_crossings_path_from_data_sources(
        cfg, config_path=tmp_path / "p.toml", cache_dir=tmp_path / "cache"
    )

    assert path is not None and path.parent == tmp_path / "cache"
    assert path.name.startswith("crossings_ground_custom_")
    frame = gpd.read_file(path)
    assert list(frame.columns) == [*records.ATTRIBUTES, "geometry"]
    assert frame["kind"].tolist() == ["road", "bridge"]


def test_a_folder_gives_its_first_vector_file(tmp_path: Path) -> None:
    folder = tmp_path / "structures"
    folder.mkdir()
    _custom_file(folder / "roads.gpkg", kind=["road"])
    cfg = _cfg([CustomCrossingsSource(path=folder)])

    path = resolve_crossings_path_from_data_sources(
        cfg, config_path=tmp_path / "p.toml", cache_dir=tmp_path / "cache"
    )

    assert gpd.read_file(path)["kind"].tolist() == ["road"]


def test_the_resolver_refuses_a_custom_file_without_kind(tmp_path: Path) -> None:
    _custom_file(tmp_path / "roads.gpkg", name=["a"])
    cfg = _cfg([CustomCrossingsSource(path=Path("roads.gpkg"))])

    with pytest.raises(ValueError, match="has no 'kind' column"):
        resolve_crossings_path_from_data_sources(
            cfg, config_path=tmp_path / "p.toml", cache_dir=tmp_path / "cache"
        )


def test_a_missing_custom_file_is_named(tmp_path: Path) -> None:
    cfg = _cfg([CustomCrossingsSource(path=Path("gone.gpkg"))])

    with pytest.raises(FileNotFoundError, match="gone.gpkg"):
        resolve_crossings_path_from_data_sources(cfg, config_path=tmp_path / "p.toml")


def test_the_merge_is_in_the_project_crs_and_keeps_every_source(
    tmp_path: Path, offline: list[tuple]
) -> None:
    _custom_file(tmp_path / "roads.gpkg", kind=["road"])
    cfg = _cfg(
        [
            BdtopoCrossingsSource(),
            RoeCrossingsSource(),
            CustomCrossingsSource(path=Path("roads.gpkg")),
        ]
    )
    cfg.geographic.crs_project = "EPSG:27572"

    path = resolve_crossings_path_from_data_sources(
        cfg, config_path=tmp_path / "p.toml", cache_dir=tmp_path / "cache"
    )

    frame = gpd.read_file(path)
    assert frame.crs.to_epsg() == 27572
    assert frame["source"].value_counts().to_dict() == {"bdtopo": 9, "roe": 5, "custom": 1}


def test_an_api_source_is_asked_over_the_outlet_box_and_cached_under_its_prefix(
    tmp_path: Path, offline: list[tuple]
) -> None:
    cfg = _cfg([BdtopoCrossingsSource(), RoeCrossingsSource()])
    kwargs = {"config_path": tmp_path / "p.toml", "cache_dir": tmp_path / "cache"}

    first = resolve_crossings_path_from_data_sources(cfg, **kwargs)
    second = resolve_crossings_path_from_data_sources(cfg, **kwargs)

    assert first == second
    assert first.name.startswith("crossings_ground_bdtopo_roe_") and first.suffix == ".gpkg"
    assert offline[0] == (315000.0, 6775000.0, 375000.0, 6835000.0)
    assert len(offline) == 2, "the second call must reuse the file"


def test_force_refresh_asks_the_provider_again(tmp_path: Path, offline: list[tuple]) -> None:
    cfg = _cfg([RoeCrossingsSource(force_refresh=True)])
    kwargs = {"config_path": tmp_path / "p.toml", "cache_dir": tmp_path / "cache"}

    resolve_crossings_path_from_data_sources(cfg, **kwargs)
    resolve_crossings_path_from_data_sources(cfg, **kwargs)

    assert len(offline) == 2


def test_the_box_is_clipped_to_the_dem_footprint(tmp_path: Path, offline: list[tuple]) -> None:
    dem = _write_raster(tmp_path / "dem.tif", left=340000.0, top=6810000.0, size=10000.0)
    cfg = _cfg([RoeCrossingsSource()], dem_init_path=dem)

    resolve_crossings_path_from_data_sources(
        cfg, config_path=tmp_path / "p.toml", cache_dir=tmp_path / "cache"
    )

    assert offline[0] == pytest.approx((340000.0, 6800000.0, 350000.0, 6810000.0))


def test_an_outlet_outside_the_dem_is_refused(tmp_path: Path, offline: list[tuple]) -> None:
    dem = _write_raster(tmp_path / "dem.tif", left=100000.0, top=6200000.0, size=10000.0)
    cfg = _cfg([RoeCrossingsSource()], dem_init_path=dem)

    with pytest.raises(ValueError, match="does not meet the DEM footprint"):
        resolve_crossings_path_from_data_sources(cfg, config_path=tmp_path / "p.toml")


def test_an_api_source_without_an_outlet_is_refused(tmp_path: Path, offline: list[tuple]) -> None:
    cfg = _cfg([RoeCrossingsSource()], x_outlet=None)

    with pytest.raises(ValueError, match="x_outlet"):
        resolve_crossings_path_from_data_sources(cfg, config_path=tmp_path / "p.toml")
    assert offline == []


def test_a_box_without_any_crossing_is_refused(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(
        CrossingsManager.SOURCES,
        "roe",
        lambda source_cfg, *, bbox, context: iter([records.empty("EPSG:2154")]),
    )
    cfg = _cfg([RoeCrossingsSource()])

    with pytest.raises(ValueError, match="no crossing"):
        resolve_crossings_path_from_data_sources(
            cfg, config_path=tmp_path / "p.toml", cache_dir=tmp_path / "cache"
        )


def test_a_changed_custom_file_is_a_new_cache_file(tmp_path: Path) -> None:
    roads = _custom_file(tmp_path / "roads.gpkg", kind=["road"])
    cfg = _cfg([CustomCrossingsSource(path=Path("roads.gpkg"))])
    kwargs = {"config_path": tmp_path / "p.toml", "cache_dir": tmp_path / "cache"}

    before = resolve_crossings_path_from_data_sources(cfg, **kwargs)
    _custom_file(roads, kind=["road", "bridge"])
    after = resolve_crossings_path_from_data_sources(cfg, **kwargs)

    assert before != after
    assert gpd.read_file(after).shape[0] == 2


def test_the_pages_of_a_download_are_written_as_they_arrive(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    """The file holds the first page while the second is still to be fetched."""
    cache = tmp_path / "cache"
    held: list[int] = []

    def fetch(source_cfg, *, bbox, context):
        sample = _roe_sample()
        for start in range(0, len(sample), 2):
            staged = list(cache.glob("*.tmp-*.gpkg"))
            held.append(len(gpd.read_file(staged[0])) if staged else 0)
            yield sample.iloc[start : start + 2]

    monkeypatch.setitem(CrossingsManager.SOURCES, "roe", fetch)
    cfg = _cfg([RoeCrossingsSource()])

    with caplog.at_level("INFO"):
        out = resolve_crossings_path_from_data_sources(
            cfg, config_path=tmp_path / "p.toml", cache_dir=cache
        )

    assert held == [0, 2, 4]
    assert len(gpd.read_file(out)) == 5
    assert not list(cache.glob("*.tmp-*.gpkg"))
    messages = [record.getMessage() for record in caplog.records]
    assert any("Crossings from roe: 5 features in" in message for message in messages)


def test_a_failure_in_the_middle_of_the_pages_leaves_no_file(tmp_path: Path, monkeypatch) -> None:
    cache = tmp_path / "cache"

    def fetch(source_cfg, *, bbox, context):
        yield _roe_sample().iloc[:2]
        raise RuntimeError("the service stopped")

    monkeypatch.setitem(CrossingsManager.SOURCES, "roe", fetch)
    cfg = _cfg([RoeCrossingsSource()])

    with pytest.raises(RuntimeError, match="stopped"):
        resolve_crossings_path_from_data_sources(
            cfg, config_path=tmp_path / "p.toml", cache_dir=cache
        )

    assert list(cache.glob("*.gpkg")) == []
