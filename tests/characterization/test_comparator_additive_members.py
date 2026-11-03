"""The comparator holds the members the cell-mesh layout added, and only those.

A run written before the layout does not hold the cell centers, the family bits, the edge
tables or the two family tables. Comparing it to a run written after must not read
as drift, but a member missing from the newer run, or an unlisted new one, still
does.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import zarr

from tests.characterization.comparator import (
    ADDITIVE_DETAIL,
    ADDITIVE_MEMBERS,
    UGRID_DETAIL,
    UGRID_MEMBERS,
    compare_run_dirs,
    render_markdown,
)

HEAD = np.linspace(10.0, 20.0, 12).reshape(1, 1, 12)
CONNECTIVITY = np.arange(48, dtype=np.int32).reshape(12, 4)


def _run(
    root: Path,
    *,
    mesh_arrays: tuple[str, ...] = (),
    tables: tuple[str, ...] = (),
    engine: str | None = None,
) -> Path:
    """Write a minimal run directory with the named extra mesh arrays and tables.

    ``engine`` marks the run as written by the cell-mesh layout.
    """
    root.mkdir(parents=True)
    group = zarr.open_group(str(root / "fields.zarr"), mode="w")
    group.create_array("head", shape=HEAD.shape, dtype=HEAD.dtype)[...] = HEAD
    mesh = group.create_group("mesh")
    if engine is not None:
        mesh.attrs["engine"] = engine
    mesh.create_array("face_node_connectivity", shape=CONNECTIVITY.shape, dtype=np.int32)[...] = (
        CONNECTIVITY
    )
    for name in mesh_arrays:
        mesh.create_array(name, shape=(12,), dtype=np.float64)[...] = np.arange(12.0)
    folder = root / "tables.parquet"
    folder.mkdir()
    pd.DataFrame({"percent_error": [0.001]}).to_parquet(folder / "mass_balance.parquet")
    for name in tables:
        pd.DataFrame({"family": ["rivers"], "cell_id": [1]}).to_parquet(folder / name)
    artifacts = [{"path": "tables.parquet/mass_balance.parquet"}] + [
        {"path": f"tables.parquet/{name}"} for name in tables
    ]
    (root / "manifest.json").write_text(
        json.dumps({"manifest_version": 1, "run": {"solver": "modflow6"}, "artifacts": artifacts}),
        encoding="utf-8",
    )
    return root


def _verdicts(comparison, target: str):
    return [v for v in comparison.verdicts if v.target == target]


def test_a_member_the_layout_added_is_held_when_the_older_run_lacks_it(tmp_path):
    older = _run(tmp_path / "older")
    newer = _run(
        tmp_path / "newer",
        mesh_arrays=("face_x", "face_y", "face_family"),
        tables=("mesh_cell_families.parquet",),
    )

    comparison = compare_run_dirs(older, newer)

    assert comparison.ok, [v.target for v in comparison.drifted]
    for target in (
        "fields.zarr/mesh/face_x",
        "fields.zarr/mesh/face_family",
        "tables.parquet/mesh_cell_families.parquet",
    ):
        (verdict,) = _verdicts(comparison, target)
        assert (verdict.mode, verdict.within, verdict.detail) == (
            "presence",
            True,
            ADDITIVE_DETAIL,
        )


def test_an_additive_table_does_not_move_the_manifest_artifact_count(tmp_path):
    older = _run(tmp_path / "older")
    newer = _run(tmp_path / "newer", tables=("mesh_face_families.parquet",))

    comparison = compare_run_dirs(older, newer)

    (verdict,) = _verdicts(comparison, "manifest.json:artifacts (count)")
    assert (verdict.within, verdict.detail) == (True, "1 vs 1")


def test_an_unlisted_table_still_moves_the_manifest_artifact_count(tmp_path):
    older = _run(tmp_path / "older")
    newer = _run(tmp_path / "newer", tables=("flux.parquet",))

    comparison = compare_run_dirs(older, newer)

    (verdict,) = _verdicts(comparison, "manifest.json:artifacts (count)")
    assert (verdict.within, verdict.detail) == (False, "1 vs 2")


def test_a_member_the_newer_run_lost_is_a_drift(tmp_path):
    older = _run(
        tmp_path / "older", mesh_arrays=("face_x",), tables=("mesh_face_families.parquet",)
    )
    newer = _run(tmp_path / "newer")

    comparison = compare_run_dirs(older, newer)

    drifted = {v.target: v.detail for v in comparison.drifted}
    assert drifted == {
        "fields.zarr/mesh/face_x": "only in A",
        "tables.parquet/mesh_face_families.parquet": "only in A",
        "manifest.json:artifacts (count)": "2 vs 1",
    }


def test_a_new_member_off_the_list_is_a_drift(tmp_path):
    older = _run(tmp_path / "older")
    newer = _run(tmp_path / "newer", mesh_arrays=("face_x", "face_flux"))

    comparison = compare_run_dirs(older, newer)

    assert {v.target: v.detail for v in comparison.drifted} == {
        "fields.zarr/mesh/face_flux": "only in B"
    }


def test_a_member_both_runs_hold_is_compared(tmp_path):
    older = _run(tmp_path / "older", mesh_arrays=("face_x",))
    newer = _run(tmp_path / "newer", mesh_arrays=("face_x",))
    moved = zarr.open_group(str(newer / "fields.zarr"), mode="r+")
    moved["mesh/face_x"][3] = 100.0

    comparison = compare_run_dirs(older, newer)

    assert [v.target for v in comparison.drifted] == ["fields.zarr/mesh/face_x"]


def test_the_report_lists_the_additive_members_and_stays_green(tmp_path):
    older = _run(tmp_path / "older")
    newer = _run(tmp_path / "newer", mesh_arrays=("face_x",))

    report = render_markdown([compare_run_dirs(older, newer)], total_seconds=1.0)

    assert "Every compared target is inside its band." in report
    assert "### Additive members" in report
    assert "- `fields.zarr/mesh/face_x`" in report


def test_the_list_is_closed_to_the_cell_mesh_layout():
    assert {name.split("/")[-1] for name in ADDITIVE_MEMBERS if "mesh/" in name} == {
        "face_x",
        "face_y",
        "face_family",
        "face_zone",
        "edge_node_connectivity",
        "edge_face_connectivity",
        "edge_family",
    }
    assert {name for name in ADDITIVE_MEMBERS if name.startswith("tables.parquet/")} == {
        "tables.parquet/mesh_cell_families.parquet",
        "tables.parquet/mesh_face_families.parquet",
    }


def test_a_member_only_the_newer_run_holds_is_a_drift_when_the_older_run_has_the_layout(tmp_path):
    older = _run(tmp_path / "older", engine="regular")
    newer = _run(
        tmp_path / "newer",
        engine="regular",
        mesh_arrays=("face_family",),
        tables=("mesh_cell_families.parquet",),
    )

    comparison = compare_run_dirs(older, newer)

    assert {v.target: v.detail for v in comparison.drifted} == {
        "fields.zarr/mesh/face_family": "only in B",
        "tables.parquet/mesh_cell_families.parquet": "only in B",
        "manifest.json:artifacts (count)": "1 vs 2",
    }


def test_the_ugrid_node_axes_are_held_when_the_older_run_lacks_them(tmp_path):
    older = _run(tmp_path / "older", engine="regular", mesh_arrays=("face_x",))
    newer = _run(
        tmp_path / "newer", engine="regular", mesh_arrays=("face_x", "node_x", "node_y", "crs")
    )

    comparison = compare_run_dirs(older, newer)

    assert comparison.ok, [v.target for v in comparison.drifted]
    for target in sorted(UGRID_MEMBERS):
        (verdict,) = _verdicts(comparison, target)
        assert (verdict.within, verdict.detail) == (True, UGRID_DETAIL)


def test_a_new_crs_is_a_drift_when_the_older_run_has_the_node_axes(tmp_path):
    older = _run(tmp_path / "older", engine="regular", mesh_arrays=("node_x", "node_y"))
    newer = _run(tmp_path / "newer", engine="regular", mesh_arrays=("node_x", "node_y", "crs"))

    comparison = compare_run_dirs(older, newer)

    (verdict,) = _verdicts(comparison, "fields.zarr/mesh/crs")
    assert (verdict.within, verdict.detail) == (False, "only in B")
