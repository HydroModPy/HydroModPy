"""Pydantic configuration for radiation data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.managers.base_config import BaseVariableConfig
from hydromodpy.data.managers.timeseries_config import (
    TimeseriesColumnsMixin,
    TimeseriesSelectionMixin,
    UrlSourceFieldsMixin,
    registered_section_source,
)


class RadiationSourceConfig(UrlSourceFieldsMixin, TimeseriesColumnsMixin, TimeseriesSelectionMixin):
    """Configuration for one radiation data source.

    Radiation sources load atmospheric and/or visible radiation from custom
    files or SIM2 EDR products. Components select the radiation signals used by
    downstream forcing and HELP coupling.
    """

    source: Annotated[str, Profile.USER] = Field(
        ...,
        description=(
            "Data provider: 'custom' for user CSV files, or the id of a source registered "
            "for the radiation section, such as 'sim2' for the SIM2 EDR API."
        ),
    )

    @field_validator("source")
    @classmethod
    def _check_the_source_is_served_for_radiation(cls, source: str) -> str:
        return registered_section_source(source, "radiation")

    # --- Radiation-specific ---
    components: Annotated[list[Literal["atmospheric", "visible"]], Profile.USER] = Field(
        default=["atmospheric", "visible"],
        min_length=1,
        description="Radiation components: 'atmospheric' (DLI_Q) and/or 'visible' (SSI_Q).",
    )

    # --- Custom source fields ---
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="radiation", category="data"),
    ] = Field(
        default=None,
        description="Directory containing location file and chronicle CSVs, or a single .nc/.tif file.",
        json_schema_extra=field_metadata(site_scoped=True),
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> RadiationSourceConfig:
        if self.source == "file":
            if self.path is None:
                raise ValueError(
                    "File source requires 'path' (directory with location + chronicles, or a .nc/.tif file)."
                )
        return self


class RadiationConfig(BaseVariableConfig):
    """Top-level radiation configuration.

    The section groups radiation sources and an optional date window. Loaded
    data can support atmospheric forcing, potential evapotranspiration context,
    and HELP coupling.
    """

    _TOML_SECTION = "radiation"

    sources: Annotated[list[RadiationSourceConfig], Profile.USER] = Field(
        ..., min_length=1, description="At least one data source."
    )
