"""Tests for hydrography Pydantic configuration."""

import pytest

from hydromodpy.data_managers.variables.hydrography.config import (
    HydrographyConfig,
    HydrographySourceConfig,
)


@pytest.mark.fast
class TestHydrographySourceConfig:
    def test_custom_requires_path(self):
        with pytest.raises(ValueError, match="path"):
            HydrographySourceConfig(source="custom")

    def test_custom_valid(self, tmp_path):
        cfg = HydrographySourceConfig(source="custom", path=tmp_path / "streams.shp")
        assert cfg.source == "custom"
        assert cfg.rasterize_field == "FID"

    def test_osm_valid(self):
        cfg = HydrographySourceConfig(source="osm")
        assert cfg.waterway_types == ["river", "stream"]

    def test_bdtopage_valid(self):
        cfg = HydrographySourceConfig(source="bdtopage")
        assert cfg.typename == "sa:CoursEau_FXX_Topage2025"
        assert cfg.page_size == 2000

    def test_euhydro_valid(self):
        cfg = HydrographySourceConfig(source="euhydro")
        assert cfg.group_name == "River_Net_lines"
        assert cfg.euhydro_page_size == 1000

    def test_invalid_source(self):
        with pytest.raises(ValueError):
            HydrographySourceConfig(source="unknown")

    def test_extra_field_forbidden(self):
        with pytest.raises(ValueError):
            HydrographySourceConfig(source="osm", bogus=True)


@pytest.mark.fast
class TestHydrographyConfig:
    def test_valid(self, tmp_path):
        cfg = HydrographyConfig(
            sources=[
                {"source": "custom", "path": str(tmp_path / "s.shp")},
            ]
        )
        assert len(cfg.sources) == 1

    def test_empty_sources_rejected(self):
        with pytest.raises(ValueError):
            HydrographyConfig(sources=[])

    def test_multi_source(self, tmp_path):
        cfg = HydrographyConfig(
            sources=[
                {"source": "custom", "path": str(tmp_path / "s.shp")},
                {"source": "osm"},
            ]
        )
        assert len(cfg.sources) == 2


@pytest.mark.fast
class TestHydrographyConfigInDataManagers:
    """Verify that HydrographyConfig integrates with DataManagersConfig."""

    def test_typed_config_round_trip(self, tmp_path):
        from hydromodpy.data_managers.data_managers_config import DataManagersConfig

        payload = {
            "types": ["hydrography"],
            "hydrography": {
                "sources": [
                    {"source": "custom", "path": str(tmp_path / "s.shp")},
                ],
            },
        }
        cfg = DataManagersConfig.model_validate(payload)
        assert cfg.hydrography is not None
        assert cfg.hydrography.sources[0].source == "custom"

    def test_from_toml_section(self, tmp_path):
        from hydromodpy.data_managers.data_managers_config import DataManagersConfig

        section = {
            "types": ["hydrography"],
            "hydrography": {
                "sources": [
                    {"source": "custom", "path": str(tmp_path / "s.shp")},
                ],
            },
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=tmp_path)
        assert cfg.hydrography is not None
