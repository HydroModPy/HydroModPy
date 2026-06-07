"""Config validation tests for the hydrography variable manager.

Covers HydrographySourceConfig / HydrographyConfig validation, Profile
annotations, DataManagersConfig integration, TOML acceptance, documented
public surface, and the force_refresh field.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, get_args, get_origin

import pytest
from pydantic import BaseModel, ValidationError

from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.data.variables.hydrography.config import (
    HydrographyConfig,
    HydrographySourceConfig,
)

# =====================================================================
# 1. Config - HydrographySourceConfig
# =====================================================================


@pytest.mark.fast
class TestSourceConfigValidation:
    """All source types, defaults, constraints, extra=forbid."""

    # -- Custom --
    def test_custom_valid(self, tmp_path):
        cfg = HydrographySourceConfig(source="custom", path=tmp_path / "s.shp")
        assert cfg.source == "custom"
        assert cfg.path == tmp_path / "s.shp"
        assert cfg.rasterize_field == "FID"

    def test_custom_requires_path(self):
        with pytest.raises(ValidationError, match="path"):
            HydrographySourceConfig(source="custom")

    def test_custom_with_rasterize_field(self, tmp_path):
        cfg = HydrographySourceConfig(
            source="custom", path=tmp_path / "s.gpkg", rasterize_field="CODE"
        )
        assert cfg.rasterize_field == "CODE"

    # -- OSM --
    def test_osm_defaults(self):
        cfg = HydrographySourceConfig(source="osm")
        assert cfg.waterway_types == ["river", "stream"]
        assert cfg.path is None

    def test_osm_custom_waterways(self):
        cfg = HydrographySourceConfig(source="osm", waterway_types=["canal", "drain", "ditch"])
        assert cfg.waterway_types == ["canal", "drain", "ditch"]

    # -- BD Topage --
    def test_bdtopage_defaults(self):
        cfg = HydrographySourceConfig(source="bdtopage")
        assert cfg.typename == "sa:CoursEau_FXX_Topage2025"
        assert cfg.page_size == 2000

    def test_bdtopage_custom_typename(self):
        cfg = HydrographySourceConfig(
            source="bdtopage",
            typename="sa:CoursEau_FXX_Topage2019",
            page_size=500,
        )
        assert cfg.typename == "sa:CoursEau_FXX_Topage2019"
        assert cfg.page_size == 500

    # -- EU-Hydro --
    def test_euhydro_defaults(self):
        cfg = HydrographySourceConfig(source="euhydro")
        assert cfg.group_name == "River_Net_lines"
        assert cfg.euhydro_page_size == 1000

    def test_euhydro_custom_group(self):
        cfg = HydrographySourceConfig(
            source="euhydro", group_name="Canal_lines", euhydro_page_size=200
        )
        assert cfg.group_name == "Canal_lines"
        assert cfg.euhydro_page_size == 200

    # -- Rejection --
    def test_invalid_source_rejected(self):
        with pytest.raises(ValidationError):
            HydrographySourceConfig(source="nasa")

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError, match="Extra inputs"):
            HydrographySourceConfig(source="osm", magic_option=42)

    # -- Serialization round-trip --
    def test_model_dump_round_trip(self, tmp_path):
        cfg = HydrographySourceConfig(source="custom", path=tmp_path / "s.shp")
        dumped = cfg.model_dump(mode="python")
        restored = HydrographySourceConfig.model_validate(dumped)
        assert restored.source == cfg.source
        assert restored.path == cfg.path

    def test_json_round_trip(self, tmp_path):
        cfg = HydrographySourceConfig(source="custom", path=tmp_path / "s.shp")
        json_str = cfg.model_dump_json()
        restored = HydrographySourceConfig.model_validate_json(json_str)
        assert restored.source == "custom"


# =====================================================================
# 2. Config - Profile annotations
# =====================================================================


@pytest.mark.fast
class TestSourceConfigParamLevels:
    """Every field must carry a Profile annotation."""

    @staticmethod
    def _get_param_level(model_cls: type[BaseModel], field_name: str) -> str | None:
        info = model_cls.model_fields[field_name]
        for meta in info.metadata:
            if isinstance(meta, Profile):
                return meta.name.lower()
        return None

    @pytest.mark.parametrize(
        "field,expected_level",
        [
            ("source", "user"),
            ("path", "user"),
            ("rasterize_field", "user"),
            ("force_refresh", "dev"),
            ("typename", "dev"),
            ("page_size", "dev"),
            ("group_name", "dev"),
            ("euhydro_page_size", "dev"),
            ("waterway_types", "dev"),
        ],
    )
    def test_source_config_param_levels(self, field, expected_level):
        level = self._get_param_level(HydrographySourceConfig, field)
        assert level == expected_level, (
            f"Field '{field}' expected Profile('{expected_level}'), got '{level}'"
        )

    def test_config_sources_field_is_user(self):
        level = self._get_param_level(HydrographyConfig, "sources")
        assert level == "user"


# =====================================================================
# 3. Config - HydrographyConfig (container)
# =====================================================================


@pytest.mark.fast
class TestHydrographyConfigContainer:
    def test_single_source(self, tmp_path):
        cfg = HydrographyConfig(sources=[{"source": "custom", "path": str(tmp_path / "s.shp")}])
        assert len(cfg.sources) == 1

    def test_multi_source_all_types(self, tmp_path):
        cfg = HydrographyConfig(
            sources=[
                {"source": "custom", "path": str(tmp_path / "s.shp")},
                {"source": "osm"},
                {"source": "bdtopage"},
                {"source": "euhydro"},
            ]
        )
        assert len(cfg.sources) == 4
        assert [s.source for s in cfg.sources] == ["custom", "osm", "bdtopage", "euhydro"]

    def test_empty_sources_rejected(self):
        with pytest.raises(ValidationError):
            HydrographyConfig(sources=[])

    def test_extra_field_on_config_rejected(self, tmp_path):
        with pytest.raises(ValidationError):
            HydrographyConfig(
                sources=[{"source": "osm"}],
                unknown_key="x",
            )

    def test_config_extra_forbid(self):
        assert HydrographyConfig.model_config.get("extra") == "forbid"


# =====================================================================
# 4. DataManagersConfig integration
# =====================================================================


@pytest.mark.fast
class TestDataManagersConfigIntegration:
    def test_hydrography_field_is_typed(self):
        """The hydrography field on DataManagersConfig should be HydrographyConfig."""
        from hydromodpy.data.data_managers_config import DataManagersConfig

        info = DataManagersConfig.model_fields["hydrography"]
        # The annotation is Annotated[HydrographyConfig | None, ...]
        assert "HydrographyConfig" in str(info.annotation)

    def test_model_validate_with_hydrography(self, tmp_path):
        from hydromodpy.data.data_managers_config import DataManagersConfig

        payload = {
            "types": ["hydrography"],
            "hydrography": {
                "sources": [{"source": "bdtopage"}],
            },
        }
        cfg = DataManagersConfig.model_validate(payload)
        assert cfg.hydrography is not None
        assert isinstance(cfg.hydrography, HydrographyConfig)
        assert cfg.hydrography.sources[0].source == "bdtopage"

    def test_from_toml_section_accepts_relative_path(self, tmp_path):
        """Relative paths in nested source configs are kept as-is by the
        top-level resolver (only top-level Path fields are resolved).
        The Pydantic model still accepts the relative string."""
        from hydromodpy.data.data_managers_config import DataManagersConfig

        section = {
            "types": ["hydrography"],
            "hydrography": {
                "sources": [
                    {"source": "custom", "path": "relative/streams.shp"},
                ],
            },
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=tmp_path)
        assert cfg.hydrography is not None
        assert cfg.hydrography.sources[0].path is not None

    def test_hydrography_in_typed_sections(self):
        """HydrographyConfig is registered in _TYPED_SECTIONS dict."""
        from hydromodpy.data.data_managers_config import DataManagersConfig

        # from_toml_section validates hydrography as typed - just check it doesn't error
        section = {
            "types": ["hydrography"],
            "hydrography": {"sources": [{"source": "osm"}]},
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=Path("/tmp"))
        assert cfg.hydrography is not None

    def test_hydrography_not_in_types_but_section_present(self, tmp_path):
        """If hydrography is not in types but section is present, it should still validate."""
        from hydromodpy.data.data_managers_config import DataManagersConfig

        section = {
            "types": ["geology"],
            "hydrography": {"sources": [{"source": "osm"}]},
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=tmp_path)
        assert cfg.hydrography is not None
        assert "hydrography" not in cfg.types

    def test_with_resolved_types_adds_hydrography(self, tmp_path):
        from hydromodpy.data.data_managers_config import DataManagersConfig

        section = {
            "types": [],
            "hydrography": {"sources": [{"source": "osm"}]},
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=tmp_path)
        resolved = cfg.with_resolved_types(["hydrography"])
        assert "hydrography" in resolved.types


# =====================================================================
# 12. TOML format acceptance
# =====================================================================


@pytest.mark.fast
class TestTomlFormatAcceptance:
    """Verify various TOML layouts produce valid configs."""

    def test_minimal_custom(self, tmp_path):
        from hydromodpy.data.data_managers_config import DataManagersConfig

        section = {
            "types": ["hydrography"],
            "hydrography": {
                "sources": [{"source": "custom", "path": str(tmp_path / "s.shp")}],
            },
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=tmp_path)
        assert cfg.hydrography.sources[0].source == "custom"

    def test_minimal_osm(self):
        from hydromodpy.data.data_managers_config import DataManagersConfig

        section = {
            "types": ["hydrography"],
            "hydrography": {"sources": [{"source": "osm"}]},
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=Path("/tmp"))
        assert cfg.hydrography.sources[0].waterway_types == ["river", "stream"]

    def test_minimal_bdtopage(self):
        from hydromodpy.data.data_managers_config import DataManagersConfig

        section = {
            "types": ["hydrography"],
            "hydrography": {"sources": [{"source": "bdtopage"}]},
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=Path("/tmp"))
        assert cfg.hydrography.sources[0].typename == "sa:CoursEau_FXX_Topage2025"

    def test_minimal_euhydro(self):
        from hydromodpy.data.data_managers_config import DataManagersConfig

        section = {
            "types": ["hydrography"],
            "hydrography": {"sources": [{"source": "euhydro"}]},
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=Path("/tmp"))
        assert cfg.hydrography.sources[0].group_name == "River_Net_lines"

    def test_multi_source_toml(self, tmp_path):
        from hydromodpy.data.data_managers_config import DataManagersConfig

        section = {
            "types": ["hydrography"],
            "hydrography": {
                "sources": [
                    {"source": "custom", "path": str(tmp_path / "local.shp")},
                    {"source": "osm", "waterway_types": ["canal"]},
                    {
                        "source": "bdtopage",
                        "typename": "sa:CoursEau_FXX_Topage2019",
                        "page_size": 100,
                    },
                    {
                        "source": "euhydro",
                        "group_name": "River_Net_lines",
                        "euhydro_page_size": 500,
                    },
                ],
            },
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=tmp_path)
        assert len(cfg.hydrography.sources) == 4

    def test_invalid_source_in_toml(self):
        from hydromodpy.data.data_managers_config import DataManagersConfig

        section = {
            "types": ["hydrography"],
            "hydrography": {"sources": [{"source": "invalid_api"}]},
        }
        with pytest.raises((ValidationError, ValueError)):
            DataManagersConfig.from_toml_section(section, base_dir=Path("/tmp"))


# =====================================================================
# 13. Supported formats / internal data summary
# =====================================================================


@pytest.mark.fast
class TestDocumentedContracts:
    """Verify the documented public API surface."""

    def test_source_literals(self):
        """The four supported source types are exactly these."""
        info = HydrographySourceConfig.model_fields["source"]
        # Extract Literal args from Annotated
        for arg in get_args(info.annotation):
            if get_origin(arg) is Literal or hasattr(arg, "__args__"):
                literals = set(get_args(arg))
                if literals:
                    assert literals == {"custom", "osm", "bdtopage", "euhydro"}
                    return
        # Fallback: check via model_json_schema
        schema = HydrographySourceConfig.model_json_schema()
        source_enum = schema["properties"]["source"]["enum"]
        assert set(source_enum) == {"custom", "osm", "bdtopage", "euhydro"}

    def test_custom_vector_formats(self):
        """custom.py supports SHP, GPKG, GeoJSON."""
        from hydromodpy.data.variables.hydrography.custom import _VECTOR_EXTENSIONS

        assert "*.shp" in _VECTOR_EXTENSIONS
        assert "*.gpkg" in _VECTOR_EXTENSIONS
        assert "*.geojson" in _VECTOR_EXTENSIONS

    def test_config_is_not_dataclass(self):
        import dataclasses

        assert not dataclasses.is_dataclass(HydrographyConfig)

    def test_all_apis_return_epsg4326(self):
        """Documented contract: all API fetch() functions return EPSG:4326."""
        # This is verified in the individual API tests above; here we just
        # verify the modules are importable and have a fetch function.
        from hydromodpy.data.variables.hydrography.apis import bdtopage, euhydro, osm

        assert callable(osm.fetch)
        assert callable(bdtopage.fetch)
        assert callable(euhydro.fetch)

    def test_manager_variable_name(self):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        assert HydrographyManager.VARIABLE_NAME == "hydrography"

    def test_package_exports(self):
        import hydromodpy.data.variables.hydrography as pkg

        assert hasattr(pkg, "HydrographyConfig")
        assert hasattr(pkg, "HydrographySourceConfig")
        assert hasattr(pkg, "HydrographyManager")


# =====================================================================
# 19. Config - force_refresh field
# =====================================================================


@pytest.mark.fast
class TestForceRefreshConfig:
    def test_force_refresh_default_false(self):
        cfg = HydrographySourceConfig(source="osm")
        assert cfg.force_refresh is False

    def test_force_refresh_set_true(self):
        cfg = HydrographySourceConfig(source="osm", force_refresh=True)
        assert cfg.force_refresh is True

    def test_force_refresh_param_level_dev(self):
        info = HydrographySourceConfig.model_fields["force_refresh"]
        for meta in info.metadata:
            if isinstance(meta, Profile):
                assert meta == Profile.DEV
                return
        pytest.fail("force_refresh should have Profile.DEV")

    def test_force_refresh_in_model_dump(self):
        cfg = HydrographySourceConfig(source="osm", force_refresh=True)
        dumped = cfg.model_dump()
        assert dumped["force_refresh"] is True
