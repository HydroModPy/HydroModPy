"""The scan of the custom files of a workspace, and the sidecars it writes."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from hydromodpy.data.provenance.sidecars import Sidecar, sidecar_path_for, write_sidecar
from hydromodpy.data.workspace.custom_scan import check_custom, scan_custom
from hydromodpy.data.workspace.scaffold import scaffold


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


def test_scan_reports_a_converter_that_fails_unexpectedly(tmp_path, monkeypatch):
    from hydromodpy.data.workspace import custom_scan

    def explode(src, dest):
        raise RuntimeError("disk full")

    monkeypatch.setattr(custom_scan, "convert_timeseries_csv_to_parquet", explode)
    root = scaffold(tmp_path / "ws", with_examples=False)
    _write_hydro_file(root, "S1")
    report = scan_custom(root)
    assert any("RuntimeError: disk full" in message for _, message in report.errors)


def _geology_dir(tmp_path: Path) -> tuple[Path, Path]:
    root = scaffold(tmp_path / "ws", with_examples=False)
    return root, root / "data" / "geology"


def _write_vector(path: Path) -> Path:
    import geopandas as gpd
    from shapely.geometry import box

    gdf = gpd.GeoDataFrame({"CODE": ["A"]}, geometry=[box(0, 0, 10, 10)], crs="EPSG:2154")
    driver = "GeoJSON" if path.suffix == ".json" else "GPKG"
    gdf.to_file(str(path), driver=driver)
    return path


def _orphan(geology: Path, data_name: str = "geology_custom_X.gpkg") -> Path:
    return write_sidecar(geology / data_name, Sidecar(source="custom", sha256="abc"))


def _declared_orphan(geology: Path, data_name: str = "geology_custom_X.gpkg") -> Path:
    sidecar = Sidecar(source="custom", sha256="abc", license="etalab-2.0")
    return write_sidecar(geology / data_name, sidecar)


def test_an_orphan_sidecar_is_not_read_as_data(tmp_path: Path) -> None:
    root, geology = _geology_dir(tmp_path)
    _orphan(geology)

    report = scan_custom(root)

    assert report.errors == []
    assert report.added == []


def test_an_orphan_holding_only_a_hash_is_removed_without_a_warning(tmp_path: Path, caplog) -> None:
    root, geology = _geology_dir(tmp_path)
    orphan = _orphan(geology)

    with caplog.at_level(logging.WARNING):
        report = scan_custom(root)

    assert report.removed_sidecars == [orphan]
    assert report.orphan_sidecars == []
    assert not orphan.exists()
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert scan_custom(root).removed_sidecars == []


def test_an_orphan_with_an_undetermined_licence_is_removed(tmp_path: Path) -> None:
    root, geology = _geology_dir(tmp_path)
    sidecar = Sidecar(source="custom", sha256="abc", license="LicenseRef-undetermined")
    orphan = write_sidecar(geology / "geology_custom_X.gpkg", sidecar)

    assert scan_custom(root).removed_sidecars == [orphan]


def test_an_orphan_with_a_note_is_kept(tmp_path: Path) -> None:
    root, geology = _geology_dir(tmp_path)
    sidecar = Sidecar(source="custom", sha256="abc", notes="digitized by hand")
    orphan = write_sidecar(geology / "geology_custom_X.gpkg", sidecar)

    report = scan_custom(root)

    assert report.orphan_sidecars == [orphan]
    assert orphan.is_file()


def test_an_unreadable_orphan_is_kept(tmp_path: Path) -> None:
    root, geology = _geology_dir(tmp_path)
    orphan = geology / "geology_custom_X.gpkg.json"
    orphan.write_text("{not json", encoding="utf-8")

    report = scan_custom(root)

    assert report.orphan_sidecars == [orphan]
    assert orphan.is_file()


def test_a_declared_orphan_is_kept_and_reported_naming_its_missing_file(
    tmp_path: Path, caplog
) -> None:
    root, geology = _geology_dir(tmp_path)
    orphan = _declared_orphan(geology)

    with caplog.at_level(logging.WARNING):
        scan_custom(root)

    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(messages) == 1
    assert "geology_custom_X.gpkg is missing" in messages[0]
    assert "DataSourceError" not in messages[0]
    assert orphan.is_file()


def test_the_scan_summary_lists_the_kept_and_the_removed_orphans(tmp_path: Path) -> None:
    root, geology = _geology_dir(tmp_path)
    kept = _declared_orphan(geology)
    removed = _orphan(geology, "geology_custom_Z.gpkg")

    summary = scan_custom(root).format_summary()

    assert "Orphans :   1" in summary
    assert "Removed :   1" in summary
    assert str(kept) in summary
    assert str(removed) in summary


def test_check_custom_reports_the_orphans_and_removes_none(tmp_path: Path) -> None:
    root, geology = _geology_dir(tmp_path)
    kept = _declared_orphan(geology)
    bare = _orphan(geology, "geology_custom_Z.gpkg")

    issues = dict(check_custom(root, variable="geology"))

    assert sorted(issues) == sorted([kept, bare])
    assert "geology_custom_X.gpkg is missing" in issues[kept]
    assert "Restore the data file" in issues[kept]
    assert "The next scan removes it" in issues[bare]
    assert kept.is_file()
    assert bare.is_file()


def test_a_sidecar_next_to_its_file_is_skipped_and_the_file_is_scanned(tmp_path: Path) -> None:
    root, geology = _geology_dir(tmp_path)
    data = _write_vector(geology / "geology_custom_X.gpkg")
    write_sidecar(data, Sidecar(source="custom", sha256="abc"))

    report = scan_custom(root)

    assert report.errors == []
    assert report.orphan_sidecars == []
    assert [a.source_path for a in report.added] == [data]
    assert sidecar_path_for(data).is_file()


def test_a_geojson_named_dot_json_is_still_data(tmp_path: Path) -> None:
    root, geology = _geology_dir(tmp_path)
    data = _write_vector(geology / "geology_custom_Y.json")

    report = scan_custom(root)

    assert report.errors == []
    assert report.orphan_sidecars == []
    assert [a.source_path for a in report.added] == [data]
