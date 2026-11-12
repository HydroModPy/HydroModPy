"""The two BRGM geology maps (1:1 000 000 and 1:50 000), on a stubbed provider.

The port classes return a file record over a crop box given in meters. The
builders turn a local archive into a Lambert-93 GeoPackage and crop it to a box.
The contract suite checks the port declarations on every source.
"""

from __future__ import annotations

import hashlib
import zipfile
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box

pyproj = pytest.importorskip("pyproj")

from hydromodpy.core.exceptions import DataCapabilityError, DataRequestError  # noqa: E402
from hydromodpy.data.source.port import Extent, FetchRequest, Period  # noqa: E402
from hydromodpy.data.variables.geology.apis import brgm_1m, brgm_50k  # noqa: E402
from hydromodpy.data.variables.geology.apis.brgm_1m import BRGM_1M_URL, Brgm1m  # noqa: E402
from hydromodpy.data.variables.geology.apis.brgm_50k import BRGM_50K_ORIGIN, Brgm50k  # noqa: E402
from hydromodpy.data.variables.geology.apis.fgeol import bbox_hash  # noqa: E402

BOX = (340000.0, 6800000.0, 350000.0, 6810000.0)
EXTENT = Extent(xmin=BOX[0], ymin=BOX[1], xmax=BOX[2], ymax=BOX[3], crs="EPSG:2154")
FOREIGN = Extent(xmin=-2.0, ymin=48.0, xmax=-1.5, ymax=48.4, crs="EPSG:4326")
PERIOD = Period(start=datetime(2020, 1, 1), end=datetime(2020, 2, 1))

CLASSES = [
    pytest.param(Brgm1m, brgm_1m, BRGM_1M_URL, id="brgm_1m"),
    pytest.param(Brgm50k, brgm_50k, BRGM_50K_ORIGIN, id="brgm_50k"),
]
# The pairs, for the cases that need no origin: a ParameterSet does not unpack.
PAIRS = [(Brgm1m, brgm_1m), (Brgm50k, brgm_50k)]


def _expected_box(extent: Extent) -> tuple[float, float, float, float]:
    """Reproject with pyproj directly, so the port is not its own reference."""
    transformer = pyproj.Transformer.from_crs(extent.crs, "EPSG:2154", always_xy=True)
    return tuple(transformer.transform_bounds(*extent.bbox))  # type: ignore[return-value]


def _gpkg(path: Path) -> Path:
    """A one-polygon Lambert-93 GeoPackage with the BRGM code column."""
    gpd.GeoDataFrame(
        {"CODE_LEG": ["G1"]}, geometry=[box(0.0, 0.0, 1.0, 1.0)], crs="EPSG:2154"
    ).to_file(path, driver="GPKG")
    return path


@pytest.mark.parametrize("cls, module, origin", CLASSES)
def test_a_crop_answers_a_file_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cls, module, origin
) -> None:
    asked: dict = {}
    fetch = getattr(module, f"fetch_{cls.source_id}")

    def fake(*, output_dir, bbox, code_field, **_kw):
        asked.update(bbox=bbox, code_field=code_field)
        return _gpkg(Path(output_dir) / f"{cls.source_id}.gpkg")

    monkeypatch.setattr(module, fetch.__name__, fake)

    result = cls().fetch(FetchRequest(out_dir=tmp_path, extent=EXTENT))

    [record] = result.files
    assert asked["bbox"] == BOX
    assert asked["code_field"] == "CODE_LEG"
    assert record.state == "raw"
    assert record.nodata is None
    assert record.origin == origin
    assert record.sha256 == hashlib.sha256(record.path.read_bytes()).hexdigest()
    assert result.variables == ("geology",)


