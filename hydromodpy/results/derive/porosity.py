"""Effective porosity of a run, the water its pores hold and the turnover time it gives.

``effective_porosity`` looks first for a stored ``porosity`` field, which has one value
per layer and cell and is returned as stored. A run without one, which is every run
today, gives the one value that a ``[transport.<section>]`` of its sealed configuration
declares. That value is spread over every layer and cell, so a run of several layers gets
the same porosity in each. A run that declares none, or that declares one in several
sections, is refused, since no single value is then the porosity of the run.

``pore_volume`` weighs the porosity of each cell by its saturated thickness and its
area. ``turnover_years`` divides that volume by the mean outflow of the domain.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.core.exceptions import NothingThereError
from hydromodpy.core.fields.nodata import SENTINEL_ABS_THRESHOLD
from hydromodpy.core.units.quantities import DAYS_PER_YEAR, SECONDS_PER_DAY

FIELD = "porosity"


def effective_porosity(run: Any) -> np.ndarray:
    """Return the effective porosity as an array of shape (layers, cells).

    The stored field when the run holds one, else the one ``porosity`` that a section
    of ``[transport]`` sets in the sealed configuration of the run, spread over every
    layer and cell. Raises ``NothingThereError`` when neither exists, and when several
    sections set a porosity.
    """
    if run.has_field(FIELD):
        return np.atleast_2d(np.asarray(run.field(FIELD), dtype=float))
    sections = ((run.config_snapshot or {}).get("transport") or {}).items()
    found = {
        name: section[FIELD]
        for name, section in sections
        if isinstance(section, dict) and section.get(FIELD) is not None
    }
    if not found:
        raise NothingThereError(
            f"Run {run.name!r} stores no {FIELD!r} field and its configuration sets no "
            "[transport] porosity."
        )
    if len(found) > 1:
        raise NothingThereError(
            f"Run {run.name!r} sets a porosity in several [transport] sections "
            f"({', '.join(found)}), so it has no single porosity."
        )
    return np.full((run.n_layers, run.n_cells), float(next(iter(found.values()))))


def pore_volume(
    porosity: np.ndarray,
    head: np.ndarray,
    interfaces: np.ndarray,
    areas: np.ndarray,
    domain: np.ndarray,
) -> float:
    """Return the water held in the pores of the domain, in m3.

    ``porosity`` and ``head`` have the shape (layers, cells), ``interfaces`` the elevation
    of the layer tops and the last bottom, ``areas`` the area of each cell and ``domain``
    the active cells. The saturated thickness of a layer is the part of it under the head.
    A dry or inactive sentinel head holds no water.
    """
    head = np.atleast_2d(np.asarray(head, dtype=float))
    head = np.where(np.abs(head) >= SENTINEL_ABS_THRESHOLD, np.nan, head)
    thickness = np.clip(np.minimum(head, interfaces[:-1]) - interfaces[1:], 0.0, None)
    area = np.where(domain, np.nan_to_num(np.asarray(areas, dtype=float)), 0.0)
    return float((np.nan_to_num(porosity * thickness) * area).sum())


def turnover_years(volume: float, budget: pd.DataFrame) -> float:
    """Return ``volume`` over the mean outflow of the domain, in years.

    ``budget`` holds the rows of the domain budget, with ``component``, ``timestep`` and
    ``flux_out`` in m3/s. The storage terms are no outflow. Raises ``NothingThereError``
    when the domain loses no water.
    """
    rows = budget[~budget["component"].str.startswith("storage")]
    outflow = float(rows.groupby("timestep")["flux_out"].sum().abs().mean())
    if not outflow > 0:
        raise NothingThereError("The domain budget holds no outflow.")
    return volume / outflow / SECONDS_PER_DAY / DAYS_PER_YEAR
