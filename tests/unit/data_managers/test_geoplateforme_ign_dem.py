from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.data.variables.dem.apis._bdalti_archive_index import _request_hash_str
from hydromodpy.data.variables.dem.apis.geoplateforme_download import (
    DownloadFile,
    GeoPlateformeDownloadError,
)
from hydromodpy.data.variables.dem.apis.ign_dem_fr import (
    _archive_extract_dir,
    _install_extracted_archive,
    _normalize_dem_nodata,
    _processed_cache_is_usable,
    _processed_cache_request,
    _processed_metadata_path,
    _write_processed_cache_metadata,
    discover_ign_dem_files,
    download_ign_dem_departments,
    fetch_ign_dem,
    normalize_department_code,
)


@pytest.mark.fast
def test_normalize_department_code_for_geoplateforme():
    assert normalize_department_code("29") == "D029"
    assert normalize_department_code("D035") == "D035"
    assert normalize_department_code("971") == "D971"
    assert normalize_department_code("2A") == "D02A"


@pytest.mark.fast
def test_bd_alti_static_fallback_when_discovery_is_unavailable(monkeypatch):
    def fail_discovery(*args, **kwargs):
        raise GeoPlateformeDownloadError("offline")

    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis.ign_dem_fr.list_subresources",
        fail_discovery,
    )

    files = discover_ign_dem_files(
        departments=["29"],
        dataset="bd-alti",
        resolution_m=25,
        file_format="ASC",
    )

    assert len(files) == 1
    assert files[0].department == "D029"
    assert "25M_ASC" in files[0].file_name
    assert files[0].url.endswith(f"/{files[0].file_name}")


@pytest.mark.fast
def test_download_ign_dem_departments_dry_run_uses_cache_layout(monkeypatch, tmp_path):
    def fail_discovery(*args, **kwargs):
        raise GeoPlateformeDownloadError("offline")

    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis.ign_dem_fr.list_subresources",
        fail_discovery,
    )

    paths = download_ign_dem_departments(
        output_dir=tmp_path,
        departments=["29"],
        dataset="bd-alti",
        resolution_m=25,
        dry_run=True,
    )

    assert len(paths) == 1
    assert paths[0].parent == tmp_path / "bd-alti" / "25m" / "D029"


@pytest.mark.fast
def test_rge_alti_raw_discovery_download_layout_is_available(monkeypatch, tmp_path):
    def fake_subresources(*args, **kwargs):
        from hydromodpy.data.variables.dem.apis.geoplateforme_download import AtomEntry

        return [AtomEntry(title="RGEALTI_D029", identifier="RGEALTI_D029")]

    def fake_files(*args, **kwargs):
        return [
            DownloadFile(
                "RGEALTI",
                "RGEALTI_D029",
                "RGEALTI_1M_ASC_LAMB93_D029.7z.001",
                "https://example.test/RGEALTI_1M_ASC_LAMB93_D029.7z.001",
            )
        ]

    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis.ign_dem_fr.list_subresources",
        fake_subresources,
    )
    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis.ign_dem_fr.list_files",
        fake_files,
    )

    paths = download_ign_dem_departments(
        output_dir=tmp_path,
        departments=["29"],
        dataset="rge-alti",
        resolution_m=1,
        file_format="ASC",
        dry_run=True,
    )

    assert paths == [tmp_path / "rge-alti" / "1m" / "D029" / "RGEALTI_1M_ASC_LAMB93_D029.7z.001"]


@pytest.mark.fast
def test_archive_extract_dir_uses_short_stable_department_path(tmp_path):
    archive = (
        tmp_path
        / "raw"
        / "bd-alti"
        / "25m"
        / "D029"
        / "BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D029_2022-10-14.7z"
    )

    extract_dir = _archive_extract_dir(tmp_path / "extracted_ign", archive)

    assert extract_dir.parent == tmp_path / "extracted_ign"
    assert extract_dir.name.startswith("D029_")
    assert len(extract_dir.name) < 16
    assert "BDALTIV2" not in extract_dir.name


@pytest.mark.fast
def test_install_extracted_archive_creates_parent_directory(tmp_path):
    archive = tmp_path / "raw" / "D029" / "BDALTIV2_2-0_25M_ASC_D029.7z"
    tmp_dir = tmp_path / "tmp"
    archive_root = tmp_dir / archive.stem
    nested = archive_root / "BDALTIV2" / "1_DONNEES"
    nested.mkdir(parents=True)
    (nested / "tile.asc").write_text("ncols 1\n", encoding="utf-8")
    extract_dir = tmp_path / "missing" / "parents" / "D029_abcdef12"

    _install_extracted_archive(
        tmp_dir=tmp_dir,
        archive_path=archive,
        archive_extract_dir=extract_dir,
    )

    assert (extract_dir / "tile.asc").is_file()


