"""Unit tests for the workspace-level geographic cache (phase P02)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hydromodpy.results.geographic_cache import (
    CACHE_DIRNAME,
    MANIFEST_FILENAME,
    GeographicCache,
    GeographicInputs,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path / "ws"


@pytest.fixture
def cache(workspace: Path) -> GeographicCache:
    return GeographicCache(workspace)


class TestFingerprint:
    def test_stable_for_same_inputs(self, cache):
        inputs = GeographicInputs(
            dem_path="/data/dem.tif",
            dem_sha256="aa" * 32,
            crs_wkt="EPSG:2154",
            bbox=(0.0, 0.0, 100.0, 100.0),
            resolution_m=5.0,
        )
        assert cache.fingerprint_of(inputs) == cache.fingerprint_of(inputs)

    def test_dict_and_dataclass_yield_same_hash(self, cache):
        dc = GeographicInputs(
            dem_path="/d/dem.tif",
            crs_wkt="EPSG:2154",
            bbox=(0.0, 0.0, 10.0, 10.0),
        )
        d = {
            "dem_path": "/d/dem.tif",
            "crs_wkt": "EPSG:2154",
            "bbox": (0.0, 0.0, 10.0, 10.0),
        }
        assert cache.fingerprint_of(dc) == cache.fingerprint_of(d)

    def test_changes_when_bbox_changes(self, cache):
        a = GeographicInputs(bbox=(0, 0, 10, 10), crs_wkt="EPSG:4326")
        b = GeographicInputs(bbox=(0, 0, 20, 20), crs_wkt="EPSG:4326")
        assert cache.fingerprint_of(a) != cache.fingerprint_of(b)

    def test_changes_when_dem_sha_changes(self, cache):
        a = GeographicInputs(dem_path="/d.tif", dem_sha256="aa" * 32)
        b = GeographicInputs(dem_path="/d.tif", dem_sha256="bb" * 32)
        assert cache.fingerprint_of(a) != cache.fingerprint_of(b)

    def test_dict_key_order_independent(self, cache):
        a = {"bbox": (0, 0, 1, 1), "crs_wkt": "EPSG:2154"}
        b = {"crs_wkt": "EPSG:2154", "bbox": (0, 0, 1, 1)}
        assert cache.fingerprint_of(a) == cache.fingerprint_of(b)

    def test_extra_fields_are_included(self, cache):
        base = GeographicInputs(crs_wkt="EPSG:4326", bbox=(0, 0, 1, 1))
        extra = GeographicInputs(
            crs_wkt="EPSG:4326",
            bbox=(0, 0, 1, 1),
            extra={"delineation": "d8"},
        )
        assert cache.fingerprint_of(base) != cache.fingerprint_of(extra)

    def test_auto_hashes_referenced_file(self, cache, tmp_path):
        dem = tmp_path / "dem.tif"
        dem.write_bytes(b"hello world")
        expected = hashlib.sha256(b"hello world").hexdigest()

        inputs = GeographicInputs(dem_path=str(dem))
        fp_auto = cache.fingerprint_of(inputs, hash_files=True)

        inputs_explicit = GeographicInputs(
            dem_path=str(dem),
            dem_sha256=expected,
        )
        fp_explicit = cache.fingerprint_of(
            inputs_explicit,
            hash_files=False,
        )
        assert fp_auto == fp_explicit

    def test_hex_length_64(self, cache):
        fp = cache.fingerprint_of(GeographicInputs(crs_wkt="EPSG:4326"))
        assert len(fp) == 64
        int(fp, 16)  # parses as hex


class TestCacheRoundtrip:
    def test_cache_root_layout(self, workspace, cache):
        assert cache.root == workspace / CACHE_DIRNAME
        assert cache.root.is_dir()

    def test_save_and_load(self, cache, tmp_path):
        payload = tmp_path / "payload"
        payload.mkdir()
        (payload / "dem.tif").write_bytes(b"hello")
        (payload / "watershed.parquet").write_bytes(b"geo")

        fp = "abc" * 10 + "def" * 10 + "1234"
        dst = cache.save(fp, payload, manifest={"source": "unit-test"})

        assert dst == cache.path_for(fp)
        assert cache.is_cached(fp)
        assert (dst / "dem.tif").read_bytes() == b"hello"
        assert (dst / MANIFEST_FILENAME).is_file()

        loaded = cache.load(fp)
        assert loaded == dst

    def test_is_cached_false_when_absent(self, cache):
        assert not cache.is_cached("not-cached")
        with pytest.raises(FileNotFoundError):
            cache.load("not-cached")

    def test_is_cached_false_without_manifest(self, cache, tmp_path):
        # A bare directory without the sentinel manifest file is not
        # considered cached - prevents half-written entries from being
        # used.
        fp = "z" * 64
        (cache.root / fp).mkdir()
        assert not cache.is_cached(fp)

    def test_save_does_not_overwrite_by_default(self, cache, tmp_path):
        payload = tmp_path / "payload"
        payload.mkdir()
        (payload / "dem.tif").write_bytes(b"v1")
        fp = "d" * 64
        cache.save(fp, payload)

        # Update file and call save again without overwrite=True
        (payload / "dem.tif").write_bytes(b"v2")
        cache.save(fp, payload)  # no-op on files
        assert (cache.path_for(fp) / "dem.tif").read_bytes() == b"v1"

    def test_overwrite_true_replaces(self, cache, tmp_path):
        payload = tmp_path / "payload"
        payload.mkdir()
        (payload / "dem.tif").write_bytes(b"v1")
        fp = "e" * 64
        cache.save(fp, payload)

        (payload / "dem.tif").write_bytes(b"v2")
        cache.save(fp, payload, overwrite=True)
        assert (cache.path_for(fp) / "dem.tif").read_bytes() == b"v2"

    def test_list_fingerprints(self, cache, tmp_path):
        payload = tmp_path / "payload"
        payload.mkdir()
        (payload / "dem.tif").write_bytes(b"x")
        fp_a = "a" * 64
        fp_b = "b" * 64
        cache.save(fp_a, payload)
        cache.save(fp_b, payload)
        assert cache.list_fingerprints() == [fp_a, fp_b]
