"""The steady recharge a ``[data.recharge] formula`` asks for, from the yearly weather.

Turc, Guttman and Zuckerman, and Kessler give one value a year. A steady run
needs one rate, so the data step runs the formula on each complete calendar
year of the run, on the basin mean of the loaded precipitation (and
temperature), and takes the mean over the years. The rate is laid as a constant
daily grid on the grid of the precipitation and put where a loaded recharge
would sit, so the run reads it like any recharge product. No share of the year
is invented: a transient run is refused before it gets here.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.model.contracts import LoadResultProto
from hydromodpy.model.forcing.recharge_estimates_run import basin_series, weather_estimate
from hydromodpy.model.forcing.recharge_estimators import ESTIMATORS
from hydromodpy.model.forcing.soil_grids import (
    _guard_dims,
    _open_field_dataset,
    _variable_array,
    grid_field_record,
)


@dataclass(frozen=True, slots=True)
class SteadyRecharge:
    """The rate a formula gives a steady run, and the yearly values it is the mean of."""

    load_result: LoadResultProto
    yearly_mm: pd.Series
    formula: str

    def line(self) -> str:
        """The sentence the run prints about it."""
        years = self.yearly_mm.index
        what = ESTIMATORS[self.formula].gives.replace("_", " ")
        taken = ", taken whole as recharge" if what != "recharge" else ""
        return (
            f'[data.recharge] formula = "{self.formula}": {self.yearly_mm.mean():.0f} mm/year, '
            f"the mean of {len(years)} years ({int(years.min())} to {int(years.max())}, "
            f"{self.yearly_mm.min():.0f} to {self.yearly_mm.max():.0f}), an {what}{taken}"
        )


def computed_recharge(
    precipitation: LoadResultProto | None,
    temperature: LoadResultProto | None,
    formula: str,
    window: tuple[pd.Timestamp, pd.Timestamp],
) -> SteadyRecharge:
    """The steady recharge, mm/day, by ``formula`` over the years of ``window``."""
    section = "[data.precipitation]"
    if precipitation is None or not precipitation.has_fields or len(precipitation.fields) != 1:
        raise DataContractViolation(
            f'[data.recharge] formula = "{formula}" lays its rate on the grid of {section}, '
            'which holds no single daily grid: keep one gridded source, such as source = "sim2".'
        )
    start, end = (pd.Timestamp(t).tz_localize(None) if pd.Timestamp(t).tz else pd.Timestamp(t)
                  for t in window)  # fmt: skip

    def cut(result: LoadResultProto | None) -> pd.Series | None:
        series = basin_series(result)
        if series is None:
            return None
        return series[(series.index >= start.normalize()) & (series.index <= end)]

    yearly = weather_estimate(formula, cut(precipitation), cut(temperature))
    if isinstance(yearly, str) or yearly.empty:
        why = yearly if isinstance(yearly, str) else "no calendar year covered on 90 % of its days"
        raise DataContractViolation(
            f'[data.recharge] formula = "{formula}" has no yearly value over '
            f"{start.date()} to {end.date()}: {why}. Widen [simulation.time] to whole years."
        )
    record = precipitation.fields[0]
    da = _guard_dims(
        _variable_array(_open_field_dataset(record), record, section=section), section=section
    )
    x, y = da["x"].values, da["y"].values
    days = pd.date_range(start.normalize(), end.normalize(), freq="D").values
    rate = float(yearly.mean()) / 365.25
    values = np.full((len(days), x.size * y.size), rate, dtype=np.float64)
    field = grid_field_record("recharge", values, x=x, y=y, days=days, like=record, source=formula)
    return SteadyRecharge(type(precipitation)(fields=[field]), yearly, formula)


__all__ = ["SteadyRecharge", "computed_recharge"]
