"""Keep in ``data.types`` only the types that have a section in the payload."""

from __future__ import annotations

from typing import Any


def with_declared_types_only(payload: dict[str, Any]) -> dict[str, Any]:
    """Return *payload* with ``data.types`` cut to the types that have a ``[data.<type>]`` section.

    A configuration lists the types it inferred from the flow (a lake adds
    ``lake_inflow``) but writes no section for them. The loader of a file refuses
    such a listing, so a payload read back from a configuration drops them here.
    A type written without its section is dropped too, as the seal does: a
    replay infers the types again. The input is left as it is.
    """
    data = payload.get("data")
    if not isinstance(data, dict) or "types" not in data:
        return payload
    kept = [name for name in data["types"] if name in data]
    return {**payload, "data": {**data, "types": kept}}
