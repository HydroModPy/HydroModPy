"""Tests for hmp init / hmp new scaffolding."""

from pathlib import Path

from hydromodpy.data.scaffold import (
    VARIABLES,
    create_project,
    scaffold,
)


class TestScaffold:
    def test_creates_structure(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy")

        assert root.exists()
        assert (root / "data").is_dir()
        assert (root / "projects").is_dir()
        assert (root / "hydrometry_custom").is_dir()
        assert (root / "piezometry_custom").is_dir()
        assert (root / "water_quality_custom").is_dir()
        assert (root / "dem_custom").is_dir()
        assert (root / "geology_custom").is_dir()

    def test_creates_readme_per_variable(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy")

        for spec in VARIABLES:
            readme = root / f"{spec.name}_custom" / "README.md"
            assert readme.exists(), f"Missing README for {spec.name}_custom"
            text = readme.read_text()
            assert spec.name in text

    def test_creates_locations_template_for_timeseries(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy")

        loc = root / "hydrometry_custom" / "example_locations.csv"
        assert loc.exists()
        content = loc.read_text()
        assert "id,x,y,crs,unit" in content

        assert (root / "piezometry_custom" / "example_locations.csv").exists()
        assert (root / "water_quality_custom" / "example_locations.csv").exists()

    def test_no_locations_for_raster_or_vector(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy")

        assert not (root / "dem_custom" / "example_locations.csv").exists()
        assert not (root / "geology_custom" / "example_locations.csv").exists()

    def test_creates_chronicle_example(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy")

        chronicles = root / "hydrometry_custom" / "chronicles"
        assert chronicles.is_dir()
        example = chronicles / "EXAMPLE.csv"
        assert example.exists()
        content = example.read_text()
        assert "datetime,value" in content

    def test_idempotent(self, tmp_path):
        """Running scaffold twice does not overwrite existing files."""
        root = scaffold(tmp_path / "hydromodpy")
        loc = root / "hydrometry_custom" / "example_locations.csv"

        loc.write_text("id,x,y,crs,unit\nST01,-1.5,48.0,EPSG:4326,m3/s\n")

        scaffold(tmp_path / "hydromodpy")

        assert "ST01" in loc.read_text()

    def test_default_path(self):
        from hydromodpy.data.scaffold import DEFAULT_ROOT

        assert DEFAULT_ROOT == Path.home() / "hydromodpy"


class TestCreateProject:
    def test_creates_project_structure(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy")
        project_dir = create_project(root, "my_project")

        assert project_dir.is_dir()
        assert (project_dir / "project.toml").exists()
        assert (project_dir / "run_demo.toml").exists()

    def test_project_toml_content(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy")
        project_dir = create_project(root, "canut")

        content = (project_dir / "project.toml").read_text()
        assert "canut" in content
        assert "[geographic]" in content
        assert "[domain]" in content
        assert "[flow]" in content

    def test_run_toml_content(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy")
        project_dir = create_project(root, "canut")

        content = (project_dir / "run_demo.toml").read_text()
        assert 'base_config = "project.toml"' in content
        assert "[simulation]" in content
        assert "[[simulation.process]]" in content

    def test_idempotent(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy")
        project_dir = create_project(root, "my_project")

        (project_dir / "project.toml").write_text("# custom\n")
        create_project(root, "my_project")

        assert (project_dir / "project.toml").read_text() == "# custom\n"

    def test_project_inside_projects_dir(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy")
        project_dir = create_project(root, "test_proj")

        assert project_dir.parent.name == "projects"
        assert project_dir.parent.parent == root
