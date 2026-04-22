"""Tests for the drag-and-drop scaffold layout created by `hmp init`."""

from __future__ import annotations

from hydromodpy.data.scaffold import VARIABLES, scaffold


def test_scaffold_creates_custom_folders(tmp_path):
    root = scaffold(tmp_path / "hydromodpy")

    for spec in VARIABLES:
        var_dir = root / f"{spec.name}_custom"
        assert var_dir.is_dir()
        assert (var_dir / "README.md").exists()


def test_readme_mentions_variable(tmp_path):
    root = scaffold(tmp_path / "hydromodpy")
    text = (root / "piezometry_custom" / "README.md").read_text()
    assert "piezometry" in text
    assert "hmp data" in text


def test_timeseries_scaffold_has_locations_and_chronicles(tmp_path):
    root = scaffold(tmp_path / "hydromodpy")

    ts = root / "hydrometry_custom"
    assert (ts / "example_locations.csv").exists()
    assert (ts / "chronicles").is_dir()
    assert (ts / "chronicles" / "EXAMPLE.csv").exists()


def test_raster_scaffold_has_no_chronicles(tmp_path):
    root = scaffold(tmp_path / "hydromodpy")

    dem = root / "dem_custom"
    assert (dem / "README.md").exists()
    assert not (dem / "example_locations.csv").exists()
    assert not (dem / "chronicles").exists()


def test_vector_scaffold_has_no_chronicles(tmp_path):
    root = scaffold(tmp_path / "hydromodpy")

    geo = root / "geology_custom"
    assert (geo / "README.md").exists()
    assert not (geo / "example_locations.csv").exists()


def test_scaffold_creates_projects_and_data_dirs(tmp_path):
    root = scaffold(tmp_path / "hydromodpy")
    assert (root / "projects").is_dir()
    assert (root / "data").is_dir()


def test_scaffold_is_idempotent_for_user_edits(tmp_path):
    root = scaffold(tmp_path / "hydromodpy")
    loc = root / "recharge_custom" / "example_locations.csv"
    loc.write_text("id,x,y,crs,unit\nMYROW,1.0,2.0,EPSG:4326,mm/day\n")

    scaffold(tmp_path / "hydromodpy")

    assert "MYROW" in loc.read_text()
