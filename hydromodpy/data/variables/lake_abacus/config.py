"""Pydantic configuration for lake abacus (stage-volume-area) data sources."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, ClassVar, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.source.url import UrlSourceOptions


class FileLakeAbacusSource(HydroModelBase):
    """User-provided lake abacus file (CSV/Parquet).

    The abacus is the stage-volume-area lookup table that drives
    ``ModflowUtllaktab``. One source describes one lake; ``lake_id`` is
    injected into the table when the file omits the column.
    """

    source: Annotated[Literal["file"], Profile.USER] = Field(
        default="file",
        description="Discriminator tag selecting the 'file' lake-abacus provider.",
    )
    path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="lake_abacus", category="data"),
    ] = Field(
        ...,
        description="Path to a user lake-abacus table file (CSV with stage,volume,sarea).",
        json_schema_extra=field_metadata(site_scoped=True),
    )
    lake_id: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Lake identifier injected into the table when the file omits a lake_id column.",
    )


class UrlLakeAbacusSource(UrlSourceOptions, HydroModelBase):
    """Remote lake abacus table, downloaded into the data cache by the ``url`` source."""

    source: Annotated[Literal["url"], Profile.USER] = Field(
        default="url",
        description="Discriminator tag selecting the 'url' lake-abacus provider.",
    )
    lake_id: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Lake identifier injected into the table when the file omits a lake_id column.",
    )


class LakeAbacusConfig(HydroModelBase):
    """Top-level lake-abacus variable configuration.

    Example TOML::

        [[data.lake_abacus.sources]]
        source = "file"
        path = "data/lake_abacus/lake_abacus_file_lac0.csv"
        lake_id = "lac0"
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "id": (
            "no step read the name of the abacus. Each source names the lake its "
            "table belongs to with lake_id."
        ),
    }

    sources: Annotated[list[FileLakeAbacusSource | UrlLakeAbacusSource], Profile.USER] = Field(
        ...,
        min_length=1,
        description="At least one lake-abacus data source.",
    )

    @classmethod
    def from_csv(
        cls, path: str | Path, *, lake_id: str | None = None, **overrides
    ) -> LakeAbacusConfig:
        """LakeAbacusConfig from a user abacus CSV (stage,volume,sarea)."""
        return cls(sources=[FileLakeAbacusSource(path=Path(path), lake_id=lake_id, **overrides)])
