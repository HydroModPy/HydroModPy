"""The IGN elevation models of France, assembled offline: elevation in m, boxes in Lambert-93 m.

BD ALTI (25 m) comes from department archives and RGE ALTI (1 m or 5 m) from WMS-Raster
tiles. Only the transport is canned. The samples under ``samples/rge_alti_wms/`` are
real answers of the Geoplateforme recorded on 2026-10-05: 40 x 40 pixels at 5 m over the
upper Ille (x 344000 to 344200, y 6806000 to 6806200), and 24 x 24 pixels at 5 m at the
Saint-Malo coast. They hold the -99999 nodata, the values blended next to it, the flat
-5 m water and some land.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import box

from hydromodpy.core.exceptions import DataCapabilityError, DataRequestError
from hydromodpy.data.source.port import Extent, FetchRequest, Period
from hydromodpy.data.variables.dem.apis import geoplateforme_wms as wms
from hydromodpy.data.variables.dem.apis import ign_dem_fr
from hydromodpy.data.variables.dem.apis._bdalti_archive_index import _request_hash_str
from hydromodpy.data.variables.dem.apis.geoplateforme_download import (
    AtomEntry,
    DownloadFile,
    GeoPlateformeDownloadError,
)
from hydromodpy.data.variables.dem.apis.ign_dem_fr import (
    GEOPLATEFORME_ORIGIN,
    RGE_ALTI_MAX_PIXELS,
    IgnGeoplateformeDem,
    _archive_extract_dir,
    _install_extracted_archive,
    _mask_sea,
    _normalize_dem_nodata,
    _processed_cache_is_usable,
    _processed_cache_request,
    _processed_metadata_path,
    _write_processed_cache_metadata,
    discover_ign_dem_files,
    download_ign_dem_departments,
    fetch_ign_dem,
    fetch_rge_alti,
    normalize_department_code,
)
from hydromodpy.data.variables.dem.config import IgnGeoplateformeDemSource
from hydromodpy.data.variables.dem.resolver import resolve_dem
from hydromodpy.data.variables.dem.variable import _resolution_for_ign_geoplateforme

pytestmark = pytest.mark.fast

SAMPLES = Path(__file__).resolve().parents[3] / "samples" / "rge_alti_wms"
BOX = (340000.0, 6800000.0, 350000.0, 6810000.0)
EXTENT = Extent(xmin=BOX[0], ymin=BOX[1], xmax=BOX[2], ymax=BOX[3], crs="EPSG:2154")
FOREIGN = Extent(xmin=-2.0, ymin=48.0, xmax=-1.5, ymax=48.4, crs="EPSG:4326")
FLUME = (344000.0, 6806000.0, 344200.0, 6806200.0)
COAST = (329235.0, 6850845.0, 329355.0, 6850965.0)
LAMBERT = "EPSG:2154"
NODATA = -9999


def one_pixel_dem(path: Path, *, nodata: float = -9999.0) -> Path:
    # A 5 m pixel at 17 m, as the assembler returns it.
    profile = {
        "driver": "GTiff",
        "height": 1,
        "width": 1,
        "count": 1,
        "dtype": "float32",
        "crs": LAMBERT,
        "transform": from_origin(BOX[0], BOX[3], 5.0, 5.0),
        "nodata": nodata,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.full((1, 1), 17.0, dtype="float32"), 1)
    return path


def small_dem(path: Path) -> None:
    # 2 x 2 pixels of 25 m at the corner (100, 100).
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs=LAMBERT,
        transform=from_origin(100.0, 150.0, 25.0, 25.0),
        nodata=NODATA,
    ) as dataset:
        dataset.write(np.array([[[1.0, 2.0], [3.0, 4.0]]], dtype="float32"))


def expected_box(extent: Extent) -> tuple[float, float, float, float]:
    # Reproject with pyproj directly, so the port is not its own reference.
    from pyproj import Transformer

    transformer = Transformer.from_crs(extent.crs, LAMBERT, always_xy=True)
    return tuple(transformer.transform_bounds(*extent.bbox))


@pytest.fixture
def offline_discovery(monkeypatch):
    def fail_discovery(*args, **kwargs):
        raise GeoPlateformeDownloadError("offline")

    monkeypatch.setattr(ign_dem_fr, "list_subresources", fail_discovery)


class Answer:
    status_code = 200

    def __init__(self, content: bytes) -> None:
        self.content = content


class Session:
    """Answers each GetMap with ``serve(bbox, width, height)`` and counts them."""

    def __init__(self, serve: Callable[[tuple, int, int], bytes]) -> None:
        self.serve = serve
        self.requests: list[dict] = []

    def request(self, method, url, params=None, **_kwargs):
        self.requests.append(dict(params))
        bbox = tuple(float(v) for v in params["BBOX"].split(","))
        return Answer(self.serve(bbox, int(params["WIDTH"]), int(params["HEIGHT"])))


def geotiff(array: np.ndarray, bbox: tuple, nodata: float = -99999.0) -> bytes:
    height, width = array.shape
    res = (bbox[2] - bbox[0]) / width
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            height=height,
            width=width,
            count=1,
            dtype="float32",
            crs=LAMBERT,
            transform=from_origin(bbox[0], bbox[3], res, res),
            nodata=nodata,
        ) as dst:
            dst.write(array.astype("float32"), 1)
        return memory.read()


def surface(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return 100.0 + 0.01 * (x - 344000.0) + 0.02 * (y - 6806000.0)


def synthetic_server(bbox: tuple, width: int, height: int) -> bytes:
    # A plane, sampled at the pixel centers of the requested grid.
    xs = bbox[0] + (np.arange(width) + 0.5) * (bbox[2] - bbox[0]) / width
    ys = bbox[3] - (np.arange(height) + 0.5) * (bbox[3] - bbox[1]) / height
    return geotiff(surface(*np.meshgrid(xs, ys)), bbox)


def recorded_server(name: str) -> Callable[[tuple, int, int], bytes]:
    payload = (SAMPLES / name).read_bytes()
    return lambda bbox, width, height: payload


def canvas_server(canvas: np.ndarray, origin: tuple[float, float]) -> Callable:
    # Serve crops of one 5 m array whose top-left corner is ``origin``.
    def serve(bbox: tuple, width: int, height: int) -> bytes:
        col = round((bbox[0] - origin[0]) / 5.0)
        row = round((origin[1] - bbox[3]) / 5.0)
        return geotiff(canvas[row : row + height, col : col + width], bbox)

    return serve


@pytest.fixture
def in_france(monkeypatch) -> None:
    # The department outlines stop short of the Saint-Malo shore. The box is not what is tested.
    monkeypatch.setattr(
        "hydromodpy.catchment.administrative.france.find_departments_in_bbox",
        lambda bbox: ["035"],
    )


DEPARTMENT_CODES = [
    pytest.param("29", "D029", id="metropolitan number"),
    pytest.param("D035", "D035", id="already prefixed"),
    pytest.param("971", "D971", id="overseas"),
    pytest.param("2A", "D02A", id="corsica"),
]


@pytest.mark.parametrize(("code", "expected"), DEPARTMENT_CODES)
def test_department_code(code, expected):
    assert normalize_department_code(code) == expected


def test_static_fallback_without_discovery(offline_discovery):
    files = discover_ign_dem_files(
        departments=["29"], dataset="bd-alti", resolution_m=25, file_format="ASC"
    )

    assert len(files) == 1
    assert files[0].department == "D029"
    assert "25M_ASC" in files[0].file_name
    assert files[0].url.endswith(f"/{files[0].file_name}")


def test_bd_alti_dry_run_layout(offline_discovery, tmp_path):
    paths = download_ign_dem_departments(
        output_dir=tmp_path, departments=["29"], dataset="bd-alti", resolution_m=25, dry_run=True
    )

    assert len(paths) == 1
    assert paths[0].parent == tmp_path / "bd-alti" / "25m" / "D029"


def test_rge_alti_dry_run_layout(monkeypatch, tmp_path):
    file_name = "RGEALTI_1M_ASC_LAMB93_D029.7z.001"
    monkeypatch.setattr(
        ign_dem_fr,
        "list_subresources",
        lambda *a, **k: [AtomEntry(title="RGEALTI_D029", identifier="RGEALTI_D029")],
    )
    monkeypatch.setattr(
        ign_dem_fr,
        "list_files",
        lambda *a, **k: [
            DownloadFile("RGEALTI", "RGEALTI_D029", file_name, f"https://example.test/{file_name}")
        ],
    )

    paths = download_ign_dem_departments(
        output_dir=tmp_path,
        departments=["29"],
        dataset="rge-alti",
        resolution_m=1,
        file_format="ASC",
        dry_run=True,
    )

    assert paths == [tmp_path / "rge-alti" / "1m" / "D029" / file_name]


def test_archive_extract_dir(tmp_path):
    archive = tmp_path / "raw/bd-alti/25m/D029/BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D029_2022-10-14.7z"

    extract_dir = _archive_extract_dir(tmp_path / "extracted_ign", archive)

    # A short name keyed on the department, stable for one archive.
    assert extract_dir.parent == tmp_path / "extracted_ign"
    assert extract_dir.name.startswith("D029_")
    assert len(extract_dir.name) < 16
    assert "BDALTIV2" not in extract_dir.name


def test_install_extracted_archive_makes_parents(tmp_path):
    archive = tmp_path / "raw" / "D029" / "BDALTIV2_2-0_25M_ASC_D029.7z"
    tmp_dir = tmp_path / "tmp"
    nested = tmp_dir / archive.stem / "BDALTIV2" / "1_DONNEES"
    nested.mkdir(parents=True)
    (nested / "tile.asc").write_text("ncols 1\n", encoding="utf-8")
    extract_dir = tmp_path / "missing" / "parents" / "D029_abcdef12"

    _install_extracted_archive(
        tmp_dir=tmp_dir, archive_path=archive, archive_extract_dir=extract_dir
    )

    assert (extract_dir / "tile.asc").is_file()


def test_ign_nodata_sentinels():
    data = np.array([[[-99999.0, -9999.0, -4.5, 123.0]]], dtype="float32")

    normalized = _normalize_dem_nodata(data.copy())

    assert normalized.dtype == np.dtype("float32")
    assert normalized.tolist() == [[[-9999.0, -9999.0, -4.5, 123.0]]]


def test_sea_mask():
    # The zero plateau touching the edge is sea. The inland zeros stay.
    data = np.array(
        [
            [
                [0.0, 0.0, 5.0, 5.0, 5.0],
                [0.0, 3.0, 5.0, 0.0, 5.0],
                [5.0, 5.0, 5.0, 5.0, 5.0],
                [5.0, 5.0, 0.0, 5.0, -9999.0],
                [5.0, 5.0, 5.0, 0.0, -9999.0],
            ]
        ],
        dtype="float32",
    )

    masked = _mask_sea(data.copy())[0]

    assert masked[0, 0] == masked[0, 1] == masked[1, 0] == -9999.0
    assert masked[1, 3] == 0.0
    assert masked[4, 3] == -9999.0
    assert masked[3, 2] == 0.0
    assert masked[1, 1] == 3.0


def test_bd_alti_from_archive(tmp_path, monkeypatch):
    archive = tmp_path / "raw_source" / "bd-alti" / "25m" / "D029" / "fixture.7z"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"fake archive")
    asc = "\n".join(
        [
            "ncols 3",
            "nrows 3",
            "xllcorner 100",
            "yllcorner 100",
            "cellsize 25",
            "NODATA_value -99999",
            "1 2 3",
            "4 -99999 6",
            "7 8 9",
        ]
    )

    def fake_extract_7z(archive_path, destination):
        asc_dir = Path(destination) / Path(archive_path).stem
        asc_dir.mkdir(parents=True)
        (asc_dir / "tile.asc").write_text(asc + "\n", encoding="ascii")

    monkeypatch.setattr(ign_dem_fr, "download_ign_dem_departments", lambda *a, **k: [archive])
    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis._bdalti_archive_index._extract_7z", fake_extract_7z
    )

    raster_path = fetch_ign_dem(
        output_dir=tmp_path,
        bbox=(100.0, 100.0, 175.0, 175.0),
        departments=["29"],
        dataset="bd-alti",
        resolution_m=25.0,
        file_format="ASC",
    )

    assert raster_path.name.startswith("dem_ign_geoplateforme_bdalti_25m_")
    assert (raster_path.parent.parent / "extracted_ign").is_dir()
    with rasterio.open(raster_path) as dataset:
        assert str(dataset.crs) == LAMBERT
        assert dataset.res == (25.0, 25.0)
        assert dataset.nodata == NODATA
        assert dataset.read(1)[1, 1] == NODATA
    metadata = json.loads(_processed_metadata_path(raster_path).read_text(encoding="utf-8"))
    assert metadata["request"]["departments"] == ["029"]
    assert metadata["request"]["dataset"] == "bd-alti"
    assert metadata["archives"][0]["path"].endswith("fixture.7z")


def test_bd_alti_processed_cache_is_reused(tmp_path, monkeypatch):
    bbox = (100.0, 100.0, 150.0, 150.0)
    bbox_hash = _request_hash_str(bbox, dept_codes=["029"])
    raster_path = tmp_path / "processed" / f"dem_ign_geoplateforme_bdalti_25m_{bbox_hash}.tif"
    raster_path.parent.mkdir()
    small_dem(raster_path)
    request = _processed_cache_request(
        bbox=bbox,
        departments=["029"],
        dataset="bd-alti",
        resolution_m=25.0,
        file_format="ASC",
        crs=None,
    )
    _write_processed_cache_metadata(
        _processed_metadata_path(raster_path),
        request=request,
        raster_path=raster_path,
        archive_paths=[],
    )

    def fail_download(*args, **kwargs):
        raise AssertionError("processed cache should be reused without download")

    monkeypatch.setattr(ign_dem_fr, "download_ign_dem_departments", fail_download)

    served = fetch_ign_dem(
        output_dir=tmp_path,
        bbox=bbox,
        departments=["029"],
        dataset="bd-alti",
        resolution_m=25.0,
    )

    assert served == raster_path


def test_processed_cache_refuses_other_metadata(tmp_path):
    raster_path = tmp_path / "processed.tif"
    small_dem(raster_path)
    metadata_path = _processed_metadata_path(raster_path)
    request = _processed_cache_request(
        bbox=(100.0, 100.0, 150.0, 150.0),
        departments=["029"],
        dataset="bd-alti",
        resolution_m=25.0,
        file_format="ASC",
        crs=None,
    )
    _write_processed_cache_metadata(
        metadata_path, request=request, raster_path=raster_path, archive_paths=[]
    )

    other_department = request | {"departments": ["035"]}

    assert _processed_cache_is_usable(raster_path, metadata_path=metadata_path, request=request)
    assert not _processed_cache_is_usable(
        raster_path, metadata_path=metadata_path, request=other_department
    )


def test_foreign_box_goes_in_lambert(tmp_path, monkeypatch):
    asked = {}

    def fake(*, output_dir, bbox, **kwargs):
        asked.update(bbox=bbox, **kwargs)
        return one_pixel_dem(Path(output_dir) / "dem.tif")

    monkeypatch.setattr(ign_dem_fr, "fetch_ign_dem", fake)

    result = IgnGeoplateformeDem(dataset="rge-alti").fetch(
        FetchRequest(out_dir=tmp_path, extent=FOREIGN)
    )

    np.testing.assert_allclose(asked["bbox"], expected_box(FOREIGN), rtol=0, atol=1e-6)
    assert result.extent is not None and result.extent.crs == LAMBERT


def test_file_record_carries_the_header_nodata(tmp_path, monkeypatch):
    seen = {}

    def fake(*, output_dir, bbox, **kwargs):
        seen.update(output_dir=output_dir, bbox=bbox)
        return one_pixel_dem(Path(output_dir) / "dem_25m.tif")

    monkeypatch.setattr(ign_dem_fr, "fetch_ign_dem", fake)

    result = IgnGeoplateformeDem().fetch(FetchRequest(out_dir=tmp_path, extent=EXTENT))

    [record] = result.files
    assert record.path == seen["output_dir"] / "dem_25m.tif"
    assert record.state == "raw"
    assert record.nodata == -9999.0
    assert record.origin == GEOPLATEFORME_ORIGIN
    assert record.sha256 == hashlib.sha256(record.path.read_bytes()).hexdigest()
    assert result.variables == ("dem",)


PERIOD = Period(start=datetime(2020, 1, 1), end=datetime(2020, 2, 1))

PORT_REFUSALS = [
    pytest.param({"station_ids": ("X1",)}, "does not select by", id="stations"),
    pytest.param({"extent": EXTENT, "period": PERIOD}, "no time axis", id="period"),
]


@pytest.mark.parametrize(("selectors", "match"), PORT_REFUSALS)
def test_port_refusals_come_before_the_assembler(tmp_path, monkeypatch, selectors, match):
    def fail(**_kwargs):
        raise AssertionError("the assembler was reached before the request was refused")

    monkeypatch.setattr(ign_dem_fr, "fetch_ign_dem", fail)

    with pytest.raises(DataCapabilityError, match=match):
        IgnGeoplateformeDem().fetch(FetchRequest(out_dir=tmp_path, **selectors))


def test_a_dataset_nobody_assembles_is_refused():
    with pytest.raises((ValueError, DataRequestError)):
        IgnGeoplateformeDem(dataset="srtm")


def test_tiles_assemble_one_raster(tmp_path):
    box_m = (344003.0, 6806001.0, 344403.0, 6806201.0)
    session = Session(synthetic_server)

    path = fetch_rge_alti(
        output_dir=tmp_path, bbox=box_m, resolution_m=5.0, tile_px=30, client=session
    )

    with rasterio.open(path) as raster:
        assert raster.bounds == (344000.0, 6806000.0, 344405.0, 6806205.0)
        assert raster.res == (5.0, 5.0) and raster.crs.to_epsg() == 2154
        assert raster.nodata == NODATA and raster.dtypes[0] == "float32"
        data = raster.read(1)
    assert data.shape == (41, 81) and len(session.requests) == 6
    xs = 344000.0 + (np.arange(81) + 0.5) * 5.0
    ys = 6806205.0 - (np.arange(41) + 0.5) * 5.0
    np.testing.assert_allclose(data, surface(*np.meshgrid(xs, ys)), atol=1e-3)
    assert path.name.startswith("dem_ign_geoplateforme_rgealti_5m_")


def test_cache_repeat_and_refresh(tmp_path):
    session = Session(synthetic_server)
    args = {"output_dir": tmp_path, "bbox": FLUME, "resolution_m": 5.0, "client": session}

    first = fetch_rge_alti(**args)
    fetched = len(session.requests)
    second = fetch_rge_alti(**args)
    assert second == first and len(session.requests) == fetched
    fetch_rge_alti(**args, force_refresh=True)
    assert len(session.requests) == 2 * fetched

    metadata = json.loads(first.with_suffix(".json").read_text(encoding="utf-8"))
    assert metadata["request"]["dataset"] == "rge-alti"
    assert metadata["request"]["resolution_m"] == 5.0
    assert metadata["wms"]["layer"] == "ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES"
    assert metadata["wms"]["tiles"] == fetched and metadata["archives"] == []


def test_default_resolution_is_5_m(tmp_path):
    path = fetch_ign_dem(
        output_dir=tmp_path, bbox=FLUME, dataset="rge-alti", client=Session(synthetic_server)
    )

    with rasterio.open(path) as raster:
        assert raster.res == (5.0, 5.0)


def test_water_is_nodata(tmp_path, in_france):
    session = Session(recorded_server("coast_5m_24px.tif"))
    with rasterio.open(SAMPLES / "coast_5m_24px.tif") as raw:
        server = raw.read(1)
    nodata = server <= -99990
    plateau = np.abs(server + 5.0) < 0.005
    blend = (server > -99990) & (server < -5.01)
    assert nodata.any() and plateau.any() and blend.any()

    path = fetch_rge_alti(output_dir=tmp_path, bbox=COAST, resolution_m=5.0, client=session)

    with rasterio.open(path) as raster:
        data = raster.read(1)
    masked = data == NODATA
    assert masked[nodata | plateau | blend].all()
    kept = ~masked
    assert kept.any() and np.array_equal(data[kept], server[kept])
    # The rim is the land 8-adjacent to the blend band and nothing else.
    rim = masked & ~(nodata | plateau | blend)
    near_blend = np.zeros_like(blend)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            near_blend |= np.roll(np.roll(blend, dr, axis=0), dc, axis=1)
    assert rim.any() and near_blend[rim].all()


def test_masking_ignores_tile_and_strip_edges(tmp_path, monkeypatch, in_france):
    with rasterio.open(SAMPLES / "coast_5m_24px.tif") as raw:
        sample = raw.read(1)

    def build(name: str, tile_px: int) -> np.ndarray:
        session = Session(canvas_server(sample, (COAST[0], COAST[3])))
        path = fetch_rge_alti(
            output_dir=tmp_path / name,
            bbox=COAST,
            resolution_m=5.0,
            tile_px=tile_px,
            client=session,
        )
        with rasterio.open(path) as raster:
            return raster.read(1)

    whole = build("whole", 24)
    monkeypatch.setattr(ign_dem_fr, "_STRIP_ROWS", 5)
    cut = build("cut", 7)

    assert (whole == NODATA).any() and np.array_equal(whole, cut)


def test_share_outside_france_warned(tmp_path, monkeypatch, caplog, in_france):
    border = ign_dem_fr.RGE_ALTI_BORDER_BUFFER_M
    monkeypatch.setattr(
        "hydromodpy.catchment.administrative.france.geometry_for_departments",
        lambda codes, **kwargs: box(0.0, 6.0e6, 344100.0 - border, 7.0e6),
    )
    session = Session(synthetic_server)

    with caplog.at_level("WARNING"):
        path = fetch_rge_alti(output_dir=tmp_path, bbox=FLUME, resolution_m=5.0, client=session)

    wms_block = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))["wms"]
    assert wms_block["valid_pixels"] == 40 * 40
    assert wms_block["outside_france_pixels"] == 20 * 40
    assert wms_block["outside_france_share"] == pytest.approx(0.5)
    assert wms_block["outside_france_buffer_m"] == 1000.0
    assert "outside the French department" in caplog.text
    with rasterio.open(path) as raster:
        assert not (raster.read(1) == NODATA).any()


def test_older_masking_rule_invalidates_the_cache(tmp_path):
    session = Session(synthetic_server)
    args = {"output_dir": tmp_path, "bbox": FLUME, "resolution_m": 5.0, "client": session}
    path = fetch_rge_alti(**args)
    sidecar = path.with_suffix(".json")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    assert metadata["request"]["processing_version"] == ign_dem_fr.RGE_ALTI_PROCESSING_VERSION
    fetched = len(session.requests)

    del metadata["request"]["processing_version"]
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    fetch_rge_alti(**args)

    assert len(session.requests) == 2 * fetched


def test_no_elevation_leaves_no_file(tmp_path):
    session = Session(lambda bbox, w, h: geotiff(np.full((h, w), -99999.0), bbox))

    with pytest.raises(ValueError, match="no elevation"):
        fetch_rge_alti(output_dir=tmp_path, bbox=FLUME, resolution_m=5.0, client=session)
    assert not list((tmp_path / "processed").glob("*.tif"))


# Refusals come before any request to the server.

BOX_30_KM = (340000.0, 6800000.0, 370000.0, 6830000.0)
BOX_60_KM = (320000.0, 6780000.0, 380000.0, 6840000.0)

FETCH_REFUSALS = [
    pytest.param(
        BOX_30_KM,
        {"resolution_m": 1.0},
        r"(?s)30000 x 30000 pixels \(900 million, 3.6 GB.*resolution_m = 5",
        id="30 km at 1 m",
    ),
    pytest.param(
        BOX_60_KM,
        {"resolution_m": 5.0, "max_pixels": 100_000_000},
        "above the limit",
        id="60 km under a small limit",
    ),
    pytest.param(FLUME, {"resolution_m": 0.5}, "1, 5 m only", id="resolution 0.5 m"),
    pytest.param(FLUME, {"resolution_m": 2.0}, "1, 5 m only", id="resolution 2 m"),
    pytest.param(FLUME, {"resolution_m": 10.0}, "1, 5 m only", id="resolution 10 m"),
    pytest.param(FLUME, {"resolution_m": 25.0}, "1, 5 m only", id="resolution 25 m"),
    pytest.param(
        (100000.0, 6800000.0, 100500.0, 6800500.0),
        {"resolution_m": 5.0},
        "No department found",
        id="no department",
    ),
]


@pytest.mark.parametrize(("bbox", "kwargs", "match"), FETCH_REFUSALS)
def test_fetch_refusals(tmp_path, bbox, kwargs, match):
    session = Session(synthetic_server)

    with pytest.raises(ValueError, match=match):
        fetch_rge_alti(output_dir=tmp_path, bbox=bbox, client=session, **kwargs)
    assert session.requests == []


def test_over_limit_at_5_m_advice(tmp_path):
    box_m = (300000.0, 6780000.0, 370000.0, 6850000.0)

    with pytest.raises(ValueError, match="above the limit") as info:
        fetch_rge_alti(
            output_dir=tmp_path, bbox=box_m, resolution_m=5.0, client=Session(synthetic_server)
        )
    assert "resolution_m" not in str(info.value)


def test_60_km_fits_default_limit():
    # An outlet off the 5 m grid snaps outward to one more pixel a side.
    snapped = wms.snap_bbox((320001.0, 6780001.0, 380001.0, 6840001.0), 5.0)

    assert wms.grid_shape(snapped, 5.0) == (12001, 12001)
    assert 12001 * 12001 <= RGE_ALTI_MAX_PIXELS


def project(resolution_m):
    source = IgnGeoplateformeDemSource(dataset="rge-alti", resolution_m=resolution_m)
    geographic = SimpleNamespace(x_outlet=344100.0, y_outlet=6806100.0)
    dem = SimpleNamespace(sources=[source])
    return SimpleNamespace(data=SimpleNamespace(dem=dem), geographic=geographic)


def test_project_refuses_1_m(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ign_dem_fr, "fetch_rge_alti", lambda **kw: calls.append(kw))

    with pytest.raises(ValueError, match="billions of pixels") as info:
        resolve_dem(project(1.0), data_dir=tmp_path)

    assert calls == []
    message = str(info.value)
    assert "hmp data get" in message and "resolution_m = 5" in message and "file source" in message
    assert "Reduce the extent" not in message


def test_project_passes_5_m(tmp_path, monkeypatch):
    calls = []

    def fake(**kw):
        # The real fetch returns the path of a raster it has written.
        calls.append(kw)
        return one_pixel_dem(tmp_path / "dem.tif")

    monkeypatch.setattr(ign_dem_fr, "fetch_rge_alti", fake)

    record = resolve_dem(project(5.0), data_dir=tmp_path)

    assert Path(record.path) == tmp_path / "dem.tif"
    assert calls[0]["resolution_m"] == 5.0
    assert calls[0]["bbox"] == (314100.0, 6776100.0, 374100.0, 6836100.0)


def test_rge_alti_default_resolution():
    source = IgnGeoplateformeDemSource(dataset="rge-alti")

    assert source.resolution_m is None
    assert _resolution_for_ign_geoplateforme(source) == 5.0
    assert IgnGeoplateformeDemSource(dataset="rge-alti", resolution_m=1.0).resolution_m == 1.0
    assert _resolution_for_ign_geoplateforme(IgnGeoplateformeDemSource()) == 25.0


DECLARATION_REFUSALS = [
    pytest.param({"dataset": "rge-alti", "resolution_m": 25.0}, id="rge 25 m"),
    pytest.param({"dataset": "rge-alti", "resolution_m": 2.0}, id="rge 2 m"),
    pytest.param({"dataset": "bd-alti", "resolution_m": 5.0}, id="bd alti 5 m"),
    pytest.param({"dataset": "rge-alti", "departments": ["35"]}, id="rge with departments"),
    pytest.param({"dataset": "rge-alti", "regions": ["Bretagne"]}, id="rge with regions"),
    pytest.param({"dataset": "rge-alti", "file_format": "TIF"}, id="rge with a file format"),
    pytest.param({"dataset": "rge-alti", "crs": "EPSG:4326"}, id="rge with a crs"),
]


@pytest.mark.parametrize("fields", DECLARATION_REFUSALS)
def test_declaration_refusals(fields):
    with pytest.raises(ValueError):
        IgnGeoplateformeDemSource(**fields)
