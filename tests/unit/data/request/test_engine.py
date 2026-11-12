"""``run_request``: a data request served offline, one file per variable, cut to size.

Every provider is replaced by a stub. A chronicle, a grid, a raster and a vector each
land as one file cut to the extent (m or degrees) and the period; an empty answer is a
success; a failed variable is listed and does not stop the others; the report holds the
checksum of each file; the bounds of the call refuse a host before it is contacted.
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

from hydromodpy.core.exceptions import JobInputNotFoundError
from hydromodpy.core.io.file_digest import sha256_and_size
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.loading.store import DataStore
from hydromodpy.data.request.engine import run_request
from hydromodpy.data.request.model import DataRequest
from hydromodpy.data.source.port import FetchRequest, FetchResult, extent_for

REPO_ROOT = Path(__file__).resolve().parents[4]
BOX_2154 = [320000.0, 6780000.0, 330000.0, 6790000.0]


def read_report(out: Path) -> dict:
    return json.loads((out / "request.json").read_text(encoding="utf-8"))


def station(
    station_id: str = "J0001",
    lon: float = -1.7,
    lat: float = 48.1,
    start: str = "2019-12-01",
    days: int = 61,
) -> PointRecord:
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


def hubeau_double(
    answers: list[PointRecord] | None = None,
    *,
    raises: Exception | None = None,
    hosts: tuple[str, ...] = (),
) -> type:
    """The class behind the ``("hydrometry", "hubeau")`` key, answering what the test hands it."""

    class StubHubeau:
        source_id: ClassVar[str] = "hubeau"
        section: ClassVar[str] = "hydrometry"
        payload_kind: ClassVar[str] = "points"
        extent_crs: ClassVar[str] = "EPSG:4326"
        selectors: ClassVar[tuple[str, ...]] = ("extent", "station_ids")
        period_need: ClassVar[str] = "required"
        writes_out_dir: ClassVar[bool] = False

        def __init__(self):
            self.variables: tuple[str, ...] = ("hydrometry",)
            self.hosts: tuple[str, ...] = hosts

        def fetch(self, request: FetchRequest) -> FetchResult:
            if raises is not None:
                raise raises
            return FetchResult(
                source_id=self.source_id,
                kind=self.payload_kind,
                variables=self.variables,
                points=tuple(answers or ()),
            )

    return StubHubeau


def test_chronicle_is_cut_to_the_period(tmp_path: Path, isolated_registry):
    isolated_registry.register(hubeau_double([station(days=120)]), replace=True)
    request = DataRequest.for_variable(
        "hydrometry",
        station_ids=["J0001"],
        start="2020-01-01",
        end="2020-01-31",
    )

    run_request(request, tmp_path / "out")

    report = read_report(tmp_path / "out")
    entry = report["files"][0]
    assert entry["kind"] == "points" and entry["stations"] == ["J0001"]
    table = pd.read_parquet(tmp_path / "out" / entry["path"])
    assert table["datetime"].min() == pd.Timestamp("2020-01-01")
    assert table["datetime"].max() == pd.Timestamp("2020-01-31")
    assert len(table) == 31


class LargeGrid:
    """A SIM2 stand-in that answers with a grid larger than any request."""

    source_id: ClassVar[str] = "sim2"
    section: ClassVar[str] = "precipitation"
    payload_kind: ClassVar[str] = "fields"
    extent_crs: ClassVar[str] = "EPSG:2154"
    selectors: ClassVar[tuple[str, ...]] = ("extent",)
    period_need: ClassVar[str] = "required"
    writes_out_dir: ClassVar[bool] = False

    def __init__(self, *, components: list[str] | None = None, **_options: object):
        self.components = components
        self.variables: tuple[str, ...] = (
            tuple(f"precipitation_{name}" for name in components) if components else ()
        )
        self.hosts: tuple[str, ...] = ()

    def fetch(self, request: FetchRequest) -> FetchResult:
        import xarray as xr

        time = pd.date_range("2019-01-01", "2021-12-31", freq="D")
        x = np.arange(300000.0, 360000.0, 8000.0)
        y = np.arange(6810000.0, 6760000.0, -8000.0)
        data = np.ones((len(time), len(y), len(x)))
        records = []
        for name in self.variables or ("precipitation_total",):
            dataset = xr.Dataset(
                {name: (("time", "y", "x"), data)},
                coords={"time": time, "y": y, "x": x},
            )
            records.append(
                FieldRecord(
                    variable=name,
                    source="sim2",
                    unit="mm/day",
                    data=dataset,
                    bbox=(300000.0, 6760000.0, 360000.0, 6810000.0),
                    crs="EPSG:2154",
                    date_start=time[0].to_pydatetime(),
                    date_end=time[-1].to_pydatetime(),
                    frequency="D",
                )
            )
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables or ("precipitation_total",),
            extent=extent_for(self, request),
            period=request.period,
            fields=tuple(records),
        )


def test_grid_is_cut_to_the_box(tmp_path: Path, isolated_registry):
    import xarray as xr

    isolated_registry.register(LargeGrid, replace=True)
    request = DataRequest.for_variable(
        "precipitation",
        bbox=BOX_2154,
        crs="EPSG:2154",
        start="2020-06-01",
        end="2020-06-30",
    )

    run_request(request, tmp_path / "out")

    entry = read_report(tmp_path / "out")["files"][0]
    assert entry["kind"] == "fields"
    with xr.open_dataset(tmp_path / "out" / entry["path"]) as cut:
        assert float(cut["x"].min()) >= BOX_2154[0] and float(cut["x"].max()) <= BOX_2154[2]
        assert float(cut["y"].min()) >= BOX_2154[1] and float(cut["y"].max()) <= BOX_2154[3]
        assert cut.sizes["time"] == 30
        assert cut.sizes["x"] < 8


def region_dem(path: Path) -> Path:
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


def test_raster_is_cut_to_the_box(tmp_path: Path):
    rasterio = pytest.importorskip("rasterio")
    dem = region_dem(tmp_path / "dem_custom_region.tif")
    request = DataRequest.model_validate(
        {
            "data": {"dem": {"sources": [{"source": "file", "path": str(dem)}]}},
            "extent": {"bbox": BOX_2154, "crs": "EPSG:2154"},
        }
    )

    run_request(request, tmp_path / "out", store=DataStore(data_root=tmp_path / "data"))

    entry = read_report(tmp_path / "out")["files"][0]
    assert entry["kind"] == "raster"
    with rasterio.open(tmp_path / "out" / entry["path"]) as cut:
        assert cut.width == 100 and cut.height == 100
        assert cut.bounds.left == pytest.approx(BOX_2154[0])
        assert cut.bounds.top == pytest.approx(BOX_2154[3])


class AcmeRivers:
    """A network source served through the registry, like BD Topage."""

    source_id: ClassVar[str] = "acme-rivers"
    section: ClassVar[str] = "hydrography"
    payload_kind: ClassVar[str] = "features"
    extent_crs: ClassVar[str] = "EPSG:2154"
    selectors: ClassVar[tuple[str, ...]] = ("extent",)
    period_need: ClassVar[str] = "refused"
    hosts: ClassVar[tuple[str, ...]] = ()
    writes_out_dir: ClassVar[bool] = False

    def __init__(self):
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


def test_network_is_cut_to_the_box(tmp_path: Path, isolated_registry):
    import geopandas as gpd

    isolated_registry.register(AcmeRivers)
    request = DataRequest.model_validate(
        {
            "data": {"hydrography": {"sources": [{"source": "acme-rivers"}]}},
            "extent": {"bbox": BOX_2154, "crs": "EPSG:2154"},
        }
    )

    run_request(request, tmp_path / "out")

    entry = read_report(tmp_path / "out")["files"][0]
    assert entry["kind"] == "vector"
    network = gpd.read_file(tmp_path / "out" / entry["path"])
    assert list(network["name"]) == ["inside"]


def test_empty_answer_is_a_success(tmp_path: Path, isolated_registry):
    isolated_registry.register(hubeau_double(), replace=True)
    request = DataRequest.for_variable(
        "hydrometry",
        bbox=[-5.0, 47.0, -4.9, 47.1],
        crs="EPSG:4326",
        start="2020-01-01",
        end="2020-12-31",
    )

    report = run_request(request, tmp_path / "out")

    assert report.failures == ()
    document = read_report(tmp_path / "out")
    assert document["files"][0]["empty"] is True
    assert document["files"][0]["path"] is None


def test_failed_variable_is_isolated(tmp_path: Path, isolated_registry):
    isolated_registry.register(hubeau_double(raises=RuntimeError("provider down")), replace=True)
    isolated_registry.register(LargeGrid, replace=True)
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

    document = read_report(tmp_path / "out")
    assert [f["variable"] for f in document["failures"]] == ["hydrometry"]
    assert "provider down" in document["failures"][0]["error"]
    assert [f["variable"] for f in document["files"]] == ["precipitation"]


def test_report_holds_the_checksums(tmp_path: Path, isolated_registry):
    isolated_registry.register(LargeGrid, replace=True)
    request = DataRequest.for_variable(
        "precipitation", bbox=BOX_2154, crs="EPSG:2154", start="2020-01-01", end="2020-01-05"
    )

    run_request(request, tmp_path / "out")

    for entry in read_report(tmp_path / "out")["files"]:
        digest, size = sha256_and_size(tmp_path / "out" / entry["path"])
        assert (entry["sha256"], entry["bytes"]) == (digest, size)


NO_WHITEBOX_SCRIPT = """
import sys
from pathlib import Path
from typing import ClassVar

