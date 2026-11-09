"""Unit tests for the generic url data source."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from hydromodpy.data.provenance.sidecars import Sidecar, load_sidecar, write_sidecar
from hydromodpy.data.source.port import FetchRequest
from hydromodpy.data.source.registry import data_sources
from hydromodpy.data.source.url import DemUrl, RechargeUrl, UrlSource


def test_url_source_hosts_from_instance() -> None:
    source = DemUrl(url="https://example.com/dem.tif")
    assert source.hosts == ("example.com",)


def test_pinned_sha256_found_without_network(tmp_path: Path) -> None:
    content = b"cached raster bytes"
    pin = hashlib.sha256(content).hexdigest()
    out_dir = tmp_path / "cache"
    out_dir.mkdir()

    # Pre-populate cache file matching pattern dem_url_*_<sha8>.*
    cached_file = out_dir / f"dem_url_example-com_{pin[:8]}.tif"
    cached_file.write_bytes(content)

    source = DemUrl(url="https://example.com/dem.tif", sha256=pin)
    req = FetchRequest(out_dir=out_dir)

    # With patch preventing any network connection
    with patch("socket.getaddrinfo", side_effect=AssertionError("Network accessed!")):
        res = source.fetch(req)

    assert len(res.files) == 1
    assert res.files[0].path == cached_file
    assert res.files[0].sha256 == pin
    assert res.files[0].origin == "url"


def test_etag_matches_without_redownload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"existing data"
    sha = hashlib.sha256(content).hexdigest()
    out_dir = tmp_path / "cache"
    out_dir.mkdir()

    data_file = out_dir / "dem_url_example-com_12345678.tif"
    data_file.write_bytes(content)
    sidecar = Sidecar(
        source="url",
        origin="https://example.com/dem.tif",
        sha256=sha,
        etag='"etag-v1"',
        last_modified="Wed, 21 Oct 2025 07:28:00 GMT",
    )
    write_sidecar(data_file, sidecar)

    # HEAD returns same ETag
    head_resp = MagicMock(status_code=200, headers={"ETag": '"etag-v1"'})
    head_resp.iter_content = MagicMock(return_value=iter([]))

    monkeypatch.setattr(
        "socket.getaddrinfo", lambda _h, _p: [(2, 1, 6, "", ("93.184.216.34", 443))]
    )
    with patch("requests.Session.request", return_value=head_resp) as mock_req:
        source = DemUrl(url="https://example.com/dem.tif")
        req = FetchRequest(out_dir=out_dir)
        res = source.fetch(req)

    assert len(res.files) == 1
    assert res.files[0].path == data_file
    assert res.files[0].sha256 == sha
    # Only HEAD request was issued, no GET streaming
    assert mock_req.call_count == 1
    assert mock_req.call_args[0][0] == "HEAD"


def test_etag_changed_triggers_redownload_and_writes_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "cache"
    out_dir.mkdir()

    old_file = out_dir / "recharge_url_example-com_12345678.tif"
    old_file.write_bytes(b"old")
    write_sidecar(
        old_file,
        Sidecar(source="url", origin="https://example.com/r.tif", sha256="old", etag='"v1"'),
    )

    new_content = b"new recharge raster"
    new_sha = hashlib.sha256(new_content).hexdigest()

    head_resp = MagicMock(status_code=200, headers={"ETag": '"v2"'})
    head_resp.iter_content = MagicMock(return_value=iter([]))

    get_resp = MagicMock(
        status_code=200, headers={"ETag": '"v2"', "Last-Modified": "Thu, 22 Oct 2025 08:00:00 GMT"}
    )
    get_resp.iter_content = MagicMock(return_value=iter([new_content]))

    monkeypatch.setattr(
        "socket.getaddrinfo", lambda _h, _p: [(2, 1, 6, "", ("93.184.216.34", 443))]
    )

    def fake_request(_self: Any, method: str, _url: str, **_kw: Any) -> MagicMock:
        return head_resp if method == "HEAD" else get_resp

    monkeypatch.setattr("requests.Session.request", fake_request)

    source = RechargeUrl(url="https://example.com/r.tif", license="ODbL-1.0")
    req = FetchRequest(out_dir=out_dir)
    res = source.fetch(req)

    assert len(res.files) == 1
    new_path = res.files[0].path
    assert new_path.is_file()
    assert new_path.name.startswith("recharge_url_example-com_")
    assert new_path.name.endswith(".tif")
    assert new_path.read_bytes() == new_content

    # Verify sidecar written
    sc = load_sidecar(new_path)
    assert sc.origin == "https://example.com/r.tif"
    assert sc.etag == '"v2"'
    assert sc.last_modified == "Thu, 22 Oct 2025 08:00:00 GMT"
    assert sc.license == "ODbL-1.0"
    assert sc.sha256 == new_sha
    assert sc.state == "raw"


def test_url_subclasses_registered_for_single_file_sections() -> None:
    expected_url_sections = {
        "crossings",
        "dem",
        "etp",
        "geology",
        "humidity",
        "hydrography",
        "lake_abacus",
        "lake_bathymetry",
        "lake_geometry",
        "layer_base",
        "precipitation",
        "radiation",
        "recharge",
        "runoff",
        "soil_capacity",
        "soil_moisture",
        "substratum",
        "temperature",
        "wind",
    }
    for sec in expected_url_sections:
        cls = data_sources.get(sec, "url")
        assert issubclass(cls, UrlSource)
        assert cls.section == sec
        assert cls.source_id == "url"
