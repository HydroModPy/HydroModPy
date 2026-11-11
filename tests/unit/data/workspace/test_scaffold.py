"""The scaffold of a data workspace."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.data.common.io_helpers import is_scaffold_example
from hydromodpy.data.workspace.scaffold import (
    VARIABLES,
    create_project,
    scaffold,
)


class TestScaffold:
    @pytest.fixture(scope="class")
    def ws(self, tmp_path_factory):
        return scaffold(tmp_path_factory.mktemp("hmp"))

    def test_creates_structure(self, ws):
        assert ws.exists()
        assert (ws / "data").is_dir()
        assert (ws / "projects").is_dir()
        for name in (
            "hydrometry",
            "piezometry",
            "water_quality",
            "intermittency",
            "dem",
            "geology",
        ):
            assert (ws / "data" / name).is_dir()
        assert list(ws.glob("*_custom")) == []

    def test_creates_readme_per_variable(self, ws):
        for spec in VARIABLES:
            readme = ws / "data" / spec.name / "README.md"
            assert readme.exists(), f"Missing README for {spec.name}"
            assert spec.name in readme.read_text()

    def test_loc_template_for_point_and_grid(self, ws):
        loc = ws / "data" / "hydrometry" / "hydrometry_custom_LOC.csv"
        assert loc.exists()
        assert "id,x,y,crs,unit" in loc.read_text()

        assert (ws / "data" / "piezometry" / "piezometry_custom_LOC.csv").exists()
        assert (ws / "data" / "water_quality" / "waterquality_custom_LOC.csv").exists()
        assert (ws / "data" / "precipitation" / "precipitation_custom_LOC.csv").exists()

    def test_chronicle_example(self, ws):
        example = ws / "data" / "hydrometry" / "hydrometry_custom_EXAMPLE_20000101_20000131_D.csv"
        assert example.exists()
        assert "datetime,value" in example.read_text()

    def test_geology_example_per_format(self, ws):
        geo = ws / "data" / "geology"
        for ext in ("gpkg", "shp", "geojson", "tif", "csv"):
            assert (geo / f"geology_custom_EXAMPLE.{ext}").exists(), ext

    def test_example_project_and_projects_readme(self, ws):
        assert (ws / "projects" / "README.md").exists()
        example = ws / "projects" / "example"
        assert (example / "project.toml").exists()
        assert (example / "run_demo.toml").exists()

    def test_example_project_writes_the_edition_2_1(self, ws):
        import tomllib

        project = ws / "projects" / "example" / "project.toml"
        assert tomllib.loads(project.read_text(encoding="utf-8"))["edition"] == "2.1"

    def test_idempotent(self, tmp_path):
        """Running scaffold twice does not overwrite existing files."""
        root = scaffold(tmp_path / "hmp")
        loc = root / "data" / "hydrometry" / "hydrometry_custom_LOC.csv"

        loc.write_text("id,x,y,crs,unit\nST01,-1.5,48.0,EPSG:4326,m3/s\n")

        scaffold(tmp_path / "hmp")

        assert "ST01" in loc.read_text()

    def test_default_path(self):
        from hydromodpy.data.workspace.scaffold import DEFAULT_ROOT

        assert DEFAULT_ROOT == Path.home() / "hydromodpy"


class TestCreateProject:
    def test_creates_project_structure(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy", with_examples=False)
        project_dir = create_project(root, "my_project")

        assert project_dir.is_dir()
        assert (project_dir / "project.toml").exists()
        assert (project_dir / "run_demo.toml").exists()

    def test_creates_the_folders_of_the_files_the_project_keeps(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy", with_examples=False)
        project_dir = create_project(root, "my_project")

        assert (project_dir / "inputs").is_dir()
        assert (project_dir / "configs").is_dir()

    def test_the_example_project_has_its_folders(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy")

        example = root / "projects" / "example"
        assert (example / "inputs").is_dir()
        assert (example / "configs").is_dir()

    @pytest.mark.parametrize(
        ("name", "said"),
        [
            ("My Project", "Write 'my_project'"),
            ("Canut", "Write 'canut'"),
            ("a" * 41, "41 characters"),
            ("con", "Windows reserves"),
            ("COM1", "is refused"),
            ("nul", "Windows reserves"),
            ("", "cannot be empty"),
            ("a/b", "is refused"),
            ("é", "is refused"),
        ],
    )
    def test_a_name_that_breaks_the_rule_is_refused_and_creates_nothing(self, tmp_path, name, said):
        from hydromodpy.core.exceptions import ConfigError

        root = scaffold(tmp_path / "hydromodpy", with_examples=False)

        with pytest.raises(ConfigError, match=said):
            create_project(root, name)

        assert [path.name for path in (root / "projects").iterdir()] == ["README.md"]

    @pytest.mark.parametrize("name", ["canut", "a" * 40, "k_1-b", "com10", "console"])
    def test_a_name_that_follows_the_rule_is_taken(self, tmp_path, name):
        root = scaffold(tmp_path / "hydromodpy", with_examples=False)

        assert create_project(root, name).name == name

    def test_project_toml_content(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy", with_examples=False)
        project_dir = create_project(root, "canut")

        content = (project_dir / "project.toml").read_text()
        assert "canut" in content
        assert "[geographic]" in content
        assert "[domain]" in content
        assert "[flow]" in content

    def test_run_toml_content(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy", with_examples=False)
        project_dir = create_project(root, "canut")

        content = (project_dir / "run_demo.toml").read_text()
        assert 'base_config = "project.toml"' in content
        assert "[simulation]" in content
        assert "[[simulation.process]]" in content

    def test_idempotent(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy", with_examples=False)
        project_dir = create_project(root, "my_project")

        (project_dir / "project.toml").write_text("# custom\n")
        create_project(root, "my_project")

        assert (project_dir / "project.toml").read_text() == "# custom\n"

    def test_project_inside_projects_dir(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy", with_examples=False)
        project_dir = create_project(root, "test_proj")

        assert project_dir.parent.name == "projects"
        assert project_dir.parent.parent == root


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


def test_creates_example_project_and_projects_readme(ws):
    assert (ws / "projects" / "README.md").exists()
    example = ws / "projects" / "example"
    assert (example / "project.toml").exists()
    assert (example / "run_demo.toml").exists()


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
