"""The ``lineage`` block of a seal: where a run comes from, by ids.

Why
---
Names move: a rename, a restore, a tar extracted elsewhere. Ids do not. The
link from a promoted run to its session, from a rerun to its parent, from a
versioned run to the surcharge that made it, is written by id. A ``*_hint``
is a directory name as it was at seal time, for a human reading the file; a
tool never requires it.

Format
------
``parent_sim_id`` is the run this one derives from (a rerun, a restart).
``session_id``, ``phase`` and ``trial`` name the calibration trial a promoted
run is. ``kind`` says which relation holds. ``overrides`` is what ``--set`` or
``--overlay`` changed against the file the run was launched from, as dotted
paths to values, so a ``.v2`` says what differs from the ``.v1``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase

LineageKind = Literal["rerun", "promoted", "trial", "version"]
"""The relation a run has with what it comes from."""


class Lineage(HydroModelBase):
    """Links of a run to its parent run, its session and its surcharges."""

    parent_sim_id: str | None = Field(default=None, description="Run this one derives from")
    session_id: str | None = Field(default=None, description="Session a promoted run comes from")
    phase: str | None = Field(default=None, description="Phase of that session")
    trial: int | None = Field(default=None, ge=1, description="Trial of that session")
    kind: LineageKind | None = Field(default=None, description="Relation to the parent")
    overrides: dict[str, Any] = Field(
        default_factory=dict, description="Dotted paths changed by --set or --overlay"
    )
    parent_hint: str | None = Field(
        default=None, description="Relative directory of the parent at seal time, for a reader"
    )


__all__ = ["Lineage", "LineageKind"]
