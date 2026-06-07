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
