"""The scaffold of a data workspace."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.data.workspace.scaffold import (
    create_project,
    scaffold,
)


class TestScaffold:
    @pytest.fixture(scope="class")
    def ws(self, tmp_path_factory):
        return scaffold(tmp_path_factory.mktemp("hmp"))

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

    def test_a_folder_too_long_for_windows_is_refused_and_creates_nothing(
        self, tmp_path, monkeypatch
    ):
        from hydromodpy.core.exceptions import ConfigError
        from hydromodpy.core.io import filesystem
        from tests._helpers.windows_os import WindowsOs

        root = scaffold(tmp_path / ("w" * 90), with_examples=False)
        monkeypatch.setattr(filesystem, "os", WindowsOs())

        with pytest.raises(ConfigError, match="may hold 99 characters at most"):
            create_project(root, "my_project")

        assert [path.name for path in (root / "projects").iterdir()] == ["README.md"]

    def test_idempotent(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy", with_examples=False)
        project_dir = create_project(root, "my_project")

        (project_dir / "project.toml").write_text("# custom\n")
        create_project(root, "my_project")

        assert (project_dir / "project.toml").read_text() == "# custom\n"


@pytest.fixture(scope="module")
def ws(tmp_path_factory):
    return scaffold(tmp_path_factory.mktemp("hmp"))


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


def test_scaffold_is_idempotent_for_user_edits(tmp_path):
    root = scaffold(tmp_path / "hmp", with_examples=False)
    loc = root / "data" / "recharge" / "recharge_custom_LOC.csv"
    loc.write_text("id,x,y,crs,unit\nMYROW,1.0,2.0,EPSG:4326,mm/day\n")

    scaffold(tmp_path / "hmp", with_examples=False)

    assert "MYROW" in loc.read_text()