@pytest.mark.parametrize("cls, module", PAIRS)
def test_a_foreign_box_reaches_the_provider_in_lambert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cls, module
) -> None:
    asked: dict = {}

    def fake(*, output_dir, bbox, code_field, **_kw):
        asked["bbox"] = bbox
        return _gpkg(Path(output_dir) / "map.gpkg")

    monkeypatch.setattr(module, f"fetch_{cls.source_id}", fake)

    result = cls().fetch(FetchRequest(out_dir=tmp_path, extent=FOREIGN))

    assert asked["bbox"] == pytest.approx(_expected_box(FOREIGN), rel=0, abs=1e-6)
    assert result.extent is not None and result.extent.crs == "EPSG:2154"


@pytest.mark.parametrize("cls", [Brgm1m, Brgm50k])
def test_refusals_come_before_the_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cls
) -> None:
    module = brgm_1m if cls is Brgm1m else brgm_50k

    def fail(**_kwargs):
        raise AssertionError("the provider was reached before the request was refused")

    monkeypatch.setattr(module, f"fetch_{cls.source_id}", fail)

    with pytest.raises(DataCapabilityError, match="does not select by"):
        cls().fetch(FetchRequest(out_dir=tmp_path, station_ids=("X1",)))
    with pytest.raises(DataCapabilityError, match="no time axis"):
        cls().fetch(FetchRequest(out_dir=tmp_path, extent=EXTENT, period=PERIOD))


def test_code_column_of_a_record(
    tmp_path: Path,
) -> None:
    # A record of a registered source reads CODE_LEG, a custom one its own column.
    from hydromodpy.data.variables.geology.field import _code_field

    record = type("R", (), {"source": "brgm_50k"})()
    config = type("C", (), {"sources": []})()
    assert _code_field(record, config) == "CODE_LEG"

    record.source = "file"
    config.sources = [type("S", (), {"source": "file", "code_field": "CODE_B"})()]
    assert _code_field(record, config) == "CODE_B"


def test_an_empty_crop_is_the_provider_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(*, output_dir, bbox, code_field, **_kw):
        raise ValueError("No geology feature from the 1M map intersects the requested bbox")

    monkeypatch.setattr(brgm_1m, "fetch_brgm_1m", fake)

    with pytest.raises(ValueError, match="intersects"):
        Brgm1m().fetch(FetchRequest(out_dir=tmp_path, extent=EXTENT))


def fgeol_gdf(crs="EPSG:2154"):
    """Two 1 km squares, 2 km apart, with codes a and b."""
    geoms = [box(1000, 1000, 2000, 2000), box(3000, 3000, 4000, 4000)]
    return gpd.GeoDataFrame({"CODE_LEG": ["a", "b"]}, geometry=geoms, crs="EPSG:2154").to_crs(crs)


def make_zip(path, tmp_path, *, name="X_S_FGEOL_2154", crs="EPSG:2154"):
    shp_dir = tmp_path / f"shp_{path.stem}"
    shp_dir.mkdir()
    fgeol_gdf(crs).to_file(shp_dir / f"{name}.shp")
    with zipfile.ZipFile(path, "w") as zf:
        for f in shp_dir.iterdir():
            zf.write(f, f.name)
    return path


def test_brgm_1m_builds_from_local_archive_and_crops(tmp_path):
    out = tmp_path / "cache"
    out.mkdir()
    make_zip(out / "FR_vecteur.zip", tmp_path, crs="EPSG:4326")

    full = brgm_1m.fetch_brgm_1m(output_dir=out)

    assert full.name == "geology_brgm_1m_france.gpkg"
    gdf = gpd.read_file(full)
    assert gdf.crs.to_epsg() == 2154
    assert len(gdf) == 2
    bbox = (900, 900, 1500, 1500)
    cropped = brgm_1m.fetch_brgm_1m(output_dir=out, bbox=bbox)
    assert cropped.name == f"geology_brgm_1m_{bbox_hash(bbox)}.gpkg"
    assert gpd.read_file(cropped)["CODE_LEG"].tolist() == ["a"]
    assert brgm_1m.fetch_brgm_1m(output_dir=out, bbox=bbox) == cropped  # served from the cache
    with pytest.raises(ValueError, match="intersects the requested bbox"):
        brgm_1m.fetch_brgm_1m(output_dir=out, bbox=(10, 10, 20, 20))


