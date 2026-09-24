"""auto_scan never reads a provenance sidecar as a data file.

``geology_custom_X.gpkg.json`` is the sidecar of ``geology_custom_X.gpkg``. It
was skipped only while the GeoPackage existed; once the GeoPackage was gone,
the scan opened the sidecar as a GeoJSON vector and logged a DataSourceError.
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


def test_an_orphan_sidecar_is_not_read_as_data(tmp_path: Path) -> None:
    root, geology = _geology_dir(tmp_path)
    orphan = _orphan(geology)

    report = scan_custom(root)

    assert report.errors == []
    assert report.added == []
    assert report.orphan_sidecars == [orphan]


def test_an_orphan_sidecar_is_reported_naming_its_missing_file(tmp_path: Path, caplog) -> None:
    root, geology = _geology_dir(tmp_path)
    _orphan(geology)

    with caplog.at_level(logging.WARNING):
        scan_custom(root)

    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(messages) == 1
    assert "geology_custom_X.gpkg is missing" in messages[0]
    assert "DataSourceError" not in messages[0]


def test_the_scan_summary_lists_the_orphan(tmp_path: Path) -> None:
    root, geology = _geology_dir(tmp_path)
    orphan = _orphan(geology)

    summary = scan_custom(root).format_summary()

    assert "Orphans :   1" in summary
    assert str(orphan) in summary


def test_check_custom_reports_the_orphan(tmp_path: Path) -> None:
    root, geology = _geology_dir(tmp_path)
    orphan = _orphan(geology)

    issues = check_custom(root, variable="geology")

    assert [path for path, _ in issues] == [orphan]
    assert "geology_custom_X.gpkg is missing" in issues[0][1]


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
