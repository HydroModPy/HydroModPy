"""Runtime data scope shared by launcher process runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class LoadedDataContext:
    """Loaded data-manager objects shared by process runs.

    Field types are ``Any`` because ``core`` cannot import from sibling
    layers (``data``, ``spatial``). Concrete types live in ``data.contracts``,
    ``data.variables.hydrography``, and ``spatial.field.geology``.
    """

    dem: Any = None
    geology: Any = None
    oceanic: Any = None
    hydrography: Any = None
    intermittency: Any = None
    hydrometry: Any = None
    piezometry: Any = None
    recharge: Any = None
    runoff: Any = None
    precipitation: Any = None
    etp: Any = None
    temperature: Any = None
    wind: Any = None
    humidity: Any = None
    radiation: Any = None
    soil_moisture: Any = None
    water_quality: Any = None
    lake_geometry: Any = None
    lake_bathymetry: Any = None
    lake_abacus: Any = None
    lake_levels: Any = None
    lake_inflow: Any = None
    lake_outflow: Any = None
    lake_withdrawal: Any = None
    # Data-plan types covered by the last completed load; None = never loaded.
    loaded_plan_types: tuple[str, ...] | None = None
