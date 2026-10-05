"""The RGE ALTI is assembled from WMS-Raster tiles, offline.

The samples under ``samples/rge_alti_wms/`` are real answers of the Geoplateforme
recorded on 2026-10-05: 40 x 40 pixels at 5 m over the upper Ille (x 344000 to
344200, y 6806000 to 6806200), and 24 x 24 pixels at 5 m at the Saint-Malo coast,
which hold the -99999 nodata, the values blended next to it, the flat -5 m water
and some land. Only the transport is canned: the fake session answers a GeoTIFF
for whatever box it is asked. The inland quarry is synthetic: no recorded answer
holds land below -5 m next to no water.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from hydromodpy.data.variables.dem.apis import geoplateforme_wms as wms
from hydromodpy.data.variables.dem.apis import ign_dem_fr
from hydromodpy.data.variables.dem.apis.geoplateforme_download import (
    GeoPlateformeDownloadError,
)
from hydromodpy.data.variables.dem.apis.ign_dem_fr import (
    RGE_ALTI_MAX_PIXELS,
    fetch_ign_dem,
    fetch_rge_alti,
    mask_rge_alti,
)
from hydromodpy.data.variables.dem.config import IgnGeoplateformeDemSource
from hydromodpy.data.variables.dem.manager import _resolution_for_ign_geoplateforme
from hydromodpy.data.variables.dem.resolver import resolve_dem_path_from_data_sources

SAMPLES = Path(__file__).parent / "samples" / "rge_alti_wms"
FLUME = (344000.0, 6806000.0, 344200.0, 6806200.0)
COAST = (329235.0, 6850845.0, 329355.0, 6850965.0)

pytestmark = pytest.mark.fast


class _Answer:
    status_code = 200

    def __init__(self, content: bytes) -> None:
        self.content = content


class _Session:
    """Answers each GetMap with ``serve(bbox, width, height)`` and counts them."""

    def __init__(self, serve: Callable[[tuple, int, int], bytes]) -> None:
        self.serve = serve
        self.requests: list[dict] = []

    def get(self, url, params=None, **_kwargs):
        self.requests.append(dict(params))
        bbox = tuple(float(v) for v in params["BBOX"].split(","))
        return _Answer(self.serve(bbox, int(params["WIDTH"]), int(params["HEIGHT"])))


def _geotiff(array: np.ndarray, bbox: tuple, nodata: float = -99999.0) -> bytes:
    height, width = array.shape
    res = (bbox[2] - bbox[0]) / width
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            height=height,
            width=width,
            count=1,
            dtype="float32",
            crs="EPSG:2154",
            transform=from_origin(bbox[0], bbox[3], res, res),
            nodata=nodata,
        ) as dst:
            dst.write(array.astype("float32"), 1)
        return memory.read()


def _surface(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return 100.0 + 0.01 * (x - 344000.0) + 0.02 * (y - 6806000.0)


def _synthetic_server(bbox: tuple, width: int, height: int) -> bytes:
    """A plane, sampled at the pixel centres of the requested grid."""
    xs = bbox[0] + (np.arange(width) + 0.5) * (bbox[2] - bbox[0]) / width
    ys = bbox[3] - (np.arange(height) + 0.5) * (bbox[3] - bbox[1]) / height
    grid_x, grid_y = np.meshgrid(xs, ys)
    return _geotiff(_surface(grid_x, grid_y), bbox)


def _recorded_server(name: str) -> Callable[[tuple, int, int], bytes]:
    payload = (SAMPLES / name).read_bytes()
    return lambda bbox, width, height: payload


# --- the plan -----------------------------------------------------------------


def test_the_box_grows_outward_to_the_native_grid() -> None:
    assert wms.snap_bbox((344003.0, 6806001.0, 344203.0, 6806201.0), 5.0) == (
        344000.0,
        6806000.0,
        344205.0,
        6806205.0,
    )
    assert wms.snap_bbox(FLUME, 5.0) == FLUME


def test_the_tiles_cover_the_grid_once_and_stay_under_the_limit() -> None:
    box = (0.0, 0.0, 130.0, 70.0)
    tiles = list(wms.plan_tiles(box, 5.0, tile_px=10))

    assert wms.grid_shape(box, 5.0) == (14, 26)
    assert sum(t.width * t.height for t in tiles) == 14 * 26
    assert max(max(t.width, t.height) for t in tiles) == 10
    seen = np.zeros((14, 26), dtype=int)
    for tile in tiles:
        seen[
            tile.row_off : tile.row_off + tile.height, tile.col_off : tile.col_off + tile.width
        ] += 1
        assert tile.bbox[2] - tile.bbox[0] == tile.width * 5.0
        assert tile.bbox[3] - tile.bbox[1] == tile.height * 5.0
    assert (seen == 1).all()
    assert tiles[0].bbox[0] == 0.0 and tiles[0].bbox[3] == 70.0


def test_a_tile_wider_than_the_server_accepts_is_refused() -> None:
    with pytest.raises(ValueError, match="tile_px"):
        list(wms.plan_tiles(FLUME, 5.0, tile_px=wms.MAX_IMAGE_PX + 1))


# --- one tile -----------------------------------------------------------------


def test_a_recorded_tile_is_read_as_the_server_answered(tmp_path) -> None:
    tile = next(wms.plan_tiles(FLUME, 5.0))
    session = _Session(_recorded_server("flume_5m_40px.tif"))

    data = wms.fetch_tile("LAYER", tile, session=session)

    assert data.shape == (40, 40) and data.dtype == np.float32
    assert 110.0 < np.nanmin(data) < np.nanmax(data) < 116.0
    asked = session.requests[0]
    assert asked["CRS"] == "EPSG:2154" and asked["FORMAT"] == "image/geotiff"
    assert asked["BBOX"] == "344000.0,6806000.0,344200.0,6806200.0"
    assert (asked["WIDTH"], asked["HEIGHT"]) == (40, 40)


def test_an_xml_exception_answered_with_200_is_an_error() -> None:
    session = _Session(lambda *a: b'<?xml version="1.0"?><ServiceExceptionReport/>')

    with pytest.raises(GeoPlateformeDownloadError, match="did not answer a GeoTIFF"):
        wms.fetch_tile("LAYER", next(wms.plan_tiles(FLUME, 5.0)), session=session)


def test_a_grid_that_is_not_the_one_asked_is_an_error() -> None:
    session = _Session(lambda bbox, w, h: _geotiff(np.ones((h - 1, w)), bbox))

    with pytest.raises(GeoPlateformeDownloadError, match="pixels"):
        wms.fetch_tile("LAYER", next(wms.plan_tiles(FLUME, 5.0)), session=session)


def _truncated(payload: bytes, share: float) -> bytes:
    return payload[: int(len(payload) * share)]


def test_a_truncated_body_is_asked_again_once(tmp_path) -> None:
    good = _geotiff(np.full((40, 40), 111.0), FLUME)
    bodies = [_truncated(good, 0.5), good]
    session = _Session(lambda *a: bodies.pop(0))

    data = wms.fetch_tile("LAYER", next(wms.plan_tiles(FLUME, 5.0)), session=session)

    assert len(session.requests) == 2 and (data == 111.0).all()


def test_a_body_that_stays_truncated_is_a_download_error() -> None:
    good = _geotiff(np.full((40, 40), 111.0), FLUME)
    session = _Session(lambda *a: _truncated(good, 0.5))

    with pytest.raises(GeoPlateformeDownloadError, match="cannot be read"):
        wms.fetch_tile("LAYER", next(wms.plan_tiles(FLUME, 5.0)), session=session)
    assert len(session.requests) == 2


# --- the raster ---------------------------------------------------------------


def test_the_tiles_make_the_raster_the_server_would_draw_in_one_piece(tmp_path) -> None:
    box = (344003.0, 6806001.0, 344403.0, 6806201.0)
    session = _Session(_synthetic_server)

    path = fetch_rge_alti(
        output_dir=tmp_path, bbox=box, resolution_m=5.0, tile_px=30, session=session
    )

    with rasterio.open(path) as raster:
        assert raster.bounds == (344000.0, 6806000.0, 344405.0, 6806205.0)
        assert raster.res == (5.0, 5.0) and raster.crs.to_epsg() == 2154
        assert raster.nodata == -9999 and raster.dtypes[0] == "float32"
        data = raster.read(1)
    assert data.shape == (41, 81) and len(session.requests) == 6
    xs = 344000.0 + (np.arange(81) + 0.5) * 5.0
    ys = 6806205.0 - (np.arange(41) + 0.5) * 5.0
    expected = _surface(*np.meshgrid(xs, ys))
    assert np.allclose(data, expected, atol=1e-3)
    assert path.name.startswith("dem_ign_geoplateforme_rgealti_5m_")


def test_the_second_request_is_served_from_the_cache_and_a_refresh_is_not(tmp_path) -> None:
    session = _Session(_synthetic_server)
    args = {"output_dir": tmp_path, "bbox": FLUME, "resolution_m": 5.0, "session": session}

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


def test_the_resolution_is_part_of_the_cache_name(tmp_path) -> None:
    session = _Session(_synthetic_server)
    five = fetch_rge_alti(output_dir=tmp_path, bbox=FLUME, resolution_m=5.0, session=session)
    one = fetch_rge_alti(output_dir=tmp_path, bbox=FLUME, resolution_m=1.0, session=session)

    assert five != one and "_1m_" in one.name
    with rasterio.open(one) as raster:
        assert raster.shape == (200, 200)


def test_the_default_resolution_is_5_m(tmp_path) -> None:
    session = _Session(_synthetic_server)
    path = fetch_ign_dem(output_dir=tmp_path, bbox=FLUME, dataset="rge-alti", session=session)

    with rasterio.open(path) as raster:
        assert raster.res == (5.0, 5.0)


def _in_france(monkeypatch) -> None:
    # The department outlines stop short of this shore; the box is not what is tested.
    monkeypatch.setattr(
        "hydromodpy.spatial.administrative.france.find_departments_in_bbox",
        lambda bbox: ["035"],
    )


def test_water_and_the_nodata_blend_next_to_it_are_nodata(tmp_path, monkeypatch) -> None:
    _in_france(monkeypatch)
    session = _Session(_recorded_server("coast_5m_24px.tif"))
    with rasterio.open(SAMPLES / "coast_5m_24px.tif") as raw:
        server = raw.read(1)
    nodata = server <= -99990
    plateau = np.abs(server + 5.0) < 0.005
    blend = (server > -99990) & (server < -5.01)
    assert nodata.any() and plateau.any() and blend.any()

    path = fetch_rge_alti(output_dir=tmp_path, bbox=COAST, resolution_m=5.0, session=session)

    with rasterio.open(path) as raster:
        data = raster.read(1)
    masked = data == -9999
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


def _quarry(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Flat ground at 50 m with a 30 m deep pit, far from any water."""
    pit = (np.abs(x - 344100.0) < 25.0) & (np.abs(y - 6806100.0) < 25.0)
    return np.where(pit, 20.0 - 50.0, 50.0)


