"""Pydantic configuration for lake-withdrawal volumetric time-series data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.managers.base_config import BaseVariableConfig
from hydromodpy.data.managers.timeseries_config import LakeChronicleSourceConfig


class LakeWithdrawalSourceConfig(LakeChronicleSourceConfig):
    """Configuration for one lake-withdrawal data source.

    Lake-withdrawal sources load observed volumetric withdrawal (L^3/T) time
    series per lake. The station id reused per chronicle is the ``lake_id``.
    """

    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="lake_withdrawal", category="data"),
    ] = Field(
        default=None,
        description="Directory containing location file and chronicle CSVs.",
        json_schema_extra=field_metadata(site_scoped=True),
    )


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
            sources=[LakeWithdrawalSourceConfig(source="file", path=Path(path), **overrides)],
        )
