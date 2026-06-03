"""Helpers to discover and create validity-frame implementations.

The package exposes a default entry point named ``default`` in the
``validity_frame.frames`` group. External projects can register their own
implementations under the same group and load them dynamically.
"""

from __future__ import annotations

from importlib import metadata
from typing import Any

from .validity import ValidityFrame


def _iter_entry_points(group: str):
    entry_points = metadata.entry_points()
    if hasattr(entry_points, "select"):
        return entry_points.select(group=group)
    return entry_points.get(group, [])


def create_validity_frame(name: str = "default", **kwargs: Any):
    """Load and instantiate a validity-frame class from entry points.

    Parameters
    ----------
    name:
        Entry-point name inside the ``validity_frame.frames`` group.
    **kwargs:
        Keyword arguments forwarded to the selected class constructor.
    """
    for entry_point in _iter_entry_points("validity_frame.frames"):
        if entry_point.name == name:
            frame_cls = entry_point.load()
            return frame_cls(**kwargs)

    if name == "default":
        return ValidityFrame(**kwargs)

    available = sorted(ep.name for ep in _iter_entry_points("validity_frame.frames"))
    raise LookupError(f"No validity frame entry point named {name!r} found. Available: {available}")
