"""Flow-side binders for data-to-structure updates."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.data_managers.oceanic import Oceanic
    from hydromodpy.process import Flow


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
