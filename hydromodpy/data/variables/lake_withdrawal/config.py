"""Pydantic configuration for lake-withdrawal volumetric time-series data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.base_config import BaseVariableConfig
from hydromodpy.data.variables.timeseries_variable_config import (
    TimeseriesColumnsMixin,
    TimeseriesSelectionMixin,
)


class LakeWithdrawalSourceConfig(TimeseriesColumnsMixin, TimeseriesSelectionMixin):
    """Configuration for one lake-withdrawal data source.

    Lake-withdrawal sources load observed volumetric withdrawal (L^3/T) time
    series per lake. The station id reused per chronicle is the ``lake_id``.
    """

    source: Annotated[Literal["custom"], Profile.USER] = Field(
        ..., description="Data provider: 'custom' for user files."
    )
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="lake_withdrawal", category="data"),
    ] = Field(default=None, description="Directory containing location file and chronicle CSVs.")

    @model_validator(mode="after")
    def _check_source_requirements(self) -> LakeWithdrawalSourceConfig:
        if self.source == "custom" and self.path is None:
            raise ValueError(
                "Custom source requires 'path' (directory with location + chronicles)."
            )
        return self


class LakeWithdrawalConfig(BaseVariableConfig):
    """Top-level lake-withdrawal configuration.

    The section groups observed lake-withdrawal sources and the optional
    simulation date window inherited from ``BaseVariableConfig``.
    """

    _TOML_SECTION = "lake_withdrawal"

    sources: Annotated[list[LakeWithdrawalSourceConfig], Profile.USER] = Field(
        ..., min_length=1, description="At least one lake-withdrawal data source."
    )

    @classmethod
    def from_csv_directory(
        cls,
        path: str | Path,
        *,
        start: str | None = None,
        end: str | None = None,
        **overrides,
    ) -> LakeWithdrawalConfig:
        """LakeWithdrawalConfig reading a directory of lake-withdrawal chronicle CSVs."""
        return cls(
            date_start=start,
            date_end=end,
            sources=[LakeWithdrawalSourceConfig(source="custom", path=Path(path), **overrides)],
        )
