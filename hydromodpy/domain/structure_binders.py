"""Domain-side binders for data-to-structure updates."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.data_managers.geology.geology_field import GeologyField
    from hydromodpy.domain import Domain


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
