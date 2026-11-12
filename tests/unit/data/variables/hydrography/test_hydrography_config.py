"""Config validation tests for the hydrography variable.

Covers HydrographySourceConfig / HydrographyConfig validation, Profile
annotations, DataConfig integration, TOML acceptance, documented
public surface, and the force_refresh field.
"""

from __future__ import annotations

from pathlib import Path

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

    def test_custom_requires_path(self):
        with pytest.raises(ValidationError, match="path"):
            HydrographySourceConfig(source="file")

    # -- OSM --

    # -- BD Topage --

    # -- EU-Hydro --

    # -- Rejection --
    def test_invalid_source_rejected(self):
        with pytest.raises(ValidationError):
            HydrographySourceConfig(source="nasa")

    # -- Serialization round-trip --


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
            ("force_refresh", "user"),
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
    def test_config_extra_forbid(self):
        assert HydrographyConfig.model_config.get("extra") == "forbid"


# =====================================================================
# 4. DataConfig integration
# =====================================================================


@pytest.mark.fast
class TestDataConfigIntegration:
    def test_hydrography_field_is_typed(self):
        """The hydrography field on DataConfig should be HydrographyConfig."""
        from hydromodpy.data.loading.config_schema import DataConfig

        info = DataConfig.model_fields["hydrography"]
        # The annotation is Annotated[HydrographyConfig | None, ...]
        assert "HydrographyConfig" in str(info.annotation)

    def test_hydrography_not_in_types_but_section_present(self, tmp_path):
        """If hydrography is not in types but section is present, it should still validate."""
        from hydromodpy.data.loading.config_schema import DataConfig

        section = {
            "types": ["geology"],
            "hydrography": {"sources": [{"source": "osm"}]},
        }
        cfg = DataConfig.from_toml_section(section, base_dir=tmp_path)
        assert cfg.hydrography is not None
        assert "hydrography" not in cfg.types


# =====================================================================
# 12. TOML format acceptance
# =====================================================================


@pytest.mark.fast
class TestTomlFormatAcceptance:
    """Verify various TOML layouts produce valid configs."""

    def test_invalid_source_in_toml(self):
        from hydromodpy.data.loading.config_schema import DataConfig

        section = {
            "types": ["hydrography"],
            "hydrography": {"sources": [{"source": "invalid_api"}]},
        }
        with pytest.raises((ValidationError, ValueError)):
            DataConfig.from_toml_section(section, base_dir=Path("/tmp"))


# =====================================================================
# 13. Supported formats / internal data summary
# =====================================================================


@pytest.mark.fast
class TestDocumentedContracts:
    """Verify the documented public API surface."""

    def test_a_source_serving_another_payload_kind_is_refused_by_the_document(
        self, isolated_registry
    ):
        """A gauge source resolves, and it is not a river network.

        Validating only that the name resolves would let it through here and
        refuse it inside the fetch, after a provider had been contacted.
        """
        from typing import ClassVar

        class AcmeGaugeSource:
            source_id: ClassVar[str] = "acme-gauge"
            section: ClassVar[str] = "hydrography"
            payload_kind: ClassVar[str] = "points"
            extent_crs: ClassVar[str] = "EPSG:4326"
            selectors: ClassVar[tuple[str, ...]] = ("extent",)
            period_need: ClassVar[str] = "required"
            hosts: ClassVar[tuple[str, ...]] = ()
            writes_out_dir: ClassVar[bool] = False

            def __init__(self) -> None:
                self.variables = ("gauge_level",)

            def fetch(self, request):  # pragma: no cover - never fetched here
                raise AssertionError("resolved, never run")

        isolated_registry.register(AcmeGaugeSource)
        with pytest.raises(ValidationError, match="features"):
            HydrographySourceConfig(source="acme-gauge")

    def test_custom_vector_formats(self):
        """custom.py supports SHP, GPKG, GeoJSON."""
        from hydromodpy.data.variables.hydrography.custom import _VECTOR_EXTENSIONS

        assert "*.shp" in _VECTOR_EXTENSIONS
        assert "*.gpkg" in _VECTOR_EXTENSIONS
        assert "*.geojson" in _VECTOR_EXTENSIONS

    def test_config_is_not_dataclass(self):
        import dataclasses

        assert not dataclasses.is_dataclass(HydrographyConfig)

    def test_variable_name(self):
        from hydromodpy.data.variables.hydrography.variable import HydrographyVariable

        assert HydrographyVariable.VARIABLE_NAME == "hydrography"

    def test_package_exports_nothing(self):
        """A name is read from the module that defines it (rule 8), not from the package."""
        import hydromodpy.data.variables.hydrography as pkg

        assert not hasattr(pkg, "__all__")
        assert not hasattr(pkg, "HydrographyConfig")
        assert not hasattr(pkg, "HydrographySourceConfig")


# =====================================================================
# 19. Config - force_refresh field
# =====================================================================


@pytest.mark.fast
class TestForceRefreshConfig:
    def test_force_refresh_param_level_user(self):
        # The work-offline guide tells the reader to set it to download again.
        info = HydrographySourceConfig.model_fields["force_refresh"]
        for meta in info.metadata:
            if isinstance(meta, Profile):
                assert meta == Profile.USER
                return
        pytest.fail("force_refresh should have Profile.USER")
