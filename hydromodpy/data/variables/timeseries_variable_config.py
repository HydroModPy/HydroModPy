"""Common Pydantic base for point/station time-series variable configs.

Historically, ~14 variable modules under :mod:`hydromodpy.data.variables`
(``etp``, ``humidity``, ``temperature``, ``wind``, ``precipitation``,
``radiation``, ``hydrometry``, ``intermittency``, ``piezometry``,
``soil_moisture``, ``runoff``, ``recharge``, etc.) declared the same
handful of columns — ``col_id``, ``col_x``, ``col_y``, ``col_crs``,
``col_datetime``, ``col_value``, ``default_crs`` — plus ``station_ids``,
``extent`` and ``force_refresh``. The architecture spec
(``architecture_cible/02_config_pydantic.md`` §3.4) factors these fields
out into a single :class:`TimeseriesVariableConfig` base.

Variable-specific configs now only need to declare their extra fields
(e.g. ``product`` for piezometry, ``components`` for precipitation) and
inherit the common CSV grammar from this class. Sources remain
discriminated by variable via the existing ``<Variable>SourceConfig`` classes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.profile import Profile
from hydromodpy.data.base_config import BaseVariableConfig


class TimeseriesColumnsMixin(HydroModelBase):
    """Shared CSV column-name grammar for point/station time series.

    The defaults follow the SANDRE-style CSV convention used across every
    existing timeseries variable in HydroModPy.
    """

    col_id: Annotated[str, Profile.DEV] = Field(
        default="id",
        description="Column name for the station identifier in location files.",
    )
    col_x: Annotated[str, Profile.DEV] = Field(
        default="x",
        description="Column name for the X coordinate in location files.",
    )
    col_y: Annotated[str, Profile.DEV] = Field(
        default="y",
        description="Column name for the Y coordinate in location files.",
    )
    col_crs: Annotated[str, Profile.DEV] = Field(
        default="crs",
        description="Column name for the CRS in location files.",
    )
    col_datetime: Annotated[str, Profile.DEV] = Field(
        default="datetime",
        description="Column name for timestamps in chronicle CSVs.",
    )
    col_value: Annotated[str, Profile.DEV] = Field(
        default="value",
        description="Column name for numeric values in chronicle CSVs.",
    )
    default_crs: Annotated[str, Profile.DEV] = Field(
        default="EPSG:4326",
        description="Default CRS used when a location file omits the CRS column.",
    )


class TimeseriesSelectionMixin(HydroModelBase):
    """Shared station selection and cache grammar for timeseries variables."""

    station_ids: Annotated[list[str] | None, Profile.USER] = Field(
        default=None,
        description="Explicit station identifiers to load (custom source).",
    )
    extent: Annotated[
        Literal["watershed", "study_area"] | None, Profile.USER,
    ] = Field(
        default=None,
        description=(
            "Enable bounding-box data retrieval using the project extent. "
            "``watershed`` uses the delineated watershed, ``study_area`` uses "
            "the broader study bounding box."
        ),
    )
    force_refresh: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Ignore the cache and force a fresh download from the API.",
    )


class TimeseriesVariableConfig(BaseVariableConfig):
    """Factored base for ``[data.<timeseries_variable>]`` TOML sections.

    Subclasses bring their own ``sources: list[<VariableSourceConfig>]``
    field (and any variable-specific parameters such as ``product`` or
    ``components``). The date range and CSV column grammar are inherited
    from :class:`BaseVariableConfig` and the selection/cache fields below.
    """

    # Re-expose the shared CSV column-name grammar at the top level of the
    # variable config so it can be overridden alongside dates.
    col_id: Annotated[str, Profile.DEV] = Field(default="id")
    col_x: Annotated[str, Profile.DEV] = Field(default="x")
    col_y: Annotated[str, Profile.DEV] = Field(default="y")
    col_crs: Annotated[str, Profile.DEV] = Field(default="crs")
    col_datetime: Annotated[str, Profile.DEV] = Field(default="datetime")
    col_value: Annotated[str, Profile.DEV] = Field(default="value")
    default_crs: Annotated[str, Profile.DEV] = Field(default="EPSG:4326")

    station_ids: Annotated[list[str] | None, Profile.USER] = Field(
        default=None,
        description="Explicit station identifiers to load (custom source).",
    )
    extent: Annotated[
        Literal["watershed", "study_area"] | None, Profile.USER,
    ] = Field(
        default=None,
        description="Enable bbox-based data retrieval using the project extent.",
    )
    force_refresh: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Ignore the cache and force a fresh download from the API.",
    )
    mask_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional SHP/GPKG/GeoJSON/TIF mask to spatially filter stations "
            "or clip gridded sources."
        ),
    )


__all__ = [
    "TimeseriesColumnsMixin",
    "TimeseriesSelectionMixin",
    "TimeseriesVariableConfig",
]
