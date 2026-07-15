"""[data] TOML wiring for the lake families: typed sections + path resolution.

Guards that ``[data.lake_*]`` sections validate into the
dedicated typed configs through ``DataManagersConfig.from_toml_section`` and
that ``InputFile``-annotated paths are resolved relative to the TOML dir.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.data.managers.config_schema import (
    SUPPORTED_DATA_MANAGER_TYPES,
    DataManagersConfig,
)
from hydromodpy.data.variables.lake_abacus.config import (
    CustomLakeAbacusSource,
    LakeAbacusConfig,
)
from hydromodpy.data.variables.lake_geometry.config import LakeGeometryConfig


def test_lake_families_are_supported_manager_types() -> None:
    for name in ("lake_abacus", "lake_bathymetry", "lake_geometry", "lake_levels"):
        assert name in SUPPORTED_DATA_MANAGER_TYPES


def test_lake_sections_validate_into_typed_configs(tmp_path) -> None:
    (tmp_path / "lake_abacus_custom_lac0.csv").write_text(
        "stage,volume,sarea\n85,0,0\n90,1e6,4e5\n", encoding="utf-8"
    )
    (tmp_path / "lac0.gpkg").write_text("placeholder", encoding="utf-8")

    section = {
        "types": ["lake_abacus", "lake_geometry"],
        "lake_abacus": {
            "sources": [
                {
                    "source": "custom",
                    "path": "lake_abacus_custom_lac0.csv",
                    "lake_id": "lac0",
                }
            ]
        },
        "lake_geometry": {"sources": [{"source": "custom", "path": "lac0.gpkg"}]},
    }

    cfg = DataManagersConfig.from_toml_section(section, base_dir=tmp_path)

    assert isinstance(cfg.lake_abacus, LakeAbacusConfig)
    assert isinstance(cfg.lake_geometry, LakeGeometryConfig)

    abacus_src = cfg.lake_abacus.sources[0]
    assert isinstance(abacus_src, CustomLakeAbacusSource)
    assert abacus_src.lake_id == "lac0"
    # InputFile path resolved to an absolute path under the TOML directory.
    assert Path(abacus_src.path).is_absolute()
    assert Path(abacus_src.path).exists()

    geom_path = cfg.lake_geometry.sources[0].path
    assert Path(geom_path).is_absolute()
    assert Path(geom_path).exists()


def test_extra_field_is_forbidden_in_lake_source() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LakeAbacusConfig.model_validate(
            {"sources": [{"source": "custom", "path": "a.csv", "unexpected": 1}]}
        )
