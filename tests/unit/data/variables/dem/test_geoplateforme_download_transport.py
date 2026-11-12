from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.data.variables.dem.apis.geoplateforme_download import (
    DownloadFile,
    GeoPlateformeDownloadError,
    download_file,
    fetch_atom_entries,
    list_files,
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

ATOM_SINGLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:gpf_dl="http://data.geopf.fr">
  <gpf_dl:totalentries>1</gpf_dl:totalentries>
  <entry>
    <title>BDALTI resource</title>
    <id>BDALTI</id>
    <link href="https://data.geopf.fr/telechargement/resource/BDALTI" />
  </entry>
</feed>
"""


class FakeResponse:
    def __init__(self, text: str = "", content: bytes = b"", status_code: int = 200):
        self.text = text
        self._content = content
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield self._content

    def close(self) -> None:
        pass


class FakeClient:
    """Stands for the HTTP client of ``core/io/fetch``: answers GETs in order, HEADs with 200."""

    def __init__(self, responses: list[FakeResponse]):
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs):
        if method == "HEAD":
            return FakeResponse()
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError("No fake response left.")
        return self.responses.pop(0)


@pytest.fixture
def public_dns(monkeypatch):
    """The URL guard resolves the host; a test answers a public address without the network."""
    monkeypatch.setattr(
        "hydromodpy.core.io.fetch.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )


@pytest.mark.fast
def test_fetch_atom_entries_follows_pagination():
    client = FakeClient([FakeResponse(ATOM_PAGE_1), FakeResponse(ATOM_PAGE_2)])

    entries = fetch_atom_entries(
        "https://example.test/feed",
        {"limit": 1},
        client=client,  # type: ignore[arg-type]
    )

    assert [entry.identifier for entry in entries] == ["BDALTI", "RGEALTI"]
    assert [call["params"]["page"] for call in client.calls] == [1, 2]


@pytest.mark.fast
@pytest.mark.parametrize("status", [429, 503])
def test_a_status_the_client_gives_up_on_is_an_error_naming_it(status):
    """The retries live in the client of ``core/io/fetch``; what it hands back failed."""
    client = FakeClient([FakeResponse(status_code=status)])

    with pytest.raises(GeoPlateformeDownloadError, match=str(status)):
        fetch_atom_entries(
            "https://example.test/feed",
            {"limit": 1},
            client=client,  # type: ignore[arg-type]
        )

    assert len(client.calls) == 1


@pytest.mark.fast
def test_list_files_converts_atom_entries_to_download_files():
    client = FakeClient([FakeResponse(ATOM_FILES)])

    files = list_files(
        "BDALTI",
        "sub",
        client=client,  # type: ignore[arg-type]
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
    client = FakeClient([])

    path = download_file(
        DownloadFile("BDALTI", "sub", "archive.7z", "https://example.test/archive.7z"),
        tmp_path,
        client=client,  # type: ignore[arg-type]
    )

    assert path == target
    assert target.read_bytes() == b"cached"
    assert client.calls == []


@pytest.mark.fast
def test_download_file_writes_part_then_final(tmp_path, public_dns):
    client = FakeClient([FakeResponse(content=b"payload")])

    path = download_file(
        DownloadFile("BDALTI", "sub", "archive.7z", "https://example.test/archive.7z"),
        tmp_path,
        client=client,  # type: ignore[arg-type]
    )

    assert path == tmp_path / "archive.7z"
    assert path.read_bytes() == b"payload"
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".part")] == []


@pytest.mark.fast
def test_a_stale_partial_file_never_reaches_the_answer(tmp_path, public_dns):
    """The fetch writes a fresh partial of its own, so a stale one is never read back."""
    (tmp_path / "archive.7z.part").write_bytes(b"stale")
    client = FakeClient([FakeResponse(content=b"fresh", status_code=200)])

    path = download_file(
        DownloadFile("BDALTI", "sub", "archive.7z", "https://example.test/archive.7z"),
        tmp_path,
        client=client,  # type: ignore[arg-type]
    )

    assert path.read_bytes() == b"fresh"