def _quarry_server(bbox: tuple, width: int, height: int) -> bytes:
    xs = bbox[0] + (np.arange(width) + 0.5) * (bbox[2] - bbox[0]) / width
    ys = bbox[3] - (np.arange(height) + 0.5) * (bbox[3] - bbox[1]) / height
    return _geotiff(_quarry(*np.meshgrid(xs, ys)), bbox)


def test_land_below_minus_5_m_far_from_water_is_kept(tmp_path) -> None:
    session = _Session(_quarry_server)

    path = fetch_rge_alti(output_dir=tmp_path, bbox=FLUME, resolution_m=5.0, session=session)

    with rasterio.open(path) as raster:
        data = raster.read(1)
    assert (data == -30.0).sum() == 10 * 10
    assert (data == -9999).sum() == 0


def test_the_mask_follows_the_water_not_a_depth() -> None:
    field = np.full((30, 30), 50.0, dtype="float32")
    field[5:9, 5:9] = -30.0  # a pit
    field[20:25, 20:25] = -5.0  # water
    field[19, 20:25] = -400.0  # blend next to it
    field[18, 20:25] = -4.99  # land next to the blend

    masked = mask_rge_alti(field)

    assert (masked[5:9, 5:9] == -30.0).all()
    assert np.isnan(masked[20:25, 20:25]).all()
    assert np.isnan(masked[19, 20:25]).all() and np.isnan(masked[18, 20:25]).all()
    assert (masked[17, 21:24] == 50.0).all()


