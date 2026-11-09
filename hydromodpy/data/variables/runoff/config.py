"""Pydantic configuration for runoff data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, ClassVar

from pydantic import Field

from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.managers.base_config import BaseVariableConfig
from hydromodpy.data.managers.timeseries_config import (
    Sim2GridSourceConfig,
    UrlSourceFieldsMixin,
)


class RunoffSourceConfig(UrlSourceFieldsMixin, Sim2GridSourceConfig):
    """Configuration for one runoff data source.

    Runoff sources load station or gridded surface-runoff time series from
    custom files or SIM2 EDR products. Source-level fields define file paths,
    station columns, masks, units, and cache refresh behavior.
    """

    VARIABLE_NAME: ClassVar[str] = "runoff"

    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="runoff", category="data"),
    ] = Field(
        default=None,
        description="Directory containing location file and chronicle CSVs, or a single .nc/.tif file.",
        json_schema_extra=field_metadata(site_scoped=True),
    )


class RunoffConfig(BaseVariableConfig):
    """Top-level runoff configuration.

    The section groups runoff sources and an optional date window. Loaded data
    can support hydrological forcing, recharge/runoff partitioning checks, and
    diagnostic comparisons.
    """

    _TOML_SECTION = "runoff"

    sources: Annotated[list[RunoffSourceConfig], Profile.USER] = Field(
        ...,
        min_length=1,
        description="At least one data source.",
    )
