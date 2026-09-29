"""auto_scan never reads a provenance sidecar as a data file.

``geology_custom_X.gpkg.json`` is the sidecar of ``geology_custom_X.gpkg``. It
was skipped only while the GeoPackage existed; once the GeoPackage was gone,
the scan opened the sidecar as a GeoJSON vector and logged a DataSourceError.

Git ignores the sidecars HydroModPy writes, so a data file a commit removes
leaves its sidecar in every clone, and every run warned about it. An orphan
that holds nothing but what the file gives back is now removed; one that holds
a licence or a note someone declared is kept and reported.
"""

from __future__ import annotations

import logging
from pathlib import Path

from hydromodpy.data.provenance.sidecars import Sidecar, sidecar_path_for, write_sidecar
from hydromodpy.data.workspace.custom_scan import check_custom, scan_custom
from hydromodpy.data.workspace.scaffold import scaffold


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
