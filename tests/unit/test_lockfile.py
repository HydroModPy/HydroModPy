"""Unit tests for the lockfile / frozen-mode helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.data.data_freeze import (
    LOCKFILE_NAME,
    archive_lockfile,
    read_lockfile,
    restore_archive,
    sha256_of,
    verify_frozen,
    write_lockfile,
)
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB


def _seed_catalog(tmp: Path) -> tuple[DataCatalogDuckDB, Path]:
    cache = tmp / "cache.duckdb"
    src = tmp / "x.csv"
    src.write_text("a,b\n1,2\n")
    cat = DataCatalogDuckDB(cache)
    cat.register(variable="hydrometry", source="custom", station_id="A", file_path=src)
    return cat, src


def test_sha256_of_matches_standard(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    # sha256("hello") = 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824
    assert sha256_of(p) == ("2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")


def test_write_and_read_roundtrip(tmp_path):
    cat, _ = _seed_catalog(tmp_path)
    dest = tmp_path / LOCKFILE_NAME
    write_lockfile(cat, dest)
    entries = read_lockfile(dest)
    assert len(entries) == 1
    assert entries[0].variable == "hydrometry"
    assert entries[0].sha256


def test_verify_frozen_detects_mutation(tmp_path):
    cat, src = _seed_catalog(tmp_path)
    dest = tmp_path / LOCKFILE_NAME
    write_lockfile(cat, dest)
    assert verify_frozen(cat, dest) == []
    src.write_text("a,b\n9,9\n")
    mismatches = verify_frozen(cat, dest)
    assert len(mismatches) == 1
    assert mismatches[0].kind == "sha256"


def test_archive_and_restore(tmp_path):
    cat, _ = _seed_catalog(tmp_path)
    archive = tmp_path / "export.tar"
    archive_lockfile(cat, archive, lockfile_dest=tmp_path / LOCKFILE_NAME)
    assert archive.is_file()
    restore_dir = tmp_path / "restored"
    restore_archive(archive, restore_dir)
    assert (restore_dir / LOCKFILE_NAME).is_file()
