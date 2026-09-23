"""How a simulated series relates to the time of its stamps.

A run stamps each stress period at its END. What that stamp means depends on
the quantity:

- ``"mean"``: the value stands for the whole period ``[start, stamp)``. A
  discharge, a drain or seepage flux, a runoff forcing. An observation
  chronicle is averaged over that period.
- ``"point"``: the value is the state AT the stamp instant. A MODFLOW head, a
  water table, a lake stage or volume. An observation chronicle is read at
  that instant, never averaged over the period that ends there: that would
  compare the state with a value half a period earlier.

The CF ``cell_methods`` of the field registry already carries the distinction
for every registered field (``time: point`` or ``time: mean``), and
:func:`hydromodpy.results.derive.time_alignment.time_method_for` reads it first.
The table below names what the registry does not hold: the calibration
variables and the observed families. It also repeats the registry states, so a
layer that may not read the registry, such as ``simulation``, resolves them the
same way; a unit test keeps the two in agreement.

An unknown name is ``"mean"``. That is the rule the discharge scoring was
measured on, and a flux is the commoner calibration target.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Literal

__all__ = (
    "DEFAULT_TIME_METHOD",
    "bare_observable_name",
    "OBSERVABLE_TIME_METHODS",
    "TIME_METHODS",
    "TimeMethod",
    "check_time_method",
    "observable_time_method",
    "time_method_from_cell_methods",
)

TimeMethod = Literal["mean", "point"]
"""``"mean"``: a period average on ``[start, stamp)``. ``"point"``: the state at the stamp."""

TIME_METHODS: tuple[str, ...] = ("mean", "point")

DEFAULT_TIME_METHOD: TimeMethod = "mean"
"""The method of a name nothing declares."""

OBSERVABLE_TIME_METHODS: Mapping[str, TimeMethod] = {
    # Fluxes over the period.
    "discharge": "mean",
    "outlet_discharge": "mean",
    "runoff": "mean",
    "lake_inflow": "mean",
    "lake_outflow": "mean",
    "lake_withdrawal": "mean",
    # States at the end instant of the period. The four registry states are
    # repeated here for the layers that cannot read the registry.
    "head": "point",
    "watertable_elevation": "point",
    "watertable_depth": "point",
    "concentration": "point",
    "saturated_thickness": "point",
    "groundwater_level": "point",
    "groundwater_depth": "point",
    "water_level": "point",
    "lake_level": "point",
    "lake_levels": "point",
    "stage": "point",
    "volume": "point",
    "surface_area": "point",
}
"""Time method of the observable names the field registry does not describe."""

_OBSERVED_SUFFIX = "_obs"
_TIME_ENTRY = re.compile(r"(?:^|\s)time:\s*([A-Za-z_]+)")


def check_time_method(method: str) -> TimeMethod:
    """Return ``method`` when it is a known time method, else raise ``ValueError``."""
    if method == "mean":
        return "mean"
    if method == "point":
        return "point"
    raise ValueError(f"unknown time method {method!r}; expected one of {TIME_METHODS}.")


def time_method_from_cell_methods(cell_methods: str) -> TimeMethod:
    """Return the time method a CF ``cell_methods`` string declares.

    ``time: point`` is a state at the stamp. Any other method on time (mean,
    sum, maximum) describes the whole period, so it aligns as ``"mean"``. A
    field with no ``time:`` entry has no time extent at all: its value holds at
    every instant, which is a point.
    """
    match = _TIME_ENTRY.search(str(cell_methods or ""))
    if match is None:
        return "point"
    return "point" if match.group(1).lower() == "point" else "mean"


def observable_time_method(name: str | None) -> TimeMethod:
    """Return the method of ``name`` from the table, ``"mean"`` when unknown.

    The ``_obs`` suffix the ingestion appends is ignored. Callers that may
    read the field registry use
    :func:`hydromodpy.results.derive.time_alignment.time_method_for` instead.
    """
    key = bare_observable_name(name)
    return OBSERVABLE_TIME_METHODS.get(key, DEFAULT_TIME_METHOD)


def bare_observable_name(name: str | None) -> str:
    """Return ``name`` stripped, without the ingestion ``_obs`` suffix."""
    key = str(name or "").strip()
    if key.endswith(_OBSERVED_SUFFIX):
        key = key[: -len(_OBSERVED_SUFFIX)]
    return key
