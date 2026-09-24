"""Constant sea-level source for oceanic data manager."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pandas as pd

from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.variables.oceanic.config import OceanicSourceConfig

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hydromodpy.data.managers.base_manager_common import SourceContext


def generate_constant(
    config: OceanicSourceConfig,
    *,
    project_period: tuple[datetime, datetime] | None = None,
) -> list[PointRecord]:
    """Generate a constant mean sea-level PointRecord.

    If *project_period* is given, expands the constant to a daily series.
    """
    msl_value = float(config.value)

    if project_period is not None:
        index = pd.date_range(start=project_period[0], end=project_period[1], freq="D")
        df = pd.DataFrame({"datetime": index, "value": msl_value})
        date_start = index[0].to_pydatetime()
        date_end = index[-1].to_pydatetime()
    else:
        now = pd.Timestamp.now().to_pydatetime()
        df = pd.DataFrame({"datetime": [pd.Timestamp.now()], "value": [msl_value]})
        date_start = now
        date_end = now

    return [
        PointRecord(
            station_id="constant",
            variable="mean_sea_level",
            source="constant",
            unit="m",
            frequency="constant",
            data=df,
            date_start=date_start,
            date_end=date_end,
            is_constant=True,
        )
    ]


def fetch(
    cfg: OceanicSourceConfig,
    *,
    bbox: tuple | None,
    period: tuple[datetime, datetime] | None,
    context: SourceContext,
) -> list[PointRecord]:
    """The ``SOURCES`` entry of ``source = "constant"``: one level over the run's period."""
    del bbox, context
    return generate_constant(cfg, project_period=period)
