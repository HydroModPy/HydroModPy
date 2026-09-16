"""The double-execution comparator is itself under test.

A comparator nobody tested is a comparator nobody should believe. These cases
build two run directories by hand, move one number at a time, and check that
the verdict changes exactly when it should. They run in a second: the four
frozen projects are the comparator's field use, not its test.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import zarr

from tests.characterization.comparator import (
    FIELD_ATOL,
    FIELD_RTOL,
    FROZEN_PROJECTS,
    REPO_ROOT,
    SIGNATURE_RTOL,
    compare_arrays,
    compare_run_dirs,
    render_markdown,
)

HEAD = np.linspace(10.0, 20.0, 24).reshape(2, 1, 12)
CONNECTIVITY = np.arange(48, dtype=np.int32).reshape(12, 4)


def _write_run(root: Path, *, head: np.ndarray, connectivity: np.ndarray, area: float) -> Path:
    """Write a minimal run directory shaped like the storage contract."""
    root.mkdir(parents=True, exist_ok=True)
    group = zarr.open_group(str(root / "fields.zarr"), mode="w")
    group.create_array("head", shape=head.shape, dtype=head.dtype)[...] = head
    mesh = group.create_group("mesh")
    mesh.create_array("face_node_connectivity", shape=connectivity.shape, dtype=connectivity.dtype)[
        ...
    ] = connectivity

    tables = root / "tables.parquet"
    tables.mkdir(exist_ok=True)
    pd.DataFrame(
        {
            "sim_id": ["whatever-changes-every-run"],
            "percent_error": [0.001],
            "solver": ["modflow_nwt"],
        }
    ).to_parquet(tables / "mass_balance.parquet")

    (root / "manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "run": {"solver": "modflow_nwt", "flow_regime": "steady"},
                "geometry": {
                    "n_cells": int(head.shape[-1]),
                    "n_layers": int(head.shape[-2]),
                    "catchment": {"catch_area": area},
                },
                "artifacts": [{"path": "fields.zarr"}],
            }
        ),
        encoding="utf-8",
    )
    return root


def test_two_identical_runs_show_no_drift(tmp_path: Path) -> None:
    """The comparator is silent when there is nothing to say."""
    a = _write_run(tmp_path / "a", head=HEAD, connectivity=CONNECTIVITY, area=1.5)
    b = _write_run(tmp_path / "b", head=HEAD, connectivity=CONNECTIVITY, area=1.5)
    comparison = compare_run_dirs(a, b)
    assert comparison.ok, [verdict.target for verdict in comparison.drifted]
    assert len(comparison.verdicts) > 5
    assert "mass_balance.parquet:sim_id" in comparison.dropped_columns


def test_a_head_moved_past_the_band_is_reported(tmp_path: Path) -> None:
    """A change in a computed field is what the comparator exists to catch."""
    moved = HEAD.copy()
    moved[0, 0, 3] += 1e-3
    a = _write_run(tmp_path / "a", head=HEAD, connectivity=CONNECTIVITY, area=1.5)
    b = _write_run(tmp_path / "b", head=moved, connectivity=CONNECTIVITY, area=1.5)
    comparison = compare_run_dirs(a, b)
    assert not comparison.ok
    drifted = {verdict.target for verdict in comparison.drifted}
    assert "fields.zarr/head" in drifted


def test_a_head_inside_the_band_is_not_reported(tmp_path: Path) -> None:
    """Round-off below the declared band is not a finding."""
    moved = HEAD.copy()
    moved[0, 0, 3] += FIELD_ATOL
    a = _write_run(tmp_path / "a", head=HEAD, connectivity=CONNECTIVITY, area=1.5)
    b = _write_run(tmp_path / "b", head=moved, connectivity=CONNECTIVITY, area=1.5)
    comparison = compare_run_dirs(a, b)
    assert comparison.ok, [verdict.target for verdict in comparison.drifted]


def test_a_reordered_connectivity_is_a_difference(tmp_path: Path) -> None:
    """Integer arrays are compared exactly: a renumbered mesh is not rounding."""
    swapped = CONNECTIVITY.copy()
    swapped[[0, 1]] = swapped[[1, 0]]
    a = _write_run(tmp_path / "a", head=HEAD, connectivity=CONNECTIVITY, area=1.5)
    b = _write_run(tmp_path / "b", head=HEAD, connectivity=swapped, area=1.5)
    comparison = compare_run_dirs(a, b)
    assert not comparison.ok
    verdict = next(v for v in comparison.drifted if v.target.endswith("face_node_connectivity"))
    assert verdict.mode == "exact"


def test_a_moved_catchment_area_is_reported(tmp_path: Path) -> None:
    """The seal is compared too, on the quantities that describe the object."""
    a = _write_run(tmp_path / "a", head=HEAD, connectivity=CONNECTIVITY, area=1.5)
    b = _write_run(tmp_path / "b", head=HEAD, connectivity=CONNECTIVITY, area=1.5001)
    comparison = compare_run_dirs(a, b)
    assert not comparison.ok
    assert any("catch_area" in verdict.target for verdict in comparison.drifted)


def test_a_missing_run_directory_is_an_error_not_a_verdict(tmp_path: Path) -> None:
    """A comparison that could not happen says so instead of passing."""
    a = _write_run(tmp_path / "a", head=HEAD, connectivity=CONNECTIVITY, area=1.5)
    comparison = compare_run_dirs(a, tmp_path / "absent")
    assert not comparison.ok
    assert comparison.errors


def test_different_shapes_fall_back_to_the_signature() -> None:
    """When the mesh moved, the distribution decides instead of the cells."""
    verdict = compare_arrays("head", HEAD, np.linspace(10.0, 20.0, 36).reshape(3, 1, 12))
    assert verdict.mode == "signature"
    assert verdict.within, "a mesh that moved is not by itself a change in the answer"
    assert "36 finite values" in verdict.detail

    shifted = compare_arrays("head", HEAD, HEAD.reshape(1, 2, 12) * 1.5)
    assert shifted.mode == "signature"
    assert not shifted.within


@pytest.mark.parametrize(
    ("delta", "expected_within"),
    [(0.0, True), (FIELD_ATOL / 2, True), (1e-3, False)],
)
def test_the_elementwise_band_is_the_declared_one(delta: float, expected_within: bool) -> None:
    """The verdict follows ``atol + rtol * max|b|`` and nothing else."""
    moved = HEAD.copy()
    moved[0, 0, 0] += delta
    verdict = compare_arrays("head", HEAD, moved)
    assert verdict.mode == "elementwise"
    assert verdict.within is expected_within
    assert verdict.max_abs == pytest.approx(delta, abs=FIELD_ATOL)


def test_the_report_names_what_drifted(tmp_path: Path) -> None:
    """The Markdown a reader opens states the finding, not just a count."""
    moved = HEAD.copy()
    moved[0, 0, 3] += 1e-3
    a = _write_run(tmp_path / "a", head=HEAD, connectivity=CONNECTIVITY, area=1.5)
    b = _write_run(tmp_path / "b", head=moved, connectivity=CONNECTIVITY, area=1.5)
    report = render_markdown([compare_run_dirs(a, b)], total_seconds=1.0)
    assert "DRIFT" in report
    assert "fields.zarr/head" in report
    assert f"{FIELD_RTOL:g}" in report
    assert f"{SIGNATURE_RTOL:g}" in report


def test_every_frozen_project_is_committed() -> None:
    """The four projects the comparator names exist, and exist in a fresh clone.

    Two of the cheapest projects in this checkout are untracked scratch
    directories; naming one here would give a tool that works on one machine
    and fails on every other.
    """
    for name in FROZEN_PROJECTS:
        path = REPO_ROOT / name
        assert path.is_file(), f"frozen project missing: {name}"
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", name],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert tracked.returncode == 0, f"frozen project is not committed: {name}"