def _canvas_server(canvas: np.ndarray, origin: tuple[float, float]) -> Callable:
    """Serve crops of one 5 m array whose top-left corner is ``origin``."""

    def serve(bbox: tuple, width: int, height: int) -> bytes:
        col = round((bbox[0] - origin[0]) / 5.0)
        row = round((origin[1] - bbox[3]) / 5.0)
        return _geotiff(canvas[row : row + height, col : col + width], bbox)

    return serve


def test_the_rule_does_not_see_tile_or_strip_edges(tmp_path, monkeypatch) -> None:
    _in_france(monkeypatch)
    with rasterio.open(SAMPLES / "coast_5m_24px.tif") as raw:
        sample = raw.read(1)

    def build(name: str, tile_px: int) -> np.ndarray:
        session = _Session(_canvas_server(sample, (COAST[0], COAST[3])))
        path = fetch_rge_alti(
            output_dir=tmp_path / name,
            bbox=COAST,
            resolution_m=5.0,
            tile_px=tile_px,
            session=session,
        )
        with rasterio.open(path) as raster:
            return raster.read(1)

    whole = build("whole", 24)
    monkeypatch.setattr(ign_dem_fr, "_STRIP_ROWS", 5)
    cut = build("cut", 7)

    assert (whole == -9999).any() and np.array_equal(whole, cut)


