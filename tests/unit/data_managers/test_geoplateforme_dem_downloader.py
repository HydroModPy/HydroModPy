from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.data.variables.dem.apis.geoplateforme_download import (
    DownloadFile,
    GeoPlateformeDownloadError,
    download_file,
    fetch_atom_entries,
    list_files,
    parse_atom_entries,
)
from hydromodpy.data.variables.dem.apis.ign_dem_fr import (
    discover_ign_dem_files,
    download_ign_dem_departments,
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
