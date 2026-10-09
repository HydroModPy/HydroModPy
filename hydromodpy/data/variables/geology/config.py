"""Pydantic configuration for geology data sources."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import Field, ValidationError

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import (
    CellSamplingDensity,
    IdentifierStr,
)
from hydromodpy.core.tracking import InputFile
from hydromodpy.spatial.geology_config import GeologyConfigBlock


class _GeologySourceBase(HydroModelBase):
    """Shared fields for geology data sources."""

    mask_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Vector polygon file (shp, gpkg or GeoJSON) whose extent this source is "
            "requested over. A project run fills it with the delineated watershed."
        ),
    )
    extent: Annotated[Literal["watershed", "study_area"] | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Retrieve on the project extent rather than on this source's own filters. Only whether it is SET matters to the loaders; the two literals are told apart by the site-selection pipeline alone, and a standard project run clips on the delineated watershed either way, through the mask the loader fills in. Declared at DEV level for that reason: a project run neither needs it nor changes with it."
        ),
    )
    force_refresh: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Download this source again instead of reading the cache.",
    )


class CustomGeologySource(_GeologySourceBase):
    """User-provided geology file (SHP/GPKG/TIF/CSV)."""

    source: Annotated[Literal["custom"], Profile.USER] = Field(
        default="custom",
        description="Discriminator tag selecting the 'custom' geology provider.",
    )
    path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="geology", category="data"),
    ] = Field(
        ...,
        description="Path to custom geology file or directory (SHP, GPKG, TIF, CSV).",
    )
    code_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Attribute column for geology codes in custom vector files "
            "(SHP/GPKG). Required for custom vector sources."
        ),
    )
    values_table_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional CSV linking geology codes to descriptions. "
            "Columns: geology_code, description."
        ),
    )
    col_x: Annotated[str, Profile.DEV] = Field(
        default="x",
        description="Column for X coordinate in CSV.",
    )
    col_y: Annotated[str, Profile.DEV] = Field(
        default="y",
        description="Column for Y coordinate in CSV.",
    )
    col_code: Annotated[str, Profile.DEV] = Field(
        default="geology_code",
        description="Column for geology code in CSV.",
    )
    default_crs: Annotated[str, Profile.DEV] = Field(
        default="EPSG:2154",
        description="Default CRS for CSV points.",
    )


class BrgmGeology1mSource(_GeologySourceBase):
    """BRGM 1:1M national geological map (CODE_LEG legend)."""

    source: Annotated[Literal["brgm_1m"], Profile.USER] = Field(
        default="brgm_1m",
        description="Discriminator tag selecting the BRGM 1:1M geology provider.",
    )


class BrgmGeology50kSource(_GeologySourceBase):
    """BRGM 1:50K departmental geological map (CODE_LEG legend)."""

    source: Annotated[Literal["brgm_50k"], Profile.USER] = Field(
        default="brgm_50k",
        description="Discriminator tag selecting the BRGM 1:50K geology provider.",
    )


GeologySourceConfig: TypeAlias = Annotated[
    CustomGeologySource | BrgmGeology1mSource | BrgmGeology50kSource,
    Field(
        discriminator="source",
        description=(
            "Discriminated union of geology data sources tagged by the 'source' provider key."
        ),
    ),
]


class GeologyConfig(HydroModelBase):
    """Top-level geology variable configuration.

    The section defines one or more geology sources and the sampling density
    used when categorical geology is projected onto mesh cells. By default,
    HydroModPy uses the BRGM 1:1M source so geology can be activated by
    planner inference without a long user section.

    Example TOML::

        [data.geology]
        cell_samples_per_axis = 8

        [[data.geology.sources]]
        source = "brgm_1m"

        [[data.geology.sources]]
        source = "custom"
        path = "data/my_geology.gpkg"
        code_field = "LITHOLOGY"
    """

    sources: Annotated[list[GeologySourceConfig], Profile.USER] = Field(
        default_factory=lambda: [BrgmGeology1mSource()],
        min_length=1,
        description="At least one geology data source. Defaults to BRGM 1:1M.",
    )

    id: Annotated[IdentifierStr, Profile.USER] = Field(
        default="field_geology",
        description="Identifier of the geology spatial field.",
    )
    cell_samples_per_axis: Annotated[CellSamplingDensity, Profile.DEV] = Field(
        default=8,
        description=(
            "Sub-sampling density for GeologyField.on_mesh(). "
            "Higher = more precise geology interface, slower runtime."
        ),
    )

    @classmethod
    def brgm_1m(cls, **overrides) -> GeologyConfig:
        """GeologyConfig backed by the BRGM 1:1M national map."""
        return cls(sources=[BrgmGeology1mSource()], **overrides)

    @classmethod
    def brgm_50k(cls, **overrides) -> GeologyConfig:
        """GeologyConfig backed by the BRGM 1:50K departmental maps."""
        return cls(sources=[BrgmGeology50kSource()], **overrides)

    @classmethod
    def from_shapefile(
        cls,
        path: str | Path,
        *,
        code_field: str,
        **overrides,
    ) -> GeologyConfig:
        """GeologyConfig from a custom polygon shapefile (SHP or GPKG)."""
        return cls(
            sources=[
                CustomGeologySource(
                    path=Path(path),
                    code_field=code_field,
                )
            ],
            **overrides,
        )

    @classmethod
    def from_geotiff(cls, path: str | Path, **overrides) -> GeologyConfig:
        """GeologyConfig from a pre-rasterized GeoTIFF."""
        return cls(
            sources=[CustomGeologySource(path=Path(path))],
            **overrides,
        )


# ---------------------------------------------------------------------------
# Standalone geology field definitions, read with GeologyConfigBlock of
# spatial.geology_config (GeologyField.from_dict/from_toml and the data
# loader build a field from them directly).
# ---------------------------------------------------------------------------


def _get_nested_section(payload: Mapping[str, Any], dotted_path: str) -> Mapping[str, Any]:
    """Resolve a nested TOML section from a dotted path."""
    current: Any = payload
    for token in str(dotted_path).split("."):
        if not isinstance(current, Mapping) or token not in current:
            raise KeyError(f"Missing TOML section '{dotted_path}'")
        current = current[token]
    if not isinstance(current, Mapping):
        raise ValueError(f"TOML section '{dotted_path}' must be a mapping")
    return current


def validate_geology_config_data(config_data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate raw geology config mapping and return normalized Python data."""
    if not isinstance(config_data, Mapping):
        raise ValueError("geology configuration must be a mapping")
    try:
        parsed = GeologyConfigBlock.model_validate(dict(config_data))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    # JSON mode gives the paths back as text, as the readers of this mapping expect.
    return parsed.model_dump(mode="json")


def load_geology_toml(config_path: str | Path, section: str = "geology") -> dict[str, Any]:
    """Load TOML file and validate one geology section."""
    path = Path(config_path)
    payload = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    section_cfg = _get_nested_section(payload, section)
    try:
        return validate_geology_config_data(section_cfg)
    except ValueError as exc:
        raise ValueError(f"Invalid geology configuration in {path}: {exc}") from exc
