"""Lake levels, inflow, outflow and withdrawal, the observed series of a lake.

Each one reads a directory of chronicle CSVs whose station id is the ``lake_id``.
The levels are a calibration target, the three fluxes are volumetric (L^3/T).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.data.families.base_config import BaseVariableConfig
from hydromodpy.data.families.stations import StationVariable
from hydromodpy.data.families.timeseries_config import LakeChronicleSourceConfig

# --- Lake levels -----------------------------------------------------------


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


class LakeLevelsVariable(StationVariable):
    VARIABLE_NAME = "lake_levels"
    INTERNAL_UNIT = "m"
    RECORD_VARIABLE = "lake_level"


# --- Lake inflow -----------------------------------------------------------


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


class LakeInflowVariable(StationVariable):
    VARIABLE_NAME = "lake_inflow"
    INTERNAL_UNIT = "m3/s"


# --- Lake outflow ----------------------------------------------------------


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


class LakeOutflowVariable(StationVariable):
    VARIABLE_NAME = "lake_outflow"
    INTERNAL_UNIT = "m3/s"


# --- Lake withdrawal -------------------------------------------------------


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


class LakeWithdrawalVariable(StationVariable):
    VARIABLE_NAME = "lake_withdrawal"
    INTERNAL_UNIT = "m3/s"
