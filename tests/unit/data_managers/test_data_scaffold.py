"""Tests for the ``data/<variable>/`` scaffold layout created by workspace init."""

from __future__ import annotations

import pytest

from hydromodpy.data.common.io_helpers import is_scaffold_example
from hydromodpy.data.scaffold import VARIABLES, scaffold


@pytest.fixture(scope="module")
def ws(tmp_path_factory):
    return scaffold(tmp_path_factory.mktemp("hmp"))


def test_creates_one_folder_per_variable_under_data(ws):
    for spec in VARIABLES:
        var_dir = ws / "data" / spec.name
        assert var_dir.is_dir()
        assert (var_dir / "README.md").exists()


def test_no_custom_suffix_folders_at_root(ws):
    # The old `<variable>_custom/` root layout must be gone.
    assert list(ws.glob("*_custom")) == []


def test_readme_mentions_variable_and_commands(ws):
    text = (ws / "data" / "piezometry" / "README.md").read_text()
    assert "piezometry" in text
    assert "hmp data" in text


def test_point_examples_have_loc_and_chronicle(ws):
    hydro = ws / "data" / "hydrometry"
    assert (hydro / "hydrometry_custom_LOC.csv").exists()
    assert (hydro / "hydrometry_custom_EXAMPLE_20000101_20000131_D.csv").exists()


def test_water_quality_uses_filename_prefix_alias(ws):
    wq = ws / "data" / "water_quality"
    assert (wq / "waterquality_custom_LOC.csv").exists()


def test_geology_ships_one_example_per_format(ws):
    geo = ws / "data" / "geology"
    for ext in ("gpkg", "shp", "geojson", "tif", "csv"):
        assert (geo / f"geology_custom_EXAMPLE.{ext}").exists(), ext


def test_dem_ships_one_example_per_format(ws):
    dem = ws / "data" / "dem"
    for ext in ("tif", "asc", "nc"):
        assert (dem / f"dem_custom_EXAMPLE.{ext}").exists(), ext


def test_grid_examples_include_nc_and_tif(ws):
    pr = ws / "data" / "precipitation"
    assert (pr / "precipitation_custom_LOC.csv").exists()
    assert (pr / "precipitation_custom_EXAMPLE.nc").exists()
    assert (pr / "precipitation_custom_EXAMPLE.tif").exists()


def test_creates_projects_and_data_dirs(ws):
    assert (ws / "projects").is_dir()
    assert (ws / "data").is_dir()


def test_example_files_are_flagged_inert():
    assert is_scaffold_example("geology_custom_EXAMPLE.gpkg")
    assert is_scaffold_example("hydrometry_custom_EXAMPLE_20000101_20000131_D.csv")
    assert not is_scaffold_example("hydrometry_custom_P01_20200101_20200103_D.csv")
    assert not is_scaffold_example("hydrometry_hubeau_J001_20200101_20200103_D.csv")


def test_scaffold_is_idempotent_for_user_edits(tmp_path):
    root = scaffold(tmp_path / "hmp", with_examples=False)
    loc = root / "data" / "recharge" / "recharge_custom_LOC.csv"
    loc.write_text("id,x,y,crs,unit\nMYROW,1.0,2.0,EPSG:4326,mm/day\n")

    scaffold(tmp_path / "hmp", with_examples=False)

    assert "MYROW" in loc.read_text()