import geopandas as gpd
from shapely.geometry import LineString

from hydromodpy.data.request.engine import run_request
from hydromodpy.data.request.model import DataRequest
from hydromodpy.data.source.registry import data_sources
from hydromodpy.data.source.port import FetchResult, extent_for


class Rivers:
    source_id: ClassVar[str] = "acme-rivers"
    section: ClassVar[str] = "hydrography"
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


data_sources.register(Rivers)
request = DataRequest.model_validate({
    "data": {"hydrography": {"sources": [{"source": "acme-rivers"}]}},
    "extent": {"bbox": [320000.0, 6780000.0, 330000.0, 6790000.0], "crs": "EPSG:2154"},
})
run_request(request, Path(sys.argv[1]))
print(sorted(name for name in sys.modules if name.startswith("whitebox")))
"""


@pytest.mark.allow_subprocess
def test_network_request_loads_no_whitebox(tmp_path: Path):
    completed = subprocess.run(
        [sys.executable, "-c", NO_WHITEBOX_SCRIPT, str(tmp_path / "out")],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    assert completed.stdout.strip().splitlines()[-1] == "[]"
    assert (tmp_path / "out" / "hydrography_acme-rivers.gpkg").is_file()


def test_period_is_a_closed_window():
    request = DataRequest.for_variable(
        "hydrometry", station_ids=["J0001"], start="2020-01-01", end="2020-12-31"
    )
    assert request.period.start == datetime(2020, 1, 1)
    with pytest.raises(ValueError, match="before it starts"):
        DataRequest.for_variable(
            "hydrometry", station_ids=["J0001"], start="2020-12-31", end="2020-01-01"
        )


def test_last_day_is_kept_whole(tmp_path: Path, isolated_registry):
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
    isolated_registry.register(hubeau_double([hourly]), replace=True)
    request = DataRequest.for_variable(
        "hydrometry", station_ids=["J0001"], start="2020-01-31", end="2020-01-31"
    )

    run_request(request, tmp_path / "out")

    entry = read_report(tmp_path / "out")["files"][0]
    table = pd.read_parquet(tmp_path / "out" / entry["path"])
    assert len(table) == 24
    assert entry["period"] == ["2020-01-31T00:00:00", "2020-01-31T23:00:00"]


class TwoSourceStore:
    """A store whose DEM comes back from two sources, the second one broken."""

    def __init__(self, good: Path):
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
                raster("file", self.good),
                raster("mirror", self.good),
                raster("mirror", self.good.with_name("absent.tif")),
            ]
        )


def test_failed_source_leaves_no_file(
    tmp_path: Path,
):
    dem = region_dem(tmp_path / "dem_file_region.tif")
    request = DataRequest.model_validate(
        {
            "data": {"dem": {"sources": [{"source": "file", "path": str(dem)}]}},
            "extent": {"bbox": BOX_2154, "crs": "EPSG:2154"},
        }
    )

    run_request(request, tmp_path / "out", store=TwoSourceStore(dem))

    document = read_report(tmp_path / "out")
    assert [(f["variable"], f["source"]) for f in document["failures"]] == [("dem", "mirror")]
    assert [f["path"] for f in document["files"]] == ["dem_file.tif"]
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [
        "dem_file.tif",
        "request.json",
    ]


def test_missing_mask_writes_nothing(tmp_path: Path):
    request = DataRequest.for_variable("dem", mask=tmp_path / "absent.gpkg")

    with pytest.raises(JobInputNotFoundError, match="absent.gpkg"):
        run_request(request, tmp_path / "out")
    assert not (tmp_path / "out").exists()


class CountedRivers(AcmeRivers):
    """The same network, counting the times it is asked."""

    calls: ClassVar[list[int]] = []

    def fetch(self, request):
        type(self).calls.append(1)
        return super().fetch(request)


def test_workspace_request_caches_the_network(tmp_path: Path, isolated_registry):
    CountedRivers.calls.clear()
    isolated_registry.register(CountedRivers)
    workspace = tmp_path / "ws"
    (workspace / "data").mkdir(parents=True)
    request = DataRequest.model_validate(
        {
            "data": {"hydrography": {"sources": [{"source": "acme-rivers"}]}},
            "extent": {"bbox": BOX_2154, "crs": "EPSG:2154"},
        }
    )

    run_request(request, tmp_path / "out1", store=DataStore(workspace_root=workspace))
    run_request(request, tmp_path / "out2", store=DataStore(workspace_root=workspace))

    cached = sorted(p.name for p in (workspace / "data" / "hydrography").glob("*.gpkg"))
    assert len(cached) == 1 and cached[0].startswith("hydrography_acme-rivers_")
    assert len(CountedRivers.calls) == 1
    assert (tmp_path / "out2" / "hydrography_acme-rivers.gpkg").is_file()


def test_caller_store_keeps_its_bounds(tmp_path, isolated_registry):
    isolated_registry.register(
        hubeau_double([station()], hosts=("villain.example.org",)), replace=True
    )
    request = DataRequest.for_variable(
        "hydrometry", station_ids=["J0001"], start="2019-12-01", end="2019-12-31"
    )
    store = DataStore(bounds=Bounds(allowed_hosts=frozenset()))

    report = run_request(request, tmp_path / "out", store=store).to_document()

    assert len(report["failures"]) == 1, report["files"]
    assert "villain.example.org" in str(report["failures"][0]["error"])
