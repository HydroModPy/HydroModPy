"""Pydantic configuration for hydrometry data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.families.base_config import BaseVariableConfig
from hydromodpy.data.families.timeseries_config import (
    SparseStationFallbackMixin,
    TimeseriesColumnsMixin,
    TimeseriesSelectionMixin,
    registered_section_source,
)


class HydrometrySourceConfig(
    TimeseriesColumnsMixin, TimeseriesSelectionMixin, SparseStationFallbackMixin
):
    """Configuration for one hydrometry data source.

    Hydrometry sources load river discharge or stage time series. Use
    ``file`` for local station files and ``hubeau`` for the French Hub'Eau
    hydrometry API. Station filters, spatial masks, and units are declared at
    source level.
    """

    source: Annotated[str, Profile.USER] = Field(
        default="hubeau",
        description=(
            "Data provider: 'file' for user files, or the id of a source registered for "
            "the hydrometry section, such as 'hubeau' for the Hub'Eau API."
        ),
    )

    @field_validator("source")
    @classmethod
    def _check_the_source_is_served_for_hydrometry(cls, source: str) -> str:
        return registered_section_source(source, "hydrometry")

    # --- File source fields ---
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="hydrometry", category="data"),
    ] = Field(
        default=None,
        description="Directory containing location file and chronicle CSVs.",
        json_schema_extra=field_metadata(site_scoped=True),
    )

    # --- API source fields ---
    product: Annotated[str | None, Profile.USER] = Field(
        default="QmnJ",
        description="Hub'Eau variable code (e.g. 'QmnJ', 'QmM', 'HIXnJ').",
    )

    @field_validator("product")
    @classmethod
    def _validate_product(cls, product: str | None) -> str | None:
        if product is not None:
            if product == "QixM":
                product = "QIXM"
            from hydromodpy.data.variables.hydrometry.apis.hubeau import PRODUCTS

            if product not in PRODUCTS:
                allowed = ", ".join(f"'{p}'" for p in sorted(PRODUCTS))
                raise ValueError(
                    f"Hub'Eau product {product!r} is not supported. Use one of {allowed}."
                )
        return product

    require_observations: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description=(
            "Drop stations whose declared service period does not overlap the requested "
            "window, before downloading them. It is a metadata filter: a station that "
            "overlaps but returns nothing is dropped after its download instead, and the "
            "run says which ones."
        ),
    )
    max_stations: Annotated[int | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Maximum number of Hub'Eau stations to KEEP. Stations that return no "
            "observation in the window do not count against it, so a preview run over a "
            "larger territory gets this many stations carrying data, not this many tried."
        ),
        json_schema_extra={"unit": "-"},
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> HydrometrySourceConfig:
        if self.source == "file":
            if self.path is None:
                raise ValueError(
                    "File source requires 'path' (directory with location + chronicles)."
                )
        if self.source == "hubeau":
            if self.product is None:
                raise ValueError("Hub'Eau source requires 'product' (e.g. 'QmnJ').")
        return self


class HydrometryConfig(BaseVariableConfig):
    """Top-level hydrometry configuration.

    The section groups hydrometric sources and the optional simulation date
    window inherited from ``BaseVariableConfig``. Loaded data is stored as
    station time series for calibration, boundary checks, or reporting.
    """

    _TOML_SECTION = "hydrometry"

    sources: Annotated[list[HydrometrySourceConfig], Profile.USER] = Field(
        ..., min_length=1, description="At least one data source."
    )

    @classmethod
    def hubeau(
        cls,
        *,
        stations: list[str] | None = None,
        product: str = "QmnJ",
        start: str | None = None,
        end: str | None = None,
        extent: Literal["watershed", "study_area"] | None = None,
        **overrides,
    ) -> HydrometryConfig:
        """HydrometryConfig reading discharge timeseries from the Hub'Eau API."""
        source_kwargs: dict[str, object] = {"product": product}
        if stations is not None:
            source_kwargs["station_ids"] = list(stations)
        if extent is not None:
            source_kwargs["extent"] = extent
        source_kwargs.update(overrides)
        return cls(
            date_start=start,
            date_end=end,
            sources=[HydrometrySourceConfig(source="hubeau", **source_kwargs)],
        )

    @classmethod
    def from_csv_directory(
        cls,
        path: str | Path,
        *,
        start: str | None = None,
        end: str | None = None,
        col_id: str = "id",
        col_x: str = "x",
        col_y: str = "y",
        col_datetime: str = "datetime",
        col_value: str = "value",
        **overrides,
    ) -> HydrometryConfig:
        """HydrometryConfig reading a directory of station CSVs."""
        return cls(
            date_start=start,
            date_end=end,
            sources=[
                HydrometrySourceConfig(
                    source="file",
                    path=Path(path),
                    col_id=col_id,
                    col_x=col_x,
                    col_y=col_y,
                    col_datetime=col_datetime,
                    col_value=col_value,
                    **overrides,
                )
            ],
        )
