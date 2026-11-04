"""Tests of `runners.state`: the fingerprints that decide whether a stored trial is the same trial."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import BaseModel

from hydromodpy.calibration.runners import state
from hydromodpy.core import tracking


class _Config(BaseModel):
    name: str = "c"


def _entry(path: Path, role: str = "dem") -> SimpleNamespace:
    return SimpleNamespace(role=role, category="data", canonical_path=path)


def test_an_entry_point_without_a_colon_is_refused() -> None:
    with pytest.raises(ValueError, match="'module.path:callable', got: 'metrics'"):
        state.load_metric_fn_entry_point("metrics")


@pytest.mark.parametrize("centers", [np.zeros(3), np.zeros((0, 2))])
def test_a_mesh_without_centroids_has_no_identity(centers) -> None:
    ctx = SimpleNamespace(setup=SimpleNamespace(cell_mesh=SimpleNamespace(centers=centers)))

    assert state.mesh_fingerprint(ctx) is None


def test_a_map_folder_and_a_missing_map_have_a_digest(tmp_path) -> None:
    folder = tmp_path / "map"
    folder.mkdir()
    (folder / "a.txt").write_text("x")

    assert state._map_digest(folder) == state.sha256_directory(folder)
    assert state._map_digest(tmp_path / "none") == "missing"


def test_input_files_are_fingerprinted_by_kind(monkeypatch, tmp_path) -> None:
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir" / "a.txt").write_text("a")
    (tmp_path / "f.txt").write_text("hello")
    entries = [
        _entry(tmp_path / "f.txt", "file"),
        _entry(tmp_path / "dir", "dir"),
        _entry(tmp_path / "gone", "gone"),
    ]
    monkeypatch.setattr(tracking, "collect_input_files", lambda config, base=None: entries)

    found = {item["role"]: item for item in state._input_file_fingerprints(_Config())}

    assert found["file"]["kind"] == "file"
    assert found["file"]["sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert found["file"]["size_bytes"] == 5
    assert found["dir"]["sha256"] == state.sha256_directory(tmp_path / "dir")
    assert (found["gone"]["kind"], found["gone"]["exists"]) == ("missing", False)


def test_a_configuration_whose_inputs_cannot_be_listed_has_no_fingerprints(monkeypatch) -> None:
    def refuse(config, base=None):
        raise RuntimeError("no inputs")

    monkeypatch.setattr(tracking, "collect_input_files", refuse)

    assert state._input_file_fingerprints(_Config()) == []
    assert state._input_file_fingerprints(object()) == []
