"""Tests for the drag-and-drop auto_scan module."""

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


def _write_hydro_file(root: Path, station_id: str, crs: str = "EPSG:2154") -> Path:
    loc = root / "hydrometry_custom" / "example_locations.csv"
    loc.write_text(
        f"id,x,y,crs,unit\n{station_id},350000.0,6780000.0,{crs},m3/s\n",
        encoding="utf-8",
    )
    chronicle = root / "hydrometry_custom" / "chronicles" / f"{station_id}.csv"
    return _drop(
        chronicle,
        "datetime,value\n2020-01-01,1.0\n2020-01-02,1.1\n2020-01-03,1.2\n",
    )


def test_scan_empty_workspace_reports_no_changes(tmp_path):
    root = scaffold(tmp_path / "ws")
    report = scan_custom(root)
    assert report.added == []
    assert report.updated == []
    assert report.errors == []


def test_scan_detects_new_timeseries_file(tmp_path):
    root = scaffold(tmp_path / "ws")
    chronicle = _write_hydro_file(root, "P01")

    report = scan_custom(root)

    assert len(report.added) == 1
    added = report.added[0]
    assert added.variable == "hydrometry"
    assert added.station_id == "P01"
    assert added.source_path == chronicle
    assert added.pivot_path.exists()


def test_scan_is_idempotent_on_unmodified_files(tmp_path):
    root = scaffold(tmp_path / "ws")
    _write_hydro_file(root, "P01")

    scan_custom(root)
    report = scan_custom(root)

    assert report.added == []
    assert len(report.skipped) >= 1


def test_scan_detects_modified_file(tmp_path):
    root = scaffold(tmp_path / "ws")
    path = _write_hydro_file(root, "P02")
    scan_custom(root)

    # bump mtime explicitly
    new_mtime = path.stat().st_mtime + 10
    os.utime(path, (new_mtime, new_mtime))

    report = scan_custom(root)
    assert len(report.updated) == 1
    assert report.updated[0].station_id == "P02"


def test_scan_reports_schema_errors(tmp_path):
    root = scaffold(tmp_path / "ws")
    _drop(
        root / "hydrometry_custom" / "chronicles" / "BAD.csv",
        "datetime,value\n2020-13-01,1.0\nbad,2.0\n",
    )
    report = scan_custom(root)
    assert any("BAD.csv" in str(p) for p, _ in report.errors)


def test_scan_skips_example_file(tmp_path):
    root = scaffold(tmp_path / "ws")
    # EXAMPLE.csv is shipped by default — scan must not ingest it
    report = scan_custom(root)
    assert all("EXAMPLE.csv" not in str(a.source_path) for a in report.added)


def test_check_custom_surfaces_all_errors(tmp_path):
    root = scaffold(tmp_path / "ws")
    _drop(
        root / "hydrometry_custom" / "chronicles" / "BAD.csv",
        "datetime,value\nfoo,bar\nbaz,qux\n",
    )
    issues = check_custom(root)
    assert len(issues) >= 2


def test_check_custom_variable_filter(tmp_path):
    root = scaffold(tmp_path / "ws")
    _drop(
        root / "hydrometry_custom" / "chronicles" / "BAD.csv",
        "datetime,value\nfoo,bar\n",
    )
    _drop(
        root / "piezometry_custom" / "chronicles" / "BAD.csv",
        "datetime,value\nfoo,bar\n",
    )
    hydro_issues = check_custom(root, variable="hydrometry")
    assert all("hydrometry_custom" in str(p) for p, _ in hydro_issues)


def test_scan_handles_missing_workspace(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan_custom(tmp_path / "missing_ws")
