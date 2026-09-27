"""The numeric defaults of the stream-network criterion, in one Pydantic model.

Two layers read the same criterion and neither may import the other: a
calibration scores it per trial, and the results layer rebuilds it from a
finished run so a figure cannot contradict the numbers it illustrates. Both may
import ``core``, so this is the only place a default can live without being
written twice, and a threshold written twice is a map that drifts from its own
caption.

Three defaults change what is computed: ``tau_specific_ratio`` selects the
seepage threshold, ``diagonal_neighbors`` the graph the descent walks and
``observed_rasterization`` the cells the mapped network is drawn on. The other
three decide only what gets logged.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

ObservedRasterization = Literal["crossing", "touch"]
"""How the mapped stream network is drawn on the mesh cells.

``"crossing"`` keeps the cell holding each point where a line crosses the
segment joining two edge-sharing cell centres: WhiteboxTools
``VectorLinesToRaster`` on a structured grid. ``"touch"`` keeps every cell the
line intersects, corners included, the rule of the sessions before 2026-09.
"""


class StreamCriterionDefaults(HydroModelBase):
    """Defaults shared by the calibration criterion and its redrawn figures."""

    tau_specific_ratio: Annotated[float, Profile.EXPERT] = Field(
        default=1.0e-4,
        ge=0.0,
        description=(
            "Fraction of its own recharge below which a releasing cell is not a "
            "stream. A SPECIFIC flux, not a discharge: on a mesh of uneven cells a "
            "fixed m3/s cut would be nine times harsher on a cell three times "
            "smaller and the network would follow the refinement rather than the "
            "physics. 0.0 reproduces the purely geometric criterion of the paper."
        ),
    )
    diagonal_neighbors: Annotated[bool, Profile.EXPERT] = Field(
        default=True,
        description=(
            "Descend over shared nodes, the eight D8 neighbours of a quad mesh. "
            "The paper traces its distances with WhiteboxTools on a D8 pointer, and "
            "the delineation that closes the catchment uses one too. False walks "
            "shared edges only, four neighbours, and departs from the paper: a D4 "
            "descent cannot follow a talweg running diagonally across the grid. On "
            "a mesh whose faces are not all quadrilaterals no cell has a diagonal, "
            "so the descent walks shared edges whatever this says."
        ),
    )
    observed_rasterization: Annotated[ObservedRasterization, Profile.EXPERT] = Field(
        default="crossing",
        description=(
            "How the mapped network is drawn on the mesh. 'crossing' keeps the cells "
            "where a line crosses the segment joining two edge-sharing cell centres: "
            "WhiteboxTools VectorLinesToRaster, the tool of the paper, one cell wide "
            "like the simulated network. 'touch' keeps every cell the line touches, "
            "corners included, and replays a session made before 2026-09."
        ),
    )
    alpha_warning_threshold: Annotated[float, Profile.EXPERT] = Field(
        default=0.90,
        gt=0.0,
        le=1.0,
        description=(
            "Below this value of the catchment-restricted agreement between the "
            "mapped network and the model top, the run says its distances carry a "
            "top-versus-map disagreement on top of the hydrogeology. Logging only."
        ),
    )
    clipping_warning_share: Annotated[float, Profile.EXPERT] = Field(
        default=0.10,
        ge=0.0,
        le=1.0,
        description=(
            "Share of the mapped stream cells outside the delineated catchment above "
            "which the whole-mesh agreement is reported as unreadable. Those reaches "
            "trace through the buffer, where no cell is required to descend into the "
            "network. Logging only."
        ),
    )
    clipping_warning_gap: Annotated[float, Profile.EXPERT] = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum absolute gap between the whole-mesh and the catchment agreement "
            "for the clipping report to fire. A linework spilling out of the "
            "catchment over ground that routes the same way leaves the two equal, "
            "and reporting it there would be noise on every project. Logging only."
        ),
    )


STREAM_CRITERION_DEFAULTS = StreamCriterionDefaults()
"""The one instance every layer reads, so a default exists in a single object."""


__all__ = ["STREAM_CRITERION_DEFAULTS", "ObservedRasterization", "StreamCriterionDefaults"]
