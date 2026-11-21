"""The ETP a ``[data.etp] formula`` asks for, computed on the grid of the loaded temperature.

The data step calls :func:`computed_etp` once every family is loaded and puts
the result where a loaded ETP would sit, so the soil reservoir, the EVT of
MODFLOW, the exports and the figures read it like any ETP product. The formulas
themselves are in ``model/soil/etp.py``; this module only reads the grid, finds
the latitude of each cell and wraps the answer as a load result.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pyproj import Transformer

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.model.contracts import LoadResultProto
from hydromodpy.model.forcing.soil_grids import (
    _guard_dims,
    _guard_temperature_scale,
    _open_field_dataset,
    _variable_array,
    grid_field_record,
)
from hydromodpy.model.soil.etp import ETP_FORMULAS


def cell_latitudes(x: np.ndarray, y: np.ndarray, crs: str) -> np.ndarray:
    """Latitude, degrees, of every cell of the ``(y, x)`` grid, flat in ``(y, x)`` order."""
    xx, yy = np.meshgrid(x, y)
    to_wgs84 = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    _, latitude = to_wgs84.transform(xx.ravel(), yy.ravel())
    return np.asarray(latitude, dtype=np.float64)


def computed_etp(temperature: LoadResultProto | None, formula: str) -> LoadResultProto:
    """The daily ETP, mm/day, by ``formula`` on the grid and days of ``temperature``."""
    section = "[data.temperature]"
    if temperature is None or not (temperature.has_fields or temperature.has_points):
        raise DataContractViolation(
            f'[data.etp] formula = "{formula}" computes the ETP from {section}, which '
            'loaded nothing: declare it, for instance with source = "sim2".'
        )
    if not temperature.has_fields or len(temperature.fields) != 1:
        raise DataContractViolation(
            f'[data.etp] formula = "{formula}" reads one daily grid from {section}, and '
            "it holds station series or several grids: keep one gridded source."
        )
    record = temperature.fields[0]
    if not record.crs:
        raise DataContractViolation(
            f"{section} grid declares no CRS, and the formula needs the latitude of each cell."
        )
    da = _guard_dims(
        _variable_array(_open_field_dataset(record), record, section=section), section=section
    )
    days = pd.DatetimeIndex(da["time"].values).normalize().values
    x, y = da["x"].values, da["y"].values
    values = np.asarray(da.values, dtype=np.float64).reshape(len(days), x.size * y.size)
    _guard_temperature_scale(values, pd.DatetimeIndex(days))
    latitude = cell_latitudes(x, y, str(record.crs))
    etp = ETP_FORMULAS[formula].formula(values, latitude, days.astype("datetime64[D]"))
    field = grid_field_record("etp", etp, x=x, y=y, days=days, like=record, source=formula)
    return type(temperature)(fields=[field])


__all__ = ["cell_latitudes", "computed_etp"]
