"""CF v85 + CSDMS Standard Names alignment for HydroModPy fields.

When a HydroModPy variable name has an exact CF v85 entry, we expose that
standard_name. When CF has no entry for the hydrogeology concept, we leave
``standard_name`` empty and provide a ``csdms_standard_name`` from the
CSDMS Standard Names registry (https://csdms.colorado.edu/wiki/CSDMS_Standard_Names).

Drift between the field registry and the writers used to inject CF-bogus
``standard_name`` values (see report 05 §2.1). This module is the single
source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CfAlias:
    """Standard-name pair for one canonical HydroModPy field."""

    standard_name: str = ""
    csdms_standard_name: str = ""
    valid_min: float | None = None
    valid_max: float | None = None


# Canonical HydroModPy field name -> CF/CSDMS aliases.
# CF v85: https://cfconventions.org/Data/cf-standard-names/85/build/cf-standard-name-table.html
# CSDMS:  https://csdms.colorado.edu/wiki/CSDMS_Standard_Names
CF_ALIASES: dict[str, CfAlias] = {
    "head": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water__hydraulic_head",
    ),
    "concentration": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water__mass_concentration",
        valid_min=0.0,
    ),
    "watertable_elevation": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water_top_surface__elevation",
    ),
    "watertable_depth": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water_top_surface__depth",
        valid_min=0.0,
    ),
    "seepage_mask": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water__seepage_binary_indicator",
        valid_min=0.0,
        valid_max=1.0,
    ),
    "seepage_rate": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water__seepage_volume_flux",
    ),
    "storage_change": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water_storage__derivative_of_volume",
    ),
    "recharge": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water__recharge_volume_flux",
    ),
    "drain": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water__drain_volume_flux",
    ),
    "outflow_drain": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water__outflow_volume_flux",
    ),
    "release_flux": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water__release_volume_flux",
    ),
    "accumulation_flux": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water__accumulation_volume_flux",
    ),
    "release_accumulation_flux": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water__release_accumulation_volume_flux",
    ),
    "river": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water__river_exchange_volume_flux",
    ),
    "well": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water__well_volume_flux",
    ),
    "surface_excess": CfAlias(
        standard_name="",
        csdms_standard_name="land_surface__saturation_excess_volume_flux",
    ),
    "cell_budget": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water__mass_balance_residual_volume_flux",
    ),
    "topography": CfAlias(
        # surface_altitude is a CF v85 standard name, canonical units m.
        standard_name="surface_altitude",
        csdms_standard_name="land_surface__elevation",
    ),
    "layer_thickness": CfAlias(
        standard_name="cell_thickness",
        csdms_standard_name="subsurface_layer__thickness",
        valid_min=0.0,
    ),
    "hydraulic_conductivity": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water__hydraulic_conductivity",
        valid_min=0.0,
    ),
    "specific_yield": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water__specific_yield",
        valid_min=0.0,
        valid_max=1.0,
    ),
    "specific_storage": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water__specific_storage_coefficient",
        valid_min=0.0,
    ),
    "porosity": CfAlias(
        standard_name="",
        csdms_standard_name="subsurface_water__effective_porosity",
        valid_min=0.0,
        valid_max=1.0,
    ),
}


def alias_for(field_name: str) -> CfAlias:
    """Return the CF/CSDMS alias for ``field_name`` or an empty placeholder."""
    return CF_ALIASES.get(field_name, CfAlias())


__all__ = ["CfAlias", "CF_ALIASES", "alias_for"]
