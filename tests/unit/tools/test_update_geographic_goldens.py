"""The goldens regenerator runs pytest from the repository root on tests that exist.

``update_geographic_goldens.py`` hardcodes the tests it re-runs with
``--update-goldens``. The list once drifted to files that did not exist, and
the command regenerated nothing while exiting 0.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hydromodpy.spatial.geographic.cases import update_geographic_goldens

pytestmark = pytest.mark.fast


def test_the_regenerator_runs_pytest_where_its_test_paths_resolve(monkeypatch):
    calls = []

    def run(cmd, *, cwd, check):
        calls.append((cmd, Path(cwd)))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(update_geographic_goldens.subprocess, "run", run)

    assert update_geographic_goldens.main(["-x"]) == 0

    ((cmd, cwd),) = calls
    assert cmd[-2:] == ["--update-goldens", "-x"]
    assert update_geographic_goldens.GOLDEN_TEST_PATHS
    for relative_path in update_geographic_goldens.GOLDEN_TEST_PATHS:
        assert (cwd / relative_path).is_file(), f"{relative_path} is listed, not in the tree"
        source = (cwd / relative_path).read_text(encoding="utf-8")
        assert "update_goldens" in source, f"--update-goldens is a no-op for {relative_path}"
