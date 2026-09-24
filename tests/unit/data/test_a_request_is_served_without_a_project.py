"""A data request is served from outside a project, one file per variable, cut to size.

Offline: every provider is replaced by a stub, and each test checks one promise
of ``run_request`` -- a chronicle, a grid, a raster and a vector each land as
one file cut to the extent and the period; an empty answer is a success; a
failed variable is listed and does not stop the others; the report's checksums
are those of the files.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data import DataRequest, DataStore, run_request
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.source.port import FetchResult, extent_for
from hydromodpy.data.variables.hydrometry.manager import HydrometryManager
from hydromodpy.data.variables.precipitation.manager import PrecipitationManager
from hydromodpy.schema.job.digest import sha256_file

REPO_ROOT = Path(__file__).resolve().parents[3]
BOX_2154 = [320000.0, 6780000.0, 330000.0, 6790000.0]


def _report(out: Path) -> dict:
    return json.loads((out / "request.json").read_text(encoding="utf-8"))


def _station(station_id: str, lon: float, lat: float, start: str, days: int) -> PointRecord:
    dates = pd.date_range(start, periods=days, freq="D")
    return PointRecord(
        station_id=station_id,
        variable="hydrometry",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": np.arange(days, dtype=float)}),
        date_start=dates[0].to_pydatetime(),
        date_end=dates[-1].to_pydatetime(),
        location=StationLocation(id=station_id, x=lon, y=lat, crs="EPSG:4326"),
    )


def test_a_chronicle_is_cut_to_the_period(tmp_path: Path, monkeypatch) -> None:
    def fake_hubeau(cfg, *, bbox, station_ids, start, end, context):
        return [_station("J0001", -1.7, 48.1, "2019-12-01", 120)]

    monkeypatch.setitem(HydrometryManager.SOURCES, "hubeau", fake_hubeau)
    request = DataRequest.for_variable(
        "hydrometry",
        station_ids=["J0001"],
        start="2020-01-01",
        end="2020-01-31",
    )

    run_request(request, tmp_path / "out")

    report = _report(tmp_path / "out")
    entry = report["files"][0]
    assert entry["kind"] == "points" and entry["stations"] == ["J0001"]
    table = pd.read_parquet(tmp_path / "out" / entry["path"])
    assert table["datetime"].min() == pd.Timestamp("2020-01-01")
    assert table["datetime"].max() == pd.Timestamp("2020-01-31")
    assert len(table) == 31


class _LargeGrid:
    """A SIM2 stand-in that answers with a grid larger than any request."""

    def variables(self, cfg):
        return [f"precipitation_{name}" for name in cfg.components]

    def __call__(self, cfg, *, bbox, period, context):
        import xarray as xr

        x = np.arange(300000.0, 360000.0, 8000.0)
        y = np.arange(6810000.0, 6760000.0, -8000.0)
        time = pd.date_range("2019-01-01", "2021-12-31", freq="D")
        data = np.ones((len(time), len(y), len(x)))
        dataset = xr.Dataset(
            {"precipitation_total": (("time", "y", "x"), data)},
            coords={"time": time, "y": y, "x": x},
        )
        return [
            FieldRecord(
                variable="precipitation_total",
                source="sim2",
                unit="mm/day",
                data=dataset,
                bbox=(300000.0, 6760000.0, 360000.0, 6810000.0),
                crs="EPSG:2154",
                date_start=time[0].to_pydatetime(),
                date_end=time[-1].to_pydatetime(),
                frequency="D",
            )
        ]


def test_a_grid_larger_than_the_request_is_cut(tmp_path: Path, monkeypatch) -> None:
    import xarray as xr

    monkeypatch.setitem(PrecipitationManager.SOURCES, "sim2", _LargeGrid())
    request = DataRequest.for_variable(
        "precipitation",
        bbox=BOX_2154,
        crs="EPSG:2154",
        start="2020-06-01",
        end="2020-06-30",
    )

    run_request(request, tmp_path / "out")

    entry = _report(tmp_path / "out")["files"][0]
    assert entry["kind"] == "fields"
    with xr.open_dataset(tmp_path / "out" / entry["path"]) as cut:
        assert float(cut["x"].min()) >= BOX_2154[0] and float(cut["x"].max()) <= BOX_2154[2]
        assert float(cut["y"].min()) >= BOX_2154[1] and float(cut["y"].max()) <= BOX_2154[3]
        assert cut.sizes["time"] == 30
        assert cut.sizes["x"] < 8


def _region_dem(path: Path) -> Path:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=200,
        width=200,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=from_origin(310000.0, 6800000.0, 100.0, 100.0),
        nodata=-9999,
    ) as dst:
        dst.write(np.ones((1, 200, 200), dtype="float32"))
    return path


def test_a_raster_larger_than_the_request_is_cut(tmp_path: Path) -> None:
    rasterio = pytest.importorskip("rasterio")
    dem = _region_dem(tmp_path / "dem_custom_region.tif")
    request = DataRequest.model_validate(
        {
            "data": {"dem": {"sources": [{"source": "custom", "path": str(dem)}]}},
            "extent": {"bbox": BOX_2154, "crs": "EPSG:2154"},
        }
    )

    run_request(request, tmp_path / "out", store=DataStore(data_root=tmp_path / "data"))

    entry = _report(tmp_path / "out")["files"][0]
    assert entry["kind"] == "raster"
    with rasterio.open(tmp_path / "out" / entry["path"]) as cut:
        assert cut.width == 100 and cut.height == 100
        assert cut.bounds.left == pytest.approx(BOX_2154[0])
        assert cut.bounds.top == pytest.approx(BOX_2154[3])


class _AcmeRivers:
    """A network source served through the registry, like BD Topage."""

    source_id: ClassVar[str] = "acme-rivers"
    payload_kind: ClassVar[str] = "features"
    extent_crs: ClassVar[str] = "EPSG:2154"
    selectors: ClassVar[tuple[str, ...]] = ("extent",)
    period_need: ClassVar[str] = "refused"
    hosts: ClassVar[tuple[str, ...]] = ()
    writes_out_dir: ClassVar[bool] = False

    def __init__(self) -> None:
        self.variables = ("hydrography",)

    def fetch(self, request):
        import geopandas as gpd
        from shapely.geometry import LineString

        extent = extent_for(self, request)
        frame = gpd.GeoDataFrame(
            {"name": ["inside", "outside"]},
            geometry=[
                LineString([(321000, 6781000), (322000, 6782000)]),
                LineString([(350000, 6800000), (351000, 6801000)]),
            ],
            crs="EPSG:2154",
        )
        return FetchResult(
            source_id=self.source_id,
            kind="features",
            variables=self.variables,
            extent=extent,
            period=None,
            features=frame,
        )


def test_a_network_is_cut_to_the_box(tmp_path: Path, isolated_registry) -> None:
    import geopandas as gpd

    isolated_registry.register(_AcmeRivers)
    request = DataRequest.model_validate(
        {
            "data": {"hydrography": {"sources": [{"source": "acme-rivers"}]}},
            "extent": {"bbox": BOX_2154, "crs": "EPSG:2154"},
        }
    )

    run_request(request, tmp_path / "out")

    entry = _report(tmp_path / "out")["files"][0]
    assert entry["kind"] == "vector"
    network = gpd.read_file(tmp_path / "out" / entry["path"])
    assert list(network["name"]) == ["inside"]


def test_an_empty_answer_is_a_success(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(HydrometryManager.SOURCES, "hubeau", lambda cfg, **kwargs: [])
    request = DataRequest.for_variable(
        "hydrometry",
        bbox=[-5.0, 47.0, -4.9, 47.1],
        crs="EPSG:4326",
        start="2020-01-01",
        end="2020-12-31",
    )

    report = run_request(request, tmp_path / "out")

    assert report.failures == ()
    document = _report(tmp_path / "out")
    assert document["files"][0]["empty"] is True
    assert document["files"][0]["path"] is None


def test_a_failed_variable_is_listed_and_the_others_are_served(tmp_path: Path, monkeypatch) -> None:
    def boom(cfg, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setitem(HydrometryManager.SOURCES, "hubeau", boom)
    monkeypatch.setitem(PrecipitationManager.SOURCES, "sim2", _LargeGrid())
    request = DataRequest.model_validate(
        {
            "data": {
                "hydrometry": {"sources": [{"source": "hubeau"}]},
                "precipitation": {"sources": [{"source": "sim2"}]},
            },
            "extent": {"bbox": BOX_2154, "crs": "EPSG:2154"},
            "period": {"start": "2020-01-01", "end": "2020-01-10"},
        }
    )

    run_request(request, tmp_path / "out")

    document = _report(tmp_path / "out")
    assert [f["variable"] for f in document["failures"]] == ["hydrometry"]
    assert "provider down" in document["failures"][0]["error"]
    assert [f["variable"] for f in document["files"]] == ["precipitation"]


def test_the_report_names_each_file_by_its_checksum(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(PrecipitationManager.SOURCES, "sim2", _LargeGrid())
    request = DataRequest.for_variable(
        "precipitation", bbox=BOX_2154, crs="EPSG:2154", start="2020-01-01", end="2020-01-05"
    )

    run_request(request, tmp_path / "out")

    for entry in _report(tmp_path / "out")["files"]:
        digest, size = sha256_file(tmp_path / "out" / entry["path"])
        assert (entry["sha256"], entry["bytes"]) == (digest, size)


_NO_WHITEBOX_SCRIPT = """
import sys
from pathlib import Path
from typing import ClassVar

