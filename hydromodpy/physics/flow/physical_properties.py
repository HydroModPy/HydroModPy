"""Pydantic model for flow physical properties with pint units.

This module introduces a typed, unit-aware representation of the core
hydrogeological scalars (``k_aquifer``, ``specific_yield``, ``specific_storage``)
used by flow simulations. It is the first P03 migration target and serves
as the template for the broader rollout planned in P04-P09 (field parameters,
recharge, boundary conditions, ...).

Canonical units
---------------
- ``k_aquifer`` :          m/s   (via :data:`HydraulicConductivity`)
- ``specific_yield`` :     -     (dimensionless, in [0, 1])
- ``specific_storage`` :   1/m   (via :data:`SpecificStorage`)

TOML compatibility
------------------
Each pint-typed field accepts either a bare number (interpreted in the
canonical unit) or an explicit ``"<value> <unit>"`` string, so the following
are all valid:

.. code-block:: toml

    [flow.properties]
    k_aquifer = 1e-4            # m/s (fallback)
    k_aquifer = "1e-4 m/s"
    k_aquifer = "0.36 m/h"      # auto-converted to m/s

The value always comes back as a pint ``Quantity`` in the canonical unit.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import ConfigDict, Field

from hydromodpy.core.units import (
    HydraulicConductivity,
    SpecificStorage,
    SpecificYield,
)
from hydromodpy.master_config.base import HydroModelBase
from hydromodpy.master_config.profile import Profile


class FlowPhysicalProperties(HydroModelBase):
    """Canonical physical properties of a flow medium.

    Each field uses a pint-backed Pydantic annotation so that unit conversion
    and range validation happen at construction time.
    """

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        str_strip_whitespace=True,
        validate_default=True,
    )

    k_aquifer: Annotated[HydraulicConductivity, Profile.USER] = Field(
        default="1e-4 m/s",
        description="Hydraulic conductivity of the aquifer (K).",
        json_schema_extra={
            "widget_type": "input",
            "unit": "m/s",
            "display_name_fr": "Conductivité hydraulique",
            "help_text_fr": (
                "Vitesse à laquelle l'eau traverse l'aquifère (m/s). "
                "Accepte une valeur numérique (m/s) ou une chaîne '<valeur> <unité>'."
            ),
            "display_min": 1e-14,
            "display_max": 1e2,
        },
    )

    specific_yield: Annotated[SpecificYield, Profile.USER] = Field(
        default=0.1,
        description="Specific yield of the aquifer (Sy), dimensionless.",
        json_schema_extra={
            "widget_type": "slider",
            "unit": "-",
            "display_name_fr": "Porosité efficace",
            "help_text_fr": "Fraction d'eau libérée par gravité (0-1).",
            "display_min": 0.001,
            "display_max": 0.5,
        },
    )

    specific_storage: Annotated[SpecificStorage, Profile.USER] = Field(
        default="1e-5 1/m",
        description="Specific storage coefficient (Ss), in m^-1.",
        json_schema_extra={
            "widget_type": "input",
            "unit": "1/m",
            "display_name_fr": "Emmagasinement spécifique",
            "help_text_fr": (
                "Volume d'eau libéré par unité de volume d'aquifère pour "
                "une baisse unitaire de charge (m^-1)."
            ),
            "display_min": 1e-9,
            "display_max": 1e-3,
        },
    )


__all__ = ["FlowPhysicalProperties"]
