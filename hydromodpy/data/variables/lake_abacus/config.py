"""Pydantic configuration for lake abacus (stage-volume-area) data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import IdentifierStr
from hydromodpy.core.tracking import InputFile


class CustomLakeAbacusSource(HydroModelBase):
    """User-provided lake abacus file (CSV/Parquet).

    The abacus is the stage-volume-area lookup table that drives
    ``ModflowUtllaktab``. One source describes one lake; ``lake_id`` is
    injected into the table when the file omits the column.
    """

    source: Annotated[Literal["custom"], Profile.USER] = Field(
        default="custom",
        description="Discriminator tag selecting the 'custom' lake-abacus provider.",
    )
    path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="lake_abacus", category="data"),
    ] = Field(
        ...,
        description="Path to a custom lake-abacus table file (CSV with stage,volume,sarea).",
    )
    lake_id: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Lake identifier injected into the table when the file omits a lake_id column.",
    )


class LakeAbacusConfig(HydroModelBase):
    """Top-level lake-abacus variable configuration.

    Example TOML::

        [[data.lake_abacus.sources]]
        source = "custom"
        path = "data/lake_abacus/lake_abacus_custom_lac0.csv"
        lake_id = "lac0"
    """

    sources: Annotated[list[CustomLakeAbacusSource], Profile.USER] = Field(
        ...,
        min_length=1,
        description="At least one lake-abacus data source.",
    )
    id: Annotated[IdentifierStr, Profile.USER] = Field(
        default="lake_abacus",
        description="Identifier of the lake-abacus table.",
    )

    @classmethod
    def from_csv(
        cls, path: str | Path, *, lake_id: str | None = None, **overrides
    ) -> LakeAbacusConfig:
        """LakeAbacusConfig from a custom abacus CSV (stage,volume,sarea)."""
        return cls(
            sources=[CustomLakeAbacusSource(path=Path(path), lake_id=lake_id)],
            **overrides,
        )
