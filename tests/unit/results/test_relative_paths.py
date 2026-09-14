"""Workspace-relative path helpers and tracked-input encoding."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.state.paths import (
    CATALOG_FILENAME,
    cache_dir,
    decode_workspace_path,
    encode_workspace_path,
    from_workspace_relative,
    is_under_workspace,
    resolve_workspace,
    state_dir,
    to_workspace_relative,
    to_workspace_uri,
)


def test_to_workspace_relative_returns_posix_path(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    target = ws / "sub" / "file.tif"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x")

    assert to_workspace_relative(ws, target) == "sub/file.tif"


def test_to_workspace_relative_rejects_outsider(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    other = tmp_path / "out" / "blob.bin"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"x")

    with pytest.raises(ValueError, match="is not under workspace"):
        to_workspace_relative(ws, other)


def test_from_workspace_relative_rebuilds_absolute_path(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    abs_path = from_workspace_relative(ws, "data/dem/raw/file.tif")
    assert abs_path == ws.resolve() / "data" / "dem" / "raw" / "file.tif"


def test_is_under_workspace_truth_table(tmp_path: Path):
    ws = tmp_path / "ws"
    inside = ws / "x" / "y"
    inside.parent.mkdir(parents=True)
    inside.touch()
    outside = tmp_path / "other.txt"
    outside.touch()
    assert is_under_workspace(ws, inside) is True
    assert is_under_workspace(ws, outside) is False


def test_encode_workspace_path_prefers_workspace_relative(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    target = ws / "a" / "b.txt"
    target.parent.mkdir(parents=True)
    target.touch()

    encoded = encode_workspace_path(ws, target)
    assert encoded == "a/b.txt"
    assert not encoded.startswith("/")


def test_encode_workspace_path_falls_back_to_cache_uri(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    monkeypatch.setenv("HMP_CACHE_HOME", str(cache_root))

    ws = tmp_path / "ws"
    ws.mkdir()
    binary = cache_root / "bin" / "mf6" / "6.4.4" / "mf6"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"binary")

    encoded = encode_workspace_path(ws, binary)
    assert encoded.startswith("cache://")
    assert encoded == "cache://bin/mf6/6.4.4/mf6"

    decoded = decode_workspace_path(ws, encoded)
    assert decoded == binary.resolve()


def test_encode_workspace_path_falls_back_to_state_uri(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    state_root = tmp_path / "state"
    state_root.mkdir()
    monkeypatch.setenv("HMP_STATE_HOME", str(state_root))

    ws = tmp_path / "ws"
    ws.mkdir()
    lock = state_root / "locks" / "foo.lock"
    lock.parent.mkdir(parents=True)
    lock.touch()

    encoded = encode_workspace_path(ws, lock)
    assert encoded == "state://locks/foo.lock"
    assert decode_workspace_path(ws, encoded) == lock.resolve()


def test_encode_workspace_path_raises_when_unanchored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("HMP_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "state"))
    (tmp_path / "cache").mkdir(exist_ok=True)
    (tmp_path / "state").mkdir(exist_ok=True)
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "elsewhere" / "blob.bin"
    outside.parent.mkdir(parents=True)
    outside.touch()

    with pytest.raises(ValueError, match="Cannot encode"):
        encode_workspace_path(ws, outside)


def test_decode_workspace_path_with_absolute_input_returns_itself(tmp_path: Path):
    ws = tmp_path / "ws"
    abs_path = tmp_path / "abs" / "f.txt"
    abs_path.parent.mkdir(parents=True)
    abs_path.touch()
    assert decode_workspace_path(ws, str(abs_path)) == abs_path.resolve()


def test_to_workspace_uri_is_file_scheme(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    uri = to_workspace_uri(ws)
    assert uri.startswith("file://")
    assert resolve_workspace(uri) == ws.resolve()


def test_resolve_workspace_rejects_non_local_uri():
    with pytest.raises(NotImplementedError, match="s3"):
        resolve_workspace("s3://bucket/prefix")


def test_resolve_workspace_handles_bare_path(tmp_path: Path):
    bare = str(tmp_path)
    assert resolve_workspace(bare) == Path(bare)


def test_tracked_files_canonical_path_is_relative(tmp_path: Path):
    """Simulate a P3-compliant INSERT into tracked_files and verify storage."""
    ws = tmp_path / "ws"
    ws.mkdir()
    db_path = ws / CATALOG_FILENAME
    sample = ws / "inputs" / "dem.tif"
    sample.parent.mkdir(parents=True)
    sample.write_bytes(b"raster")

    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE tracked_files ("
            " sim_id VARCHAR,"
            " role VARCHAR,"
            " canonical_path VARCHAR NOT NULL,"
            " PRIMARY KEY (sim_id, role, canonical_path))"
        )
        encoded = encode_workspace_path(ws, sample)
        conn.execute(
            "INSERT INTO tracked_files (sim_id, role, canonical_path) VALUES (?, ?, ?)",
            ["sim-1", "input", encoded],
        )
        rows = conn.execute("SELECT canonical_path FROM tracked_files").fetchall()
        assert rows == [("inputs/dem.tif",)]
        assert not os.path.isabs(rows[0][0])
    finally:
        conn.close()


def test_entries_file_path_relative_via_fixture(tmp_path: Path):
    """Fixture-only check until P4 wires the helper end-to-end in data cache."""
    ws = tmp_path / "ws"
    ws.mkdir()
    db_path = ws / "data" / "cache.duckdb"
    db_path.parent.mkdir(parents=True)
    sample = ws / "data" / "dem" / "raw" / "DEM.tif"
    sample.parent.mkdir(parents=True)
    sample.write_bytes(b"r")

    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE entries ("
            " id INTEGER PRIMARY KEY,"
            " variable VARCHAR NOT NULL,"
            " source VARCHAR NOT NULL,"
            " file_path TEXT NOT NULL)"
        )
        encoded = encode_workspace_path(ws, sample)
        conn.execute(
            "INSERT INTO entries (id, variable, source, file_path) VALUES (?, ?, ?, ?)",
            [1, "dem", "custom", encoded],
        )
        rows = conn.execute("SELECT file_path FROM entries").fetchall()
        assert rows == [("data/dem/raw/DEM.tif",)]
        assert not os.path.isabs(rows[0][0])
    finally:
        conn.close()


def test_state_dir_paths_helpers_still_resolve(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HMP_CACHE_HOME", str(tmp_path / "cache"))
    assert state_dir() == (tmp_path / "state").resolve()
    assert cache_dir() == (tmp_path / "cache").resolve()
