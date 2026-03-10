"""Tests for hmp init scaffolding."""

from pathlib import Path

from hydromodpy.data_managers.scaffold import scaffold


class TestScaffold:

    def test_creates_structure(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy")

        assert root.exists()
        assert (root / "data" / "hydrometry").is_dir()
        assert (root / "data" / "piezometry").is_dir()
        assert (root / "data" / "water_quality").is_dir()
        assert (root / "bv_example").is_dir()
        assert (root / "bv_example" / "data_managers.toml").exists()

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

    def test_bv_toml_points_to_data(self, tmp_path):
        root = scaffold(tmp_path / "hydromodpy")
        toml_content = (root / "bv_example" / "data_managers.toml").read_text()
        data_path = str(root / "data")
        assert data_path in toml_content

    def test_bv_toml_is_valid(self, tmp_path):
        """BV TOML must parse and validate against Pydantic configs."""
        root = scaffold(tmp_path / "hydromodpy")
        toml_path = root / "bv_example" / "data_managers.toml"

        from hydromodpy.data_managers.hydrometry.config import HydrometryConfig
        from hydromodpy.data_managers.piezometry.config import PiezometryConfig
        from hydromodpy.data_managers.water_quality.config import WaterQualityConfig

        h = HydrometryConfig.from_toml(toml_path)
        p = PiezometryConfig.from_toml(toml_path)
        w = WaterQualityConfig.from_toml(toml_path)

        assert h.sources[0].source == "custom"
        assert str(root / "data") in str(h.sources[0].path)
        assert p.sources[0].source == "custom"
        assert w.sources[0].source == "custom"

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
