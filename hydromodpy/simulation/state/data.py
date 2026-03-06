"""Runtime data scope shared by launcher process runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.data_managers.climatic import Climatic
    from hydromodpy.data_managers.geology.geology_field import GeologyField
    from hydromodpy.data_managers.hydrometry.station_set import StationSet
    from hydromodpy.data_managers.intermittency import Intermittency
    from hydromodpy.data_managers.oceanic import Oceanic
    from hydromodpy.data_managers.piezometry.piezometer_set import PiezometerSet
    from hydromodpy.data_managers.hydrography import Hydrography


@dataclass
class LoadedDataContext:
    """Loaded data-manager objects shared by process runs."""

    climatic: Climatic | None = None
    geology: GeologyField | None = None
    oceanic: Oceanic | None = None
    hydrography: Hydrography | None = None
    intermittency: Intermittency | None = None
    hydrometry: StationSet | None = None
    piezometry: PiezometerSet | None = None
