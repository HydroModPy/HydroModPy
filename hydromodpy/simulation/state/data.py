"""Runtime data scope shared by launcher process runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.data_managers.contracts.load_result import LoadResult
    from hydromodpy.data_managers.geology.geology_field import GeologyField
    from hydromodpy.data_managers.variables.hydrography.result import HydrographyResult


@dataclass
class LoadedDataContext:
    """Loaded data-manager objects shared by process runs."""

    geology: GeologyField | None = None
    oceanic: LoadResult | None = None
    hydrography: HydrographyResult | None = None
    intermittency: LoadResult | None = None
    hydrometry: LoadResult | None = None
    piezometry: LoadResult | None = None
    recharge: LoadResult | None = None
    runoff: LoadResult | None = None
    precipitation: LoadResult | None = None
    etp: LoadResult | None = None
    temperature: LoadResult | None = None
    wind: LoadResult | None = None
    humidity: LoadResult | None = None
    radiation: LoadResult | None = None
    soil_moisture: LoadResult | None = None
