"""Pydantic configuration for lake-inflow volumetric time-series data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.managers.base_config import BaseVariableConfig
from hydromodpy.data.managers.timeseries_config import LakeChronicleSourceConfig


class LakeInflowSourceConfig(LakeChronicleSourceConfig):
    """Configuration for one lake-inflow data source.

    Lake-inflow sources load observed volumetric inflow (L^3/T) time series per
    lake. The station id reused per chronicle is the ``lake_id``.
    """

    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="lake_inflow", category="data"),
    ] = Field(
        default=None,
        description="Directory containing location file and chronicle CSVs.",
        json_schema_extra=field_metadata(site_scoped=True),
    )


class LakeInflowConfig(BaseVariableConfig):
    """Top-level lake-inflow configuration.

    The section groups observed lake-inflow sources and the optional simulation
    date window inherited from ``BaseVariableConfig``.
    """

    _TOML_SECTION = "lake_inflow"

    sources: Annotated[list[LakeInflowSourceConfig], Profile.USER] = Field(
        ..., min_length=1, description="At least one lake-inflow data source."
    )

    @classmethod
    def from_csv_directory(
        cls,
        path: str | Path,
        *,
        start: str | None = None,
        end: str | None = None,
        **overrides,
    ) -> LakeInflowConfig:
        """LakeInflowConfig reading a directory of lake-inflow chronicle CSVs."""
        return cls(
            date_start=start,
            date_end=end,
            sources=[LakeInflowSourceConfig(source="file", path=Path(path), **overrides)],
        )
