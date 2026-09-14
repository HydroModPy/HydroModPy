from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextModel:
    """CM = ⟨GeoNature, Attribute, Family, K_eff⟩ — generalized for any SuS."""

    # Identity
    system_name: str

    # Outlet / delineation — from project geographic config
    outlet_x: float | None = None  # x coordinate of the outlet (in project CRS)
    outlet_y: float | None = None  # y coordinate of the outlet (in project CRS)
    crs: str | None = None  # coordinate reference system (e.g. EPSG:2154)

    # Physical structure of the aquifer
    aquifer_thickness_m: float | None = None  # constant thickness below topography
    catchment_area_km2: float | None = None  # total watershed area

    # Lithological context
    geo_nature: dict[str, Any] = field(default_factory=dict)
    # qualitative types (lithology, land-use...)
    attributes: dict[str, float] = field(default_factory=dict)
    # quantitative fractions α_i,j per rock type

    # Set of sub-units (catchments, sites, basins...)
    family: list[str] = field(default_factory=list)

    # Effective conductivity per sub-unit (filled after calibration)
    k_eff: dict[str, float] = field(default_factory=dict)

    # Free domain-specific fields
    extra: dict[str, Any] = field(default_factory=dict)
