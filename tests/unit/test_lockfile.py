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


def test_lockfile_resolves_workspace_data_variable_relative_paths(tmp_path):
    workspace = tmp_path / "workspace"
    data_dir = workspace / "data" / "hydrometry"
    data_dir.mkdir(parents=True)
    src = data_dir / "hydrometry_hubeau_A_20200101_20200102_D.csv"
    src.write_text("datetime,value\n2020-01-01,1.0\n")

    cat = DataCatalogDuckDB(workspace / "data" / "cache.duckdb")
    cat.register(
        variable="hydrometry",
        source="hubeau",
        station_id="A",
        file_path=src.name,
    )
    dest = workspace / LOCKFILE_NAME
    write_lockfile(cat, dest)

    entries = read_lockfile(dest)
    assert len(entries) == 1
    assert entries[0].file_path == src.name
    assert entries[0].sha256 == sha256_of(src)
    assert verify_frozen(cat, dest) == []


def test_verify_frozen_keeps_distinct_gridded_artifacts(tmp_path):
    workspace = tmp_path / "workspace"
    data_dir = workspace / "data" / "precipitation"
    data_dir.mkdir(parents=True)
    first = data_dir / "precip_a.nc"
    second = data_dir / "precip_b.nc"
    first.write_text("a")
    second.write_text("b")

    cat = DataCatalogDuckDB(workspace / "data" / "cache.duckdb")
    cat.register(variable="precipitation", source="sim2", file_path=first.name)
    cat.register(variable="precipitation", source="sim2", file_path=second.name)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(cat, dest)

    entries = read_lockfile(dest)
    assert {entry.file_path for entry in entries} == {first.name, second.name}
    assert verify_frozen(cat, dest) == []
