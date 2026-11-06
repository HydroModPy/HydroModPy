"""The lake and SFR payloads of a Flow as plain dicts the binders can enrich."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.physics.flow import Flow


def payloads_as_mappings(flow: Flow, table: str) -> dict[str, dict[str, object]]:
    """Return ``flow.sinks_sources[table]`` as mutable dicts keyed by id.

    The runtime stores typed configs (``FlowLakeConfig``, ``FlowReachNetworkConfig``)
    or already-enriched dicts. The binders attach loaded data onto each payload, so
    they are normalized to plain dicts the LAK and SFR builders read.
    """
    sinks_sources = getattr(flow, "sinks_sources", {})
    entries = sinks_sources.get(table) if isinstance(sinks_sources, Mapping) else None
    if not isinstance(entries, Mapping) or not entries:
        return {}

    payloads: dict[str, dict[str, object]] = {}
    for entry_id, payload in entries.items():
        if isinstance(payload, Mapping):
            payloads[str(entry_id)] = dict(payload)
        else:
            # Snapshot every declared config field so a new field never drops out.
            payloads[str(entry_id)] = {
                name: getattr(payload, name, None) for name in type(payload).model_fields
            }
    return payloads
