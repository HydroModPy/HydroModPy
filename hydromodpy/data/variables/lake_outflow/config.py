"""Pydantic configuration for lake-outflow volumetric time-series data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.managers.base_config import BaseVariableConfig
from hydromodpy.data.managers.timeseries_config import LakeChronicleSourceConfig


class LakeOutflowSourceConfig(LakeChronicleSourceConfig):
    """Configuration for one lake-outflow data source.

    Lake-outflow sources load observed volumetric outflow (L^3/T) time series per
    lake. The station id reused per chronicle is the ``lake_id``.
    """

    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="lake_outflow", category="data"),
    ] = Field(
        default=None,
        description="Directory containing location file and chronicle CSVs.",
        json_schema_extra=field_metadata(site_scoped=True),
    )


class LakeOutflowConfig(BaseVariableConfig):
    """Top-level lake-outflow configuration.

    The section groups observed lake-outflow sources and the optional simulation
    date window inherited from ``BaseVariableConfig``.
    """

    _TOML_SECTION = "lake_outflow"

    sources: Annotated[list[LakeOutflowSourceConfig], Profile.USER] = Field(
        ..., min_length=1, description="At least one lake-outflow data source."
    )

    @classmethod
    def from_csv_directory(
        cls,
        path: str | Path,
        *,
        start: str | None = None,
        end: str | None = None,
        **overrides,
    ) -> LakeOutflowConfig:
        """LakeOutflowConfig reading a directory of lake-outflow chronicle CSVs."""
        return cls(
            date_start=start,
            date_end=end,
            sources=[LakeOutflowSourceConfig(source="file", path=Path(path), **overrides)],
        )