import geopandas as gpd
from shapely.geometry import LineString

from hydromodpy.data import DataRequest, run_request
from hydromodpy.data.source import registry
from hydromodpy.data.source.port import FetchResult, extent_for


class Rivers:
    source_id: ClassVar[str] = "acme-rivers"
    payload_kind: ClassVar[str] = "features"
    extent_crs: ClassVar[str] = "EPSG:2154"
    selectors: ClassVar[tuple] = ("extent",)
    period_need: ClassVar[str] = "refused"
    hosts: ClassVar[tuple] = ()
    writes_out_dir: ClassVar[bool] = False

    def __init__(self):
        self.variables = ("hydrography",)

    def fetch(self, request):
        frame = gpd.GeoDataFrame(
            geometry=[LineString([(321000, 6781000), (322000, 6782000)])], crs="EPSG:2154"
        )
        return FetchResult(
            source_id=self.source_id, kind="features", variables=self.variables,
            extent=extent_for(self, request), period=None, features=frame,
        )


registry.register(Rivers)
request = DataRequest.model_validate({
    "data": {"hydrography": {"sources": [{"source": "acme-rivers"}]}},
    "extent": {"bbox": [320000.0, 6780000.0, 330000.0, 6790000.0], "crs": "EPSG:2154"},
})
run_request(request, Path(sys.argv[1]))
print(sorted(name for name in sys.modules if name.startswith("whitebox")))
"""


@pytest.mark.allow_subprocess
def test_a_network_request_loads_no_whitebox(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", _NO_WHITEBOX_SCRIPT, str(tmp_path / "out")],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    assert completed.stdout.strip().splitlines()[-1] == "[]"
    assert (tmp_path / "out" / "hydrography_acme-rivers.gpkg").is_file()


def test_a_period_is_a_closed_window(tmp_path: Path) -> None:
    request = DataRequest.for_variable(
        "hydrometry", station_ids=["J0001"], start="2020-01-01", end="2020-12-31"
    )
    assert request.period.start == datetime(2020, 1, 1)
    with pytest.raises(ValueError, match="before it starts"):
        DataRequest.for_variable(
            "hydrometry", station_ids=["J0001"], start="2020-12-31", end="2020-01-01"
        )


def test_the_last_day_of_the_period_is_kept_whole(tmp_path: Path, monkeypatch) -> None:
    hours = pd.date_range("2020-01-30", "2020-02-01 23:00", freq="h")
    hourly = PointRecord(
        station_id="J0001",
        variable="hydrometry",
        source="hubeau",
        unit="m3/s",
        frequency="h",
        data=pd.DataFrame({"datetime": hours, "value": np.ones(len(hours))}),
        date_start=hours[0].to_pydatetime(),
        date_end=hours[-1].to_pydatetime(),
        location=StationLocation(id="J0001", x=-1.7, y=48.1, crs="EPSG:4326"),
    )
    monkeypatch.setitem(HydrometryManager.SOURCES, "hubeau", lambda cfg, **kwargs: [hourly])
    request = DataRequest.for_variable(
        "hydrometry", station_ids=["J0001"], start="2020-01-31", end="2020-01-31"
    )

    run_request(request, tmp_path / "out")

    entry = _report(tmp_path / "out")["files"][0]
    table = pd.read_parquet(tmp_path / "out" / entry["path"])
    assert len(table) == 24
    assert entry["period"] == ["2020-01-31T00:00:00", "2020-01-31T23:00:00"]


class _TwoSourceStore:
    """A store whose DEM comes back from two sources, the second one broken."""

    def __init__(self, good: Path) -> None:
        self.good = good

    def load_dem(self, section, *, project_extent):
        def raster(source: str, path: Path) -> FieldRecord:
            return FieldRecord(
                variable="dem",
                source=source,
                unit="m",
                data=path,
                bbox=(310000.0, 6780000.0, 330000.0, 6800000.0),
                crs="EPSG:2154",
            )

        return LoadResult(
            fields=[
                raster("custom", self.good),
                raster("mirror", self.good),
                raster("mirror", self.good.with_name("absent.tif")),
            ]
        )


def test_a_failed_source_leaves_no_file_and_the_other_source_keeps_its_own(
    tmp_path: Path,
) -> None:
    dem = _region_dem(tmp_path / "dem_custom_region.tif")
    request = DataRequest.model_validate(
        {
            "data": {"dem": {"sources": [{"source": "custom", "path": str(dem)}]}},
            "extent": {"bbox": BOX_2154, "crs": "EPSG:2154"},
        }
    )

    run_request(request, tmp_path / "out", store=_TwoSourceStore(dem))

    document = _report(tmp_path / "out")
    assert [(f["variable"], f["source"]) for f in document["failures"]] == [("dem", "mirror")]
    assert [f["path"] for f in document["files"]] == ["dem_custom.tif"]
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [
        "dem_custom.tif",
        "request.json",
    ]


def test_a_mask_that_is_not_there_writes_nothing(tmp_path: Path) -> None:
    request = DataRequest.for_variable("dem", mask=tmp_path / "absent.gpkg")

    with pytest.raises(FileNotFoundError, match="absent.gpkg"):
        run_request(request, tmp_path / "out")
    assert not (tmp_path / "out").exists()
