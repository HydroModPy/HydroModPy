"""Dam cutoff wall of a lake, ``[flow.sinks_sources.lakes.<id>.cutoff_wall]``.

The wall is a :class:`FlowBarrierConfig` that sits on the lake shore: the part
of the declared trace facing the lake moves onto the shore it faces, so no cell
is left between the reservoir and the wall. ``snap_tolerance`` bounds that move.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.physics.flow.sinks_sources.flow_barrier import FlowBarrierConfig


class CutoffWallConfig(FlowBarrierConfig):
    """The flow barrier of a lake dam, laid on the lake shore."""

    snap_tolerance: Annotated[float, Profile.USER] = Field(
        default=50.0,
        ge=0.0,
        description=(
            "Largest gap [m] between the declared trace and the lake shore. The part of "
            "the trace facing the lake moves onto the shore it faces, so no cell sits "
            "between the reservoir and the wall; the trace beyond the banks stays as "
            "declared. A trace farther than this from the lake is refused. A trace that "
            "crosses the lake cuts its footprint, and the part downstream is dropped."
        ),
        json_schema_extra={"unit": "m"},
    )


__all__ = ["CutoffWallConfig"]
