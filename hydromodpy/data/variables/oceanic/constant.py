"""Constant sea-level source for the oceanic data variable."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.source.port import (
    FetchRequest,
    FetchResult,
    PayloadKind,
    PeriodNeed,
    Selector,
    require_declared_variables,
    require_period,
    require_selectors,
)
from hydromodpy.data.variables.oceanic.config import OceanicSourceConfig


def generate_constant(
    config: OceanicSourceConfig,
    *,
    project_period: tuple[datetime, datetime] | None = None,
) -> list[PointRecord]:
    """Generate a constant mean sea-level PointRecord.

    If *project_period* is given, expands the constant to a daily series.
    """
    import pandas as pd

    from hydromodpy.data.contracts.timeseries import PointRecord

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


class ConstantSeaLevel:
    """Constant sea-level DataSource for oceanic boundary conditions."""

    section: ClassVar[str] = "oceanic"
    source_id: ClassVar[str] = "constant"
    payload_kind: ClassVar[PayloadKind] = "points"
    extent_crs: ClassVar[str] = "EPSG:2154"
    selectors: ClassVar[tuple[Selector, ...]] = ()
    period_need: ClassVar[PeriodNeed] = "optional"
    writes_out_dir: ClassVar[bool] = False

    variables: tuple[str, ...]
    hosts: tuple[str, ...]

    def __init__(self, *, value: float | None = None) -> None:
        self.value = 0.0 if value is None else float(value)
        self.variables = ("mean_sea_level",)
        self.hosts = ()

    def fetch(self, request: FetchRequest) -> FetchResult:
        require_selectors(self, request)
        period = require_period(self, request)
        records = generate_constant(
            OceanicSourceConfig(source="constant", value=self.value),
            project_period=period.as_tuple if period is not None else None,
        )
        require_declared_variables(self, [r.variable for r in records])
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=request.extent,
            period=period,
            points=tuple(records),
        )


__all__ = [
    "ConstantSeaLevel",
    "generate_constant",
]
