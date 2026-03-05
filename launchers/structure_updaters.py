"""Apply structural runtime updates from already-loaded data objects.

This module intentionally contains only pure, explicit binders:
- data loading happens in ``hydromodpy.data_managers.runtime_loader``,
- orchestration order stays in ``launchers.launcher``.

The updater signatures avoid passing a full ``RunResult`` object so each
binding remains explicit, testable, and reusable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.data_managers.geology.geology_field import GeologyField
    from hydromodpy.data_managers.oceanic import Oceanic
    from hydromodpy.domain import Domain
    from hydromodpy.process import Flow


def apply_geology_to_domain(
    *,
    domain: "Domain",
    geology: "GeologyField" | None,
    zone_id: str = "geology",
) -> None:
    """Attach one loaded geology field to the domain zone registry."""
    if geology is None:
        return
    domain.set_zone(zone_id, geology)


def apply_oceanic_to_flow(
    *,
    flow: "Flow",
    oceanic: "Oceanic" | None,
) -> None:
    """Inject mean sea-level value into the active ocean boundary condition."""
    if oceanic is None:
        return
    ocean_bc = flow.boundary_conditions.get("ocean")
    if ocean_bc is None:
        return
    ocean_bc.value = oceanic.MSL
