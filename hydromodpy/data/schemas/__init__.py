"""Input-data contracts expressed as pandera schemas.

Each submodule exposes a pandera :class:`DataFrameSchema` (or a light
validator for non-dataframe contracts like :mod:`dem`) and a
``validate()`` helper that wraps pandera's validation error into
:class:`hydromodpy.core.exceptions.DataContractViolation`.

Spec reference: ``architecture_cible/03_data_contracts.md``.
"""

from __future__ import annotations

from hydromodpy.data.schemas.abacus import (
    AbacusTableSchema,
    validate_abacus,
)
from hydromodpy.data.schemas.catchment import (
    CatchmentPolygonSchema,
    validate_catchment,
)
from hydromodpy.data.schemas.dem import DEMContract, validate_dem
from hydromodpy.data.schemas.lithology import (
    LithologyTableSchema,
    validate_lithology,
)
from hydromodpy.data.schemas.stations import (
    StationCollectionSchema,
    validate_stations,
)
from hydromodpy.data.schemas.timeseries import (
    TimeSeriesSchema,
    validate_timeseries,
)
from hydromodpy.data.schemas.validation import (
    STRICT_ENV_VAR,
    validate_warn_only,
)

__all__ = [
    "TimeSeriesSchema",
    "validate_timeseries",
    "StationCollectionSchema",
    "validate_stations",
    "DEMContract",
    "validate_dem",
    "LithologyTableSchema",
    "validate_lithology",
    "AbacusTableSchema",
    "validate_abacus",
    "CatchmentPolygonSchema",
    "validate_catchment",
    "validate_warn_only",
    "STRICT_ENV_VAR",
]