def test_the_outside_france_share_is_counted_and_warned(tmp_path, monkeypatch, caplog) -> None:
    from shapely.geometry import box

    _in_france(monkeypatch)
    monkeypatch.setattr(
        "hydromodpy.spatial.administrative.france.geometry_for_departments",
        lambda codes, **kwargs: box(
            0.0, 6.0e6, 344100.0 - ign_dem_fr.RGE_ALTI_BORDER_BUFFER_M, 7.0e6
        ),
    )
    session = _Session(_synthetic_server)

    with caplog.at_level("WARNING"):
        path = fetch_rge_alti(output_dir=tmp_path, bbox=FLUME, resolution_m=5.0, session=session)

    wms_block = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))["wms"]
    assert wms_block["valid_pixels"] == 40 * 40
    assert wms_block["outside_france_pixels"] == 20 * 40
    assert wms_block["outside_france_share"] == pytest.approx(0.5)
    assert wms_block["outside_france_buffer_m"] == 1000.0
    assert "outside the French department" in caplog.text
    with rasterio.open(path) as raster:
        assert not (raster.read(1) == -9999).any()


def test_a_box_inside_france_has_no_outside_pixels(tmp_path) -> None:
    session = _Session(_synthetic_server)

    path = fetch_rge_alti(output_dir=tmp_path, bbox=FLUME, resolution_m=5.0, session=session)

    wms_block = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))["wms"]
    assert wms_block["outside_france_pixels"] == 0


def test_a_raster_cached_with_an_older_masking_rule_is_not_reused(tmp_path) -> None:
    session = _Session(_synthetic_server)
    args = {"output_dir": tmp_path, "bbox": FLUME, "resolution_m": 5.0, "session": session}
    path = fetch_rge_alti(**args)
    sidecar = path.with_suffix(".json")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    assert metadata["request"]["processing_version"] == ign_dem_fr.RGE_ALTI_PROCESSING_VERSION
    fetched = len(session.requests)

    del metadata["request"]["processing_version"]
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    fetch_rge_alti(**args)

    assert len(session.requests) == 2 * fetched


def test_a_box_with_no_elevation_is_an_error_and_leaves_no_file(tmp_path) -> None:
    session = _Session(lambda bbox, w, h: _geotiff(np.full((h, w), -99999.0), bbox))

    with pytest.raises(ValueError, match="no elevation"):
        fetch_rge_alti(output_dir=tmp_path, bbox=FLUME, resolution_m=5.0, session=session)
    assert not list((tmp_path / "processed").glob("*.tif"))


# --- the refusals ---------------------------------------------------------------


def test_a_1_m_box_of_30_km_is_refused_before_any_request(tmp_path) -> None:
    session = _Session(_synthetic_server)
    box = (340000.0, 6800000.0, 370000.0, 6830000.0)

    with pytest.raises(ValueError, match=r"30000 x 30000 pixels \(900 million, 3.6 GB") as info:
        fetch_rge_alti(output_dir=tmp_path, bbox=box, resolution_m=1.0, session=session)
    assert session.requests == []
    assert "resolution_m = 5" in str(info.value)


def test_a_5_m_box_over_the_limit_is_not_told_to_use_5_m(tmp_path) -> None:
    session = _Session(_synthetic_server)
    box = (300000.0, 6780000.0, 370000.0, 6850000.0)

    with pytest.raises(ValueError, match="above the limit") as info:
        fetch_rge_alti(output_dir=tmp_path, bbox=box, resolution_m=5.0, session=session)
    assert "resolution_m" not in str(info.value)


def _project(resolution_m, **fields):
    from types import SimpleNamespace

    source = IgnGeoplateformeDemSource(dataset="rge-alti", resolution_m=resolution_m, **fields)
    geographic = SimpleNamespace(x_outlet=344100.0, y_outlet=6806100.0)
    cfg = SimpleNamespace(
        data=SimpleNamespace(dem=SimpleNamespace(sources=[source])), geographic=geographic
    )
    return cfg


