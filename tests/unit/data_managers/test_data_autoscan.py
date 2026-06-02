"""Tests for the auto_scan module (scans ``data/<variable>/`` for custom files)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hydromodpy.data.auto_scan import check_custom, scan_custom
from hydromodpy.data.scaffold import scaffold


def _drop(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _chronicle(root: Path, variable: str, station_id: str) -> Path:
    return root / "data" / variable / f"{variable}_custom_{station_id}_20200101_20200103_D.csv"


def _write_hydro_file(root: Path, station_id: str, crs: str = "EPSG:2154") -> Path:
    var_dir = root / "data" / "hydrometry"
    var_dir.mkdir(parents=True, exist_ok=True)
    (var_dir / "hydrometry_custom_LOC.csv").write_text(
        f"id,x,y,crs,unit\n{station_id},350000.0,6780000.0,{crs},m3/s\n",
        encoding="utf-8",
    )
    return _drop(
        _chronicle(root, "hydrometry", station_id),
        "datetime,value\n2020-01-01,1.0\n2020-01-02,1.1\n2020-01-03,1.2\n",
    )


def test_scan_empty_workspace_reports_no_changes(tmp_path):
    root = scaffold(tmp_path / "ws", with_examples=False)
    report = scan_custom(root)
    assert report.added == []
    assert report.updated == []
    assert report.errors == []


def test_scan_detects_new_timeseries_file(tmp_path):
    root = scaffold(tmp_path / "ws", with_examples=False)
    chronicle = _write_hydro_file(root, "P01")

    report = scan_custom(root)

    assert len(report.added) == 1
    added = report.added[0]
    assert added.variable == "hydrometry"
    assert added.station_id == "P01"
    assert added.source_path == chronicle
    assert added.pivot_path.exists()


def test_scan_is_idempotent_on_unmodified_files(tmp_path):
    root = scaffold(tmp_path / "ws", with_examples=False)
    _write_hydro_file(root, "P01")

    scan_custom(root)
    report = scan_custom(root)

    assert report.added == []
    assert len(report.skipped) >= 1


def test_scan_detects_modified_file(tmp_path):
    root = scaffold(tmp_path / "ws", with_examples=False)
    path = _write_hydro_file(root, "P02")
    scan_custom(root)

    # bump mtime explicitly
    new_mtime = path.stat().st_mtime + 10
    os.utime(path, (new_mtime, new_mtime))

    report = scan_custom(root)
    assert len(report.updated) == 1
    assert report.updated[0].station_id == "P02"


def test_scan_reports_schema_errors(tmp_path):
    root = scaffold(tmp_path / "ws", with_examples=False)
    _drop(
        _chronicle(root, "hydrometry", "BAD"),
        "datetime,value\n2020-13-01,1.0\nbad,2.0\n",
    )
    report = scan_custom(root)
    assert any("_custom_BAD_" in str(p) for p, _ in report.errors)


def test_scan_skips_shipped_example_files(tmp_path):
    # A full scaffold ships EXAMPLE templates in every folder: scan must not
    # ingest any of them.
    root = scaffold(tmp_path / "ws")
    report = scan_custom(root)
    assert report.added == []
    assert all("EXAMPLE" not in str(a.source_path) for a in report.added)


def test_check_custom_surfaces_all_errors(tmp_path):
    root = scaffold(tmp_path / "ws", with_examples=False)
    _drop(
        _chronicle(root, "hydrometry", "BAD"),
        "datetime,value\nfoo,bar\nbaz,qux\n",
    )
    issues = check_custom(root)
    assert len(issues) >= 2


def test_check_custom_variable_filter(tmp_path):
    root = scaffold(tmp_path / "ws", with_examples=False)
    _drop(_chronicle(root, "hydrometry", "BAD"), "datetime,value\nfoo,bar\n")
    _drop(_chronicle(root, "piezometry", "BAD"), "datetime,value\nfoo,bar\n")
    hydro_issues = check_custom(root, variable="hydrometry")
    assert hydro_issues
    assert all("hydrometry" in str(p) for p, _ in hydro_issues)


def test_scan_handles_missing_workspace(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan_custom(tmp_path / "missing_ws")
