"""A docs build can read the validation results from another file.

The committed snapshot stays the default; HMP_VALIDATION_RESULTS_FILE points a
local build at fresh results without touching a tracked file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

EXT = Path(__file__).resolve().parents[3] / "docs" / "source" / "_ext"


@pytest.fixture(scope="module")
def V():
    sys.path.insert(0, str(EXT))
    import hmp_validation

    yield hmp_validation
    sys.path.remove(str(EXT))


def _write(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 1, "runs": {marker: {}}, "tests": {}}))


def test_the_committed_snapshot_is_the_default(V, tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(V.RESULTS_ENV, raising=False)
    _write(tmp_path / V.RESULTS_FILE, "snapshot")
    V.load(tmp_path)
    assert list(V.RESULTS["runs"]) == ["snapshot"]


def test_the_variable_points_at_another_file(V, tmp_path, monkeypatch) -> None:
    _write(tmp_path / V.RESULTS_FILE, "snapshot")
    _write(tmp_path / "local" / "fresh.json", "fresh")
    monkeypatch.setenv(V.RESULTS_ENV, str(tmp_path / "local" / "fresh.json"))
    V.load(tmp_path)
    assert list(V.RESULTS["runs"]) == ["fresh"]


def test_a_missing_file_warns_instead_of_emptying_the_page(V, tmp_path, monkeypatch) -> None:
    warned = []
    monkeypatch.setattr(V.logger, "warning", lambda *a, **k: warned.append(a))
    monkeypatch.setenv(V.RESULTS_ENV, str(tmp_path / "nowhere.json"))
    V.load(tmp_path)
    assert warned and V.RESULTS_ENV in warned[0][1]
    assert V.RESULTS == {}
