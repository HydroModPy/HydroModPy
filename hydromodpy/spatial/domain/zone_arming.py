"""Declare the zone ids the runtime binders write into the domain registry.

``Domain.set_zone`` refuses any id absent from ``domain.zone_ids``, so every id a
binder targets has to be declared before the domain is built. Two of those ids
are hardcoded in the binders themselves and are therefore not the user's to
declare: ``catchment`` (``apply_catchment_zones_to_domain``) and ``geology``
(``apply_geology_to_domain``). Both binders no-op when their artifact is absent,
so arming an id nothing ends up writing costs nothing.

What is left for ``domain.zone_ids`` after this is what its name says: the
zonations a project declares itself.
"""

from __future__ import annotations

from typing import Any

BINDER_ZONE_IDS = ("catchment", "geology")
"""Zone ids the workflow binders write under a fixed name, whatever the config says."""


def arm_runtime_zone_ids(
    domain_cfg: Any,
    requested_support_ids: tuple[str, ...] = (),
) -> Any:
    """Append the binder zone ids and the requested support ids, in place."""
    zone_ids = getattr(domain_cfg, "zone_ids", None)
    if zone_ids is None:
        zone_ids = []
        domain_cfg.zone_ids = zone_ids
    if not isinstance(zone_ids, list):
        zone_ids = list(zone_ids)
        domain_cfg.zone_ids = zone_ids

    declared = {str(item).strip().lower() for item in zone_ids}
    for zone_id in BINDER_ZONE_IDS:
        if zone_id not in declared:
            zone_ids.append(zone_id)
            declared.add(zone_id)

    for support_id in requested_support_ids:
        normalized = str(support_id).strip().lower()
        if normalized in declared:
            continue
        zone_ids.append(str(support_id).strip())
        declared.add(normalized)
    return domain_cfg
