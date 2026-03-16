"""Tests for hmp init / hmp new scaffolding."""

from pathlib import Path

from hydromodpy.data_managers.scaffold import scaffold, create_project


class TestScaffold:

    def test_creates_structure(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy")

        assert root.exists()
        assert (root / "data" / "hydrometry").is_dir()
        assert (root / "data" / "piezometry").is_dir()
        assert (root / "data" / "water_quality").is_dir()
        assert (root / "projects").is_dir()

    def test_creates_loc_templates(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy")

        loc = root / "data" / "hydrometry" / "hydrometry_custom_LOC.csv"
        assert loc.exists()
        content = loc.read_text()
        assert "id,x,y,crs" in content

        assert (root / "data" / "piezometry" / "piezometry_custom_LOC.csv").exists()
        assert (root / "data" / "water_quality" / "waterquality_custom_LOC.csv").exists()

    def test_creates_chronicle_examples(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy")

        example = root / "data" / "hydrometry" / "hydrometry_custom_EXAMPLE_20200101_20201231_D.csv"
        assert example.exists()
        content = example.read_text()
        assert "datetime,value" in content
        assert "Renommer" in content

    def test_idempotent(self, tmp_path):
        """Running scaffold twice does not overwrite existing files."""
        root = scaffold(tmp_path / "hydromodpy")
        loc = root / "data" / "hydrometry" / "hydrometry_custom_LOC.csv"

        loc.write_text("id,x,y,crs\nST01,-1.5,48.0,EPSG:4326\n")

        scaffold(tmp_path / "hydromodpy")

        assert "ST01" in loc.read_text()

    def test_default_path(self):
        from hydromodpy.data_managers.scaffold import DEFAULT_ROOT
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