@pytest.mark.fast
def test_normalize_dem_nodata_converts_ign_sentinel_values():
    data = np.array([[[-99999.0, -9999.0, -4.5, 123.0]]], dtype="float32")

    normalized = _normalize_dem_nodata(data.copy())

    assert normalized.dtype == np.dtype("float32")
    assert normalized.tolist() == [[[-9999.0, -9999.0, -4.5, 123.0]]]


@pytest.mark.fast
def test_fetch_ign_dem_raster_assembly_rejects_rge_alti_until_supported(tmp_path):
    with pytest.raises(NotImplementedError, match="RGE ALTI raster assembly"):
        fetch_ign_dem(
            output_dir=tmp_path,
            bbox=(0.0, 0.0, 1.0, 1.0),
            departments=["29"],
            dataset="rge-alti",
            resolution_m=5.0,
        )


@pytest.mark.fast
def test_fetch_ign_dem_assembles_small_asc_fixture(tmp_path, monkeypatch):
    rasterio = pytest.importorskip("rasterio")

    archive = tmp_path / "raw_source" / "bd-alti" / "25m" / "D029" / "fixture.7z"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"fake archive")

    def fake_download(*args, **kwargs):
        return [archive]

    def fake_extract_7z(archive_path, destination):
        asc_dir = Path(destination) / Path(archive_path).stem
        asc_dir.mkdir(parents=True)
        (asc_dir / "tile.asc").write_text(
            "\n".join(
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
            + "\n",
            encoding="ascii",
        )

    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis.ign_dem_fr.download_ign_dem_departments",
        fake_download,
    )
    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis._bdalti_archive_index._extract_7z",
        fake_extract_7z,
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
        assert str(dataset.crs) == "EPSG:2154"
        assert dataset.res == (25.0, 25.0)
        assert dataset.nodata == -9999
        assert dataset.read(1)[1, 1] == -9999

    metadata = json.loads(_processed_metadata_path(raster_path).read_text(encoding="utf-8"))
    assert metadata["request"]["departments"] == ["029"]
    assert metadata["request"]["dataset"] == "bd-alti"
    assert metadata["archives"][0]["path"].endswith("fixture.7z")


@pytest.mark.fast
def test_fetch_ign_dem_reuses_valid_processed_cache(tmp_path, monkeypatch):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    bbox = (100.0, 100.0, 150.0, 150.0)
    dept_codes = ["029"]
    bbox_hash = _request_hash_str(bbox, dept_codes=dept_codes)
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    raster_path = processed_dir / f"dem_ign_geoplateforme_bdalti_25m_{bbox_hash}.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=from_origin(100.0, 150.0, 25.0, 25.0),
        nodata=-9999,
    ) as dataset:
        dataset.write(np.array([[[1.0, 2.0], [3.0, 4.0]]], dtype="float32"))

    request = _processed_cache_request(
        bbox=bbox,
        departments=dept_codes,
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

    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis.ign_dem_fr.download_ign_dem_departments",
        fail_download,
    )

    assert (
        fetch_ign_dem(
            output_dir=tmp_path,
            bbox=bbox,
            departments=dept_codes,
            dataset="bd-alti",
            resolution_m=25.0,
        )
        == raster_path
    )


@pytest.mark.fast
def test_processed_cache_rejects_mismatched_metadata(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    raster_path = tmp_path / "processed.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=from_origin(100.0, 150.0, 25.0, 25.0),
        nodata=-9999,
    ) as dataset:
        dataset.write(np.array([[[1.0, 2.0], [3.0, 4.0]]], dtype="float32"))

    metadata_path = _processed_metadata_path(raster_path)
    original_request = _processed_cache_request(
        bbox=(100.0, 100.0, 150.0, 150.0),
        departments=["029"],
        dataset="bd-alti",
        resolution_m=25.0,
        file_format="ASC",
        crs=None,
    )
    _write_processed_cache_metadata(
        metadata_path,
        request=original_request,
        raster_path=raster_path,
        archive_paths=[],
    )
    incompatible_request = {
        **original_request,
        "departments": ["035"],
    }

    assert not _processed_cache_is_usable(
        raster_path,
        metadata_path=metadata_path,
        request=incompatible_request,
    )
