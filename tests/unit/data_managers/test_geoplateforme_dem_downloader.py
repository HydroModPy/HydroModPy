from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.data.variables.dem.apis.geoplateforme_download import (
    DownloadFile,
    GeoPlateformeDownloadError,
    download_file,
    fetch_atom_entries,
    list_files,
    parse_atom_entries,
)
from hydromodpy.data.variables.dem.apis.ign_bdalti import _request_hash_str
from hydromodpy.data.variables.dem.apis.ign_dem_fr import (
    _archive_extract_dir,
    _install_extracted_archive,
    _normalize_dem_nodata,
    _processed_cache_request,
    _processed_metadata_path,
    _write_processed_cache_metadata,
    discover_ign_dem_files,
    download_ign_dem_departments,
    fetch_ign_dem,
    normalize_department_code,
)

ATOM_PAGE_1 = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:gpf_dl="http://data.geopf.fr">
  <gpf_dl:totalentries>2</gpf_dl:totalentries>
  <entry>
    <title>BDALTI resource</title>
    <id>BDALTI</id>
    <link href="https://data.geopf.fr/telechargement/resource/BDALTI" />
  </entry>
</feed>
"""

ATOM_PAGE_2 = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:gpf_dl="http://data.geopf.fr">
  <gpf_dl:totalentries>2</gpf_dl:totalentries>
  <entry>
    <title>RGEALTI resource</title>
    <id>RGEALTI</id>
    <link href="https://data.geopf.fr/telechargement/resource/RGEALTI" />
  </entry>
</feed>
"""

ATOM_FILES = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:gpf_dl="http://data.geopf.fr">
  <gpf_dl:totalentries>1</gpf_dl:totalentries>
  <entry>
    <title>BDALTIV2_2-0_25M_ASC_LAMB93-IGN69_D029_2022-10-14.7z</title>
    <id>file-1</id>
    <gpf_dl:size>123</gpf_dl:size>
    <gpf_dl:md5>abc</gpf_dl:md5>
    <link href="https://data.geopf.fr/telechargement/download/BDALTI/sub/file.7z" />
  </entry>
</feed>
"""


class FakeResponse:
    def __init__(self, text: str = "", content: bytes = b"", status_code: int = 200):
        self.text = text
        self._content = content
        self.status_code = status_code

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield self._content


class FakeSession:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError("No fake response left.")
        return self.responses.pop(0)


@pytest.mark.fast
def test_normalize_department_code_for_geoplateforme():
    assert normalize_department_code("29") == "D029"
    assert normalize_department_code("D035") == "D035"
    assert normalize_department_code("971") == "D971"
    assert normalize_department_code("2A") == "D02A"


@pytest.mark.fast
def test_parse_atom_entries_extracts_links_and_properties():
    entries = parse_atom_entries(ATOM_FILES)

    assert len(entries) == 1
    assert entries[0].title.endswith(".7z")
    assert entries[0].properties["size"] == "123"
    assert entries[0].properties["md5"] == "abc"
    assert entries[0].links == (
        "https://data.geopf.fr/telechargement/download/BDALTI/sub/file.7z",
    )


@pytest.mark.fast
def test_fetch_atom_entries_follows_pagination():
    session = FakeSession([FakeResponse(ATOM_PAGE_1), FakeResponse(ATOM_PAGE_2)])

    entries = fetch_atom_entries(
        "https://example.test/feed",
        {"limit": 1},
        session=session,  # type: ignore[arg-type]
    )

    assert [entry.identifier for entry in entries] == ["BDALTI", "RGEALTI"]
    assert [call["params"]["page"] for call in session.calls] == [1, 2]


@pytest.mark.fast
def test_list_files_converts_atom_entries_to_download_files():
    session = FakeSession([FakeResponse(ATOM_FILES)])

    files = list_files(
        "BDALTI",
        "sub",
        session=session,  # type: ignore[arg-type]
    )

    assert files == [
        DownloadFile(
            resource_name="BDALTI",
            subresource_name="sub",
            file_name="file.7z",
            url="https://data.geopf.fr/telechargement/download/BDALTI/sub/file.7z",
            size=123,
            checksum="abc",
        )
    ]


@pytest.mark.fast
def test_download_file_reuses_existing_non_empty_file(tmp_path):
    target = tmp_path / "archive.7z"
    target.write_bytes(b"cached")
    session = FakeSession([])

    path = download_file(
        DownloadFile("BDALTI", "sub", "archive.7z", "https://example.test/archive.7z"),
        tmp_path,
        session=session,  # type: ignore[arg-type]
    )

    assert path == target
    assert target.read_bytes() == b"cached"
    assert session.calls == []


@pytest.mark.fast
def test_download_file_writes_part_then_final(tmp_path):
    session = FakeSession([FakeResponse(content=b"payload")])

    path = download_file(
        DownloadFile("BDALTI", "sub", "archive.7z", "https://example.test/archive.7z"),
        tmp_path,
        session=session,  # type: ignore[arg-type]
    )

    assert path == tmp_path / "archive.7z"
    assert path.read_bytes() == b"payload"
    assert not Path(f"{path}.part").exists()


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

    assert (extract_dir / "BDALTIV2" / "1_DONNEES" / "tile.asc").is_file()


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
        "hydromodpy.data.variables.dem.apis.ign_bdalti._extract_7z",
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
