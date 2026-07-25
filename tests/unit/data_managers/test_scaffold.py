"""Tests for workspace and project scaffolding."""

from pathlib import Path

import pytest

from hydromodpy.data.scaffold import (
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

    def test_idempotent(self, tmp_path):
        """Running scaffold twice does not overwrite existing files."""
        root = scaffold(tmp_path / "hmp")
        loc = root / "data" / "hydrometry" / "hydrometry_custom_LOC.csv"

        loc.write_text("id,x,y,crs,unit\nST01,-1.5,48.0,EPSG:4326,m3/s\n")

        scaffold(tmp_path / "hmp")

        assert "ST01" in loc.read_text()

    def test_default_path(self):
        from hydromodpy.data.scaffold import DEFAULT_ROOT

        assert DEFAULT_ROOT == Path.home() / "hydromodpy"


class TestCreateProject:
    def test_creates_project_structure(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy", with_examples=False)
        project_dir = create_project(root, "my_project")

        assert project_dir.is_dir()
        assert (project_dir / "project.toml").exists()
        assert (project_dir / "run_demo.toml").exists()

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