def test_the_project_path_refuses_1_m_before_any_request(tmp_path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(ign_dem_fr, "fetch_rge_alti", lambda **kw: calls.append(kw))

    with pytest.raises(ValueError, match="billions of pixels") as info:
        resolve_dem_path_from_data_sources(
            _project(1.0), config_path=tmp_path / "run.toml", cache_dir=tmp_path
        )

    assert calls == []
    message = str(info.value)
    assert (
        "hmp data get" in message and "resolution_m = 5" in message and "dem_init_path" in message
    )
    assert "Reduce the extent" not in message


def test_the_project_path_passes_5_m_to_the_fetch(tmp_path, monkeypatch) -> None:
    calls = []

    def fake(**kw):
        calls.append(kw)
        return tmp_path / "dem.tif"

    monkeypatch.setattr(ign_dem_fr, "fetch_rge_alti", fake)

    path = resolve_dem_path_from_data_sources(
        _project(5.0), config_path=tmp_path / "run.toml", cache_dir=tmp_path
    )

    assert path == tmp_path / "dem.tif"
    assert calls[0]["resolution_m"] == 5.0
    assert calls[0]["bbox"] == (314100.0, 6776100.0, 374100.0, 6836100.0)


def test_the_60_km_bootstrap_box_is_inside_the_default_limit_at_5_m(tmp_path) -> None:
    session = _Session(_synthetic_server)
    box = (320000.0, 6780000.0, 380000.0, 6840000.0)

    with pytest.raises(ValueError, match="above the limit"):
        fetch_rge_alti(
            output_dir=tmp_path, bbox=box, resolution_m=5.0, max_pixels=100_000_000, session=session
        )
    assert session.requests == []
    # An outlet off the 5 m grid snaps outward to one more pixel a side.
    assert wms.grid_shape(wms.snap_bbox((320001.0, 6780001.0, 380001.0, 6840001.0), 5.0), 5.0) == (
        12001,
        12001,
    )
    assert 12001 * 12001 <= RGE_ALTI_MAX_PIXELS


@pytest.mark.parametrize("resolution", [0.5, 2.0, 10.0, 25.0])
def test_a_resolution_the_server_would_resample_is_refused(tmp_path, resolution) -> None:
    session = _Session(_synthetic_server)

    with pytest.raises(ValueError, match="1, 5 m only"):
        fetch_rge_alti(output_dir=tmp_path, bbox=FLUME, resolution_m=resolution, session=session)
    assert session.requests == []


def test_a_box_that_touches_no_department_is_refused(tmp_path) -> None:
    session = _Session(_synthetic_server)

    with pytest.raises(ValueError, match="No department found"):
        fetch_rge_alti(
            output_dir=tmp_path,
            bbox=(100000.0, 6800000.0, 100500.0, 6800500.0),
            resolution_m=5.0,
            session=session,
        )
    assert session.requests == []


# --- the declaration --------------------------------------------------------------


def test_the_provider_declares_rge_alti_with_5_m_as_default() -> None:
    source = IgnGeoplateformeDemSource(dataset="rge-alti")

    assert source.resolution_m is None
    assert _resolution_for_ign_geoplateforme(source) == 5.0
    assert IgnGeoplateformeDemSource(dataset="rge-alti", resolution_m=1.0).resolution_m == 1.0
    assert _resolution_for_ign_geoplateforme(IgnGeoplateformeDemSource()) == 25.0


@pytest.mark.parametrize(
    "fields",
    [
        {"dataset": "rge-alti", "resolution_m": 25.0},
        {"dataset": "rge-alti", "resolution_m": 2.0},
        {"dataset": "bd-alti", "resolution_m": 5.0},
        {"dataset": "rge-alti", "departments": ["35"]},
        {"dataset": "rge-alti", "regions": ["Bretagne"]},
        {"dataset": "rge-alti", "file_format": "TIF"},
        {"dataset": "rge-alti", "crs": "EPSG:4326"},
    ],
)
def test_the_declaration_refuses_what_the_product_does_not_serve(fields) -> None:
    with pytest.raises(ValueError):
        IgnGeoplateformeDemSource(**fields)


def test_a_dumped_declaration_loads_back() -> None:
    source = IgnGeoplateformeDemSource(dataset="rge-alti", resolution_m=5.0)

    assert IgnGeoplateformeDemSource(**source.model_dump()) == source