def test_brgm_1m_archive_without_fgeol_layer(tmp_path):
    zip_path = make_zip(tmp_path / "FR_vecteur.zip", tmp_path, name="OTHER_LAYER")

    with pytest.raises(FileNotFoundError, match="S_FGEOL_2154.shp"):
        brgm_1m._build_national_gpkg(zip_path, tmp_path / "out.gpkg")


def test_brgm_50k_department_from_local_archive(tmp_path):
    make_zip(tmp_path / "GEO050K_HARM_022.zip", tmp_path, crs="EPSG:4326")

    built = brgm_50k._download_department("22", cache_dir=tmp_path)

    assert built == tmp_path / "GEO050K_HARM_022" / "geology_50k_022.gpkg"
    assert gpd.read_file(built).crs.to_epsg() == 2154
    assert brgm_50k._download_department("22", cache_dir=tmp_path) == built


def test_brgm_50k_bad_archives_return_none(tmp_path):
    def build(zip_path, code):
        return brgm_50k._build_department_gpkg(
            "http://invalid.test/x.zip", zip_path, tmp_path / code, tmp_path / code / "d.gpkg", code
        )

    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    no_layer = make_zip(tmp_path / "nolayer.zip", tmp_path, name="OTHER")

    assert build(bad, "001") is None
    assert not bad.exists()
    assert build(no_layer, "002") is None


def test_brgm_50k_download_failure_returns_none(tmp_path, monkeypatch):
    def offline(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(brgm_50k, "download", offline)

    result = brgm_50k._build_department_gpkg(
        "http://invalid.test/x.zip",
        tmp_path / "z.zip",
        tmp_path / "d",
        tmp_path / "d" / "g.gpkg",
        "003",
    )

    assert result is None


def test_brgm_50k_merges_and_crops_cached_departments(tmp_path, monkeypatch):
    from hydromodpy.catchment.administrative import france

    monkeypatch.setattr(france, "find_departments_in_bbox", lambda bbox: ["022", "029"])
    dept_dir = tmp_path / "out" / "departments_50k"
    for code, shift_m in (("022", 0), ("029", 5000)):
        d = dept_dir / f"GEO050K_HARM_{code}"
        d.mkdir(parents=True)
        gdf = fgeol_gdf()
        gdf["geometry"] = gdf.translate(shift_m, 0)
        gdf["CODE_LEG"] = [f"{code}a", f"{code}b"]
        gdf.to_file(d / f"geology_50k_{code}.gpkg", driver="GPKG")
    bbox = (900, 900, 6000, 2500)

    merged = brgm_50k.fetch_brgm_50k(output_dir=tmp_path / "out", bbox=bbox)

    gdf = gpd.read_file(merged)
    assert sorted(gdf["CODE_LEG"]) == ["022a", "029a"]
    assert gdf.crs.to_epsg() == 2154
    assert brgm_50k.fetch_brgm_50k(output_dir=tmp_path / "out", bbox=bbox) == merged
    with pytest.raises(ValueError, match="No geology feature intersects"):
        brgm_50k.fetch_brgm_50k(output_dir=tmp_path / "out", bbox=(10, 10, 20, 20))


def test_brgm_50k_without_department(tmp_path, monkeypatch):
    from hydromodpy.catchment.administrative import france

    monkeypatch.setattr(france, "find_departments_in_bbox", lambda bbox: [])
    with pytest.raises(ValueError, match="No department found overlapping bbox"):
        brgm_50k.fetch_brgm_50k(output_dir=tmp_path, bbox=(0, 0, 1, 1))
    monkeypatch.setattr(france, "find_departments_in_bbox", lambda bbox: ["022"])
    monkeypatch.setattr(brgm_50k, "_download_department", lambda *a, **k: None)
    with pytest.raises(ValueError, match="No 50K geology data could be downloaded"):
        brgm_50k.fetch_brgm_50k(output_dir=tmp_path, bbox=(0, 0, 1, 1))
