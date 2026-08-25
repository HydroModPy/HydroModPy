"""Reproducibility-snapshot determinism for ``hydromodpy.lock``.

These regression tests pin the deterministic behaviour of the data-freeze
layer:

- two lockfiles built from the same catalog inputs are byte-identical once
  the wall-clock timestamps (``generated_at`` / ``fetched_at``) are
  normalised, and the content-bearing sections (``inputs``, ``schema``,
  ``binaries``, ``[[artefact]]``) round-trip without drift;
- a snapshot survives a write -> read round-trip with field-level equality
  against the source catalog state;
- the dark verification branches (missing catalog key, deleted on-disk
  artefact, empty ``[inputs]`` fallback, schema-sha fallback, gzip archive
  round-trip) all classify mismatches correctly on real inputs.

Everything runs on ``tmp_path``; nothing touches the repo tree.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import tomlkit

from hydromodpy.data.data_freeze import (
    LOCKFILE_NAME,
    LockedArtifact,
    archive_lockfile,
    read_lockfile,
    read_lockfile_inputs,
    read_lockfile_schema_sha256,
    restore_archive,
    sha256_of,
    verify_frozen,
    verify_inputs_strict,
    write_lockfile,
)
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

pytestmark = pytest.mark.regression


# Wall-clock fields that legitimately differ between two writes. Everything
# else must be stable for a snapshot to be reproducible.
_VOLATILE = re.compile(
    r'(generated_at\s*=\s*"[^"]*"|fetched_at\s*=\s*"[^"]*"|"[^"]*T[^"]*\+00:00")'
)


def _normalise(text: str) -> str:
    """Blank out the wall-clock fields so two snapshots can be compared."""
    return _VOLATILE.sub("<ts>", text)


def _normalise_section(section: Any) -> dict:
    """Return a parsed section with its wall-clock members neutralised.

    ``[inputs]`` carries one ``fetched_at`` per entry, so comparing the
    parsed section verbatim would only pass while both writes happen to land
    inside the same second.
    """
    out: dict = {}
    for key, value in dict(section).items():
        if isinstance(value, dict):
            out[key] = {k: ("<ts>" if k == "fetched_at" else v) for k, v in value.items()}
        else:
            out[key] = "<ts>" if key in ("generated_at", "fetched_at") else value
    return out


def _seed_two_inputs(tmp: Path) -> tuple[DataCatalogDuckDB, Path, Path, Path]:
    """Two catalog entries under a workspace; deterministic byte payloads."""
    workspace = tmp / "workspace"
    data_dir = workspace / "data" / "hydrometry"
    data_dir.mkdir(parents=True)
    first = data_dir / "hydrometry_hubeau_A.csv"
    second = data_dir / "hydrometry_hubeau_B.csv"
    first.write_text("datetime,value\n2020-01-01,1.0\n")
    second.write_text("datetime,value\n2020-01-02,2.0\n")
    catalog = DataCatalogDuckDB(workspace / "data" / "cache.duckdb")
    catalog.register(
        variable="hydrometry",
        source="hubeau",
        station_id="A",
        file_path=first.name,
        file_mtime=1_600_000_000.5,
    )
    catalog.register(
        variable="hydrometry",
        source="hubeau",
        station_id="B",
        file_path=second.name,
        file_mtime=1_600_000_100.25,
    )
    return catalog, workspace, first, second


# -------------------------------------------------------------- determinism


def test_two_writes_are_byte_identical_after_timestamp_normalisation(
    tmp_path: Path,
) -> None:
    """Same inputs -> same snapshot (modulo wall-clock timestamps)."""
    catalog, workspace, _first, _second = _seed_two_inputs(tmp_path)
    a = workspace / "a.lock"
    b = workspace / "b.lock"
    write_lockfile(catalog, a, schema_sha256="cafef00d")
    write_lockfile(catalog, b, schema_sha256="cafef00d")
    catalog.close()

    text_a = a.read_text()
    text_b = b.read_text()
    # The only freedom between two writes is the timestamp fields.
    assert _normalise(text_a) == _normalise(text_b)
    # And the parsed content sections are equal once those are neutralised.
    doc_a = tomlkit.parse(text_a)
    doc_b = tomlkit.parse(text_b)
    for section in ("schema", "binaries", "inputs"):
        assert _normalise_section(doc_a[section]) == _normalise_section(doc_b[section])


def test_one_write_stamps_every_entry_with_the_same_instant(tmp_path: Path) -> None:
    """A snapshot reads the clock once: no entry can straddle a second."""
    catalog, workspace, _first, _second = _seed_two_inputs(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest)
    catalog.close()

    doc = tomlkit.parse(dest.read_text())
    stamps = {str(entry["fetched_at"]) for entry in dict(doc["inputs"]).values()}
    stamps.add(str(doc["hydromodpy"]["generated_at"]))
    assert len(stamps) == 1


def test_input_ordering_is_stable_across_writes(tmp_path: Path) -> None:
    """Inputs come out in the same deterministic order on every write."""
    catalog, workspace, first, second = _seed_two_inputs(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest)
    keys_one = list(read_lockfile_inputs(dest))
    write_lockfile(catalog, dest)
    keys_two = list(read_lockfile_inputs(dest))
    catalog.close()

    assert keys_one == keys_two == sorted([first.name, second.name])


def test_artefact_sha256_independent_of_run(tmp_path: Path) -> None:
    """SHA-256 digests depend only on file bytes, not on write timing."""
    catalog, workspace, first, second = _seed_two_inputs(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest)
    inputs = read_lockfile_inputs(dest)
    catalog.close()

    assert inputs[first.name]["sha256"] == sha256_of(first)
    assert inputs[second.name]["sha256"] == sha256_of(second)
    assert inputs[first.name]["sha256"] != inputs[second.name]["sha256"]


# ---------------------------------------------------------------- round-trip


def test_snapshot_round_trips_to_source_state(tmp_path: Path) -> None:
    """Parsed ``[[artefact]]`` rows equal the source catalog entries."""
    catalog, workspace, first, second = _seed_two_inputs(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest)
    catalog.close()

    entries = read_lockfile(dest)
    by_path = {entry.file_path: entry for entry in entries}
    assert set(by_path) == {first.name, second.name}

    a = by_path[first.name]
    assert isinstance(a, LockedArtifact)
    assert a.variable == "hydrometry"
    assert a.source == "hubeau"
    assert a.station_id == "A"
    assert a.sha256 == sha256_of(first)
    assert a.size_bytes == first.stat().st_size
    assert a.file_mtime == 1_600_000_000.5
    assert a.fetched_at.endswith("+00:00")

    b = by_path[second.name]
    assert b.station_id == "B"
    assert b.file_mtime == 1_600_000_100.25
    # A clean snapshot must verify with no mismatch.
    assert verify_frozen(DataCatalogDuckDB(workspace / "data" / "cache.duckdb"), dest) == []


# --------------------------------------------------- schema-sha fallback paths


def test_schema_sha256_round_trips(tmp_path: Path) -> None:
    catalog, workspace, _f, _s = _seed_two_inputs(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest, schema_sha256="0123abcd")
    catalog.close()
    assert read_lockfile_schema_sha256(dest) == "0123abcd"


def test_schema_sha256_falls_back_to_legacy_key(tmp_path: Path) -> None:
    """Pre-P9 lockfiles stored ``schema.sha256``; the reader still honours it."""
    legacy = tmp_path / "legacy.lock"
    legacy.write_text('[schema]\ncatalog = 1\nsha256 = "legacysha"\n')
    assert read_lockfile_schema_sha256(legacy) == "legacysha"


def test_schema_sha256_absent_returns_none(tmp_path: Path) -> None:
    no_schema = tmp_path / "noschema.lock"
    no_schema.write_text('[hydromodpy]\nversion = "2.0.0"\n')
    assert read_lockfile_schema_sha256(no_schema) is None

    empty_schema = tmp_path / "empty.lock"
    empty_schema.write_text("[schema]\ncatalog = 1\n")
    assert read_lockfile_schema_sha256(empty_schema) is None


# ---------------------------------------------------- verify dark branches


def test_verify_frozen_flags_entry_absent_from_lockfile(tmp_path: Path) -> None:
    """A catalog entry registered after the freeze is reported as missing."""
    catalog, workspace, _first, _second = _seed_two_inputs(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest)

    extra = workspace / "data" / "hydrometry" / "hydrometry_hubeau_C.csv"
    extra.write_text("datetime,value\n2020-01-03,3.0\n")
    catalog.register(
        variable="hydrometry",
        source="hubeau",
        station_id="C",
        file_path=extra.name,
    )

    mismatches = verify_frozen(catalog, dest)
    catalog.close()
    assert len(mismatches) == 1
    m = mismatches[0]
    assert m.kind == "missing"
    assert m.path == extra.name
    assert m.station_id == "C"
    assert m.expected is None


def test_verify_frozen_flags_deleted_artefact(tmp_path: Path) -> None:
    """A locked artefact that vanished from disk is a ``missing`` mismatch."""
    catalog, workspace, first, _second = _seed_two_inputs(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest)
    expected_sha = sha256_of(first)
    first.unlink()

    mismatches = verify_frozen(catalog, dest)
    catalog.close()
    missing = [m for m in mismatches if m.path == first.name]
    assert len(missing) == 1
    m = missing[0]
    assert m.kind == "missing"
    assert m.observed is None
    assert m.expected == expected_sha


def test_verify_inputs_strict_flags_deleted_artefact(tmp_path: Path) -> None:
    catalog, workspace, first, _second = _seed_two_inputs(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest)
    expected_sha = sha256_of(first)
    first.unlink()

    mismatches = verify_inputs_strict(catalog, dest)
    catalog.close()
    missing = [m for m in mismatches if m.path == first.name]
    assert len(missing) == 1
    assert missing[0].kind == "missing"
    assert missing[0].expected == expected_sha
    assert missing[0].observed is None


def test_verify_inputs_strict_falls_back_when_inputs_absent(tmp_path: Path) -> None:
    """Without an ``[inputs]`` table, strict verify delegates to ``verify_frozen``."""
    catalog, workspace, _first, _second = _seed_two_inputs(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest)

    # Strip the [inputs] section: legacy / artefact-only lockfile shape.
    doc = tomlkit.parse(dest.read_text())
    del doc["inputs"]
    legacy = workspace / "legacy.lock"
    legacy.write_text(tomlkit.dumps(doc))
    assert read_lockfile_inputs(legacy) == {}

    # All artefacts present on disk -> fallback path returns no mismatch.
    assert verify_inputs_strict(catalog, legacy) == []
    catalog.close()


# ----------------------------------------------------- gzip archive round-trip


def test_gzip_archive_round_trip_preserves_sha256(tmp_path: Path) -> None:
    """A ``.tar.gz`` export restores the lockfile and verifies each digest."""
    catalog, workspace, first, second = _seed_two_inputs(tmp_path)
    archive = tmp_path / "export.tar.gz"
    archive_lockfile(catalog, archive, lockfile_dest=tmp_path / LOCKFILE_NAME)
    catalog.close()
    assert archive.is_file()

    restore_dir = tmp_path / "restored"
    restore_archive(archive, restore_dir)

    lock = restore_dir / LOCKFILE_NAME
    assert lock.is_file()
    for src in (first, second):
        stored = restore_dir / "artefacts" / sha256_of(src) / src.name
        assert stored.is_file()
        assert sha256_of(stored) == sha256_of(src)


def test_zstandard_archive_round_trip_preserves_sha256(tmp_path: Path) -> None:
    """A ``.tar.zst`` export (default suffix) restores and verifies digests."""
    zstd = pytest.importorskip("zstandard")
    assert zstd  # used to gate the test, not a tautology on the unit under test

    catalog, _workspace, first, second = _seed_two_inputs(tmp_path)
    archive = tmp_path / "export.tar.zst"
    archive_lockfile(catalog, archive, lockfile_dest=tmp_path / LOCKFILE_NAME)
    catalog.close()
    assert archive.is_file()

    restore_dir = tmp_path / "restored_zst"
    restore_archive(archive, restore_dir)

    assert (restore_dir / LOCKFILE_NAME).is_file()
    for src in (first, second):
        stored = restore_dir / "artefacts" / sha256_of(src) / src.name
        assert stored.is_file()
        assert sha256_of(stored) == sha256_of(src)
