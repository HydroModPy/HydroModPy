"""Pydantic configuration for lake-level (water-level) time-series data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.families.base_config import BaseVariableConfig
from hydromodpy.data.families.timeseries_config import LakeChronicleSourceConfig


class LakeLevelsSourceConfig(LakeChronicleSourceConfig):
    """Configuration for one lake-levels data source.

    Lake-level sources load observed water-surface elevation time series used
    as a calibration target. The station id reused per chronicle is the
    ``lake_id``.
    """

    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="lake_levels", category="data"),
    ] = Field(
        default=None,
        description="Directory containing location file and chronicle CSVs.",
        json_schema_extra=field_metadata(site_scoped=True),
    )


class LakeLevelsConfig(BaseVariableConfig):
    """Top-level lake-levels configuration.

    The section groups observed lake-level sources and the optional simulation
    date window inherited from ``BaseVariableConfig``.
    """

    _TOML_SECTION = "lake_levels"

    sources: Annotated[list[LakeLevelsSourceConfig], Profile.USER] = Field(
        ..., min_length=1, description="At least one lake-levels data source."
    )

    @classmethod
    def from_csv_directory(
        cls,
        path: str | Path,
        *,
        start: str | None = None,
        end: str | None = None,
        **overrides,
    ) -> LakeLevelsConfig:
        """LakeLevelsConfig reading a directory of lake-level chronicle CSVs."""
        return cls(
            date_start=start,
            date_end=end,
            sources=[LakeLevelsSourceConfig(source="file", path=Path(path), **overrides)],
        )
