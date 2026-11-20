"""The hydrography section of the data config: sources, profile levels and refusals.

A source is one of the ids the registry resolves for the section. Each field
carries a Profile level that says who sets it (user or developer).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel, ValidationError

import hydromodpy.data.variables.hydrography as hydrography_package
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.data.loading.config_schema import DataConfig
from hydromodpy.data.variables.hydrography.config import (
    HydrographyConfig,
    HydrographySourceConfig,
)

pytestmark = pytest.mark.fast


def profile_level(model_cls: type[BaseModel], field_name: str) -> str | None:
    for meta in model_cls.model_fields[field_name].metadata:
        if isinstance(meta, Profile):
            return meta.name.lower()
    return None


SOURCE_LEVELS = [
    pytest.param("source", "user", id="source"),
    pytest.param("path", "user", id="path"),
    pytest.param("rasterize_field", "user", id="rasterize_field"),
    pytest.param("force_refresh", "user", id="force_refresh"),
    pytest.param("page_size", "dev", id="page_size"),
    pytest.param("group_name", "dev", id="group_name"),
    pytest.param("euhydro_page_size", "dev", id="euhydro_page_size"),
    pytest.param("waterway_types", "dev", id="waterway_types"),
]


@pytest.mark.parametrize(("field", "level"), SOURCE_LEVELS)
def test_source_field_levels(field, level):
    assert profile_level(HydrographySourceConfig, field) == level


def test_sources_field_is_user_level():
    assert profile_level(HydrographyConfig, "sources") == "user"


def test_container_forbids_extra_fields():
    assert HydrographyConfig.model_config.get("extra") == "forbid"


def test_container_is_not_a_dataclass():
    assert not dataclasses.is_dataclass(HydrographyConfig)


def test_package_exports_nothing():
    # A name is read from the module that defines it, not from the package.
    assert not hasattr(hydrography_package, "__all__")
    assert not hasattr(hydrography_package, "HydrographyConfig")
    assert not hasattr(hydrography_package, "HydrographySourceConfig")


def test_data_config_types_the_hydrography_field():
    info = DataConfig.model_fields["hydrography"]

    assert "HydrographyConfig" in str(info.annotation)


def test_a_section_without_the_type_still_validates(tmp_path):
    section = {
        "types": ["geology"],
        "hydrography": {"sources": [{"source": "osm"}]},
    }

    cfg = DataConfig.from_toml_section(section, base_dir=tmp_path)

    assert cfg.hydrography is not None
    assert "hydrography" not in cfg.types


class AcmeGaugeSource:
    """A gauge source resolves, and it is not a river network."""

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


SOURCE_REFUSALS = [
    pytest.param({"source": "file"}, "path", id="file without path"),
    pytest.param({"source": "nasa"}, "nasa", id="unknown source"),
]


@pytest.mark.parametrize(("kwargs", "match"), SOURCE_REFUSALS)
def test_source_refusals(kwargs, match):
    with pytest.raises(ValidationError, match=match):
        HydrographySourceConfig(**kwargs)


def test_an_unknown_source_in_a_toml_section_is_refused():
    section = {"types": ["hydrography"], "hydrography": {"sources": [{"source": "invalid_api"}]}}

    with pytest.raises((ValidationError, ValueError), match="invalid_api"):
        DataConfig.from_toml_section(section, base_dir=Path("/tmp"))


def test_a_gauge_source_is_refused_by_the_document(isolated_registry):
    # Validating only that the name resolves would let a gauge through here and refuse it
    # inside the fetch, after a provider had been contacted.
    isolated_registry.register(AcmeGaugeSource)

    with pytest.raises(ValidationError, match="features"):
        HydrographySourceConfig(source="acme-gauge")
