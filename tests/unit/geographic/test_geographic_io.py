from __future__ import annotations

from pathlib import Path

import pytest
from pyproj import CRS

from hydromodpy.spatial.geographic import geographic_io


def test_ensure_crs_for_shapefile_writes_prj_without_rewriting_vector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shp_path = tmp_path / "domain.shp"
    shp_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        geographic_io.gpd,
        "read_file",
        lambda *_args, **_kwargs: pytest.fail("shapefile should not be reopened"),
    )

    geographic_io.ensure_crs(shp_path, "EPSG:2154")

    expected_wkt = CRS.from_user_input("EPSG:2154").to_wkt(version="WKT1_ESRI")
    assert shp_path.with_suffix(".prj").read_text(encoding="utf-8") == expected_wkt


def test_ensure_crs_for_missing_shapefile_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Shapefile not found"):
        geographic_io.ensure_crs(tmp_path / "missing.shp", "EPSG:2154")
