"""Pydantic configuration for lake-level (water-level) time-series data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.managers.base_config import BaseVariableConfig
from hydromodpy.data.variables.timeseries_variable_config import (
    TimeseriesColumnsMixin,
    TimeseriesSelectionMixin,
)


class LakeLevelsSourceConfig(TimeseriesColumnsMixin, TimeseriesSelectionMixin):
    """Configuration for one lake-levels data source.

    Lake-level sources load observed water-surface elevation time series used
    as a calibration target. The station id reused per chronicle is the
    ``lake_id``.
    """

    source: Annotated[Literal["custom"], Profile.USER] = Field(
        ..., description="Data provider: 'custom' for user files."
    )
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="lake_levels", category="data"),
    ] = Field(default=None, description="Directory containing location file and chronicle CSVs.")

    @model_validator(mode="after")
    def _check_source_requirements(self) -> LakeLevelsSourceConfig:
        if self.source == "custom" and self.path is None:
            raise ValueError(
                "Custom source requires 'path' (directory with location + chronicles)."
            )
        return self


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
            sources=[LakeLevelsSourceConfig(source="custom", path=Path(path), **overrides)],
        )
