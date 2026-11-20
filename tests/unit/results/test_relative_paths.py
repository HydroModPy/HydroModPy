"""Workspace-relative path helpers and tracked-input encoding."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.state.portable import (
    decode_workspace_path,
    encode_workspace_path,
    resolve_workspace,
    to_workspace_relative,
)


def test_to_workspace_relative_rejects_outsider(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    other = tmp_path / "out" / "blob.bin"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"x")

    with pytest.raises(ValueError, match="is not under workspace"):
        to_workspace_relative(ws, other)


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


def test_resolve_workspace_rejects_non_local_uri():
    with pytest.raises(NotImplementedError, match="s3"):
        resolve_workspace("s3://bucket/prefix")


def test_resolve_workspace_handles_bare_path(tmp_path: Path):
    bare = str(tmp_path)
    assert resolve_workspace(bare) == Path(bare)
