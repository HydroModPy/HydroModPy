"""The numeric defaults of the stream-network criterion, in one Pydantic model.

Two layers read the same criterion and neither may import the other: a
calibration scores it per trial, and the results layer rebuilds it from a
finished run so a figure cannot contradict the numbers it illustrates. Both may
import ``core``, so this is the only place a default can live without being
written twice, and a threshold written twice is a map that drifts from its own
caption.

Six defaults change what is computed: ``tau_specific_ratio`` selects the
seepage threshold, ``diagonal_neighbors`` the graph the descent walks,
``observed_rasterization`` the cells the mapped network is drawn on,
``clip_map_to_catchment`` the part of the map it draws them from, and the two
``heads_`` values where the heads rule lets a head land. ``max_catchment_mismatch``
refuses a search and computes nothing. The other three decide only what gets
logged.

The module also holds the few words that ``display`` reads and that ``display`` may not
take from ``catchment``: the visible-flow threshold (:class:`VisibleFlow`,
:func:`parse_visible_flow`, ``DEFAULT_VISIBLE_FLOW``, ``GEOMETRIC``) and the numbers a
trial publishes for the provenance of the validity length.

A named protocol does not read these defaults for a version it has frozen: its
own table says what each version runs
(:data:`hydromodpy.calibration.protocols.matching_hydrographic_network.DEFAULTS_BY_VERSION`),
and a test holds the last line of that table equal to this object.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units.quantities import parse_to_m3_per_s

#: The descent walks shared nodes, the eight D8 neighbours of a quad mesh, unless told
#: otherwise. The criterion takes its ``diagonal_neighbors`` default from here, and the
#: downslope distance of ``catchment/drainage`` reads it too.
D8_DESCENT_BY_DEFAULT = True

ObservedRasterization = Literal["heads", "crossing", "touch"]
"""How the mapped stream network is drawn on the mesh cells.

``"heads"`` keeps only the free ends of the map whose largest drained area
within the snap radius does not exceed that of the other end of their reach,
lands each on a nearby cell draining enough, and follows
the criterion graph down from there: the map is drawn by the model's own
descent, connected to the outlet. ``"crossing"`` keeps the cell holding each
point where a line crosses the segment joining two edge-sharing cell centers:
WhiteboxTools ``VectorLinesToRaster`` on a structured grid, and the rule for a
map that is not a tree (canals, braids, polders, karst). ``"touch"`` keeps
every cell the line intersects, corners included, the rule of the sessions
before 2026-09.
"""


class StreamCriterionDefaults(HydroModelBase):
    """Defaults shared by the calibration criterion and its redrawn figures."""

    tau_specific_ratio: Annotated[float, Profile.EXPERT] = Field(
        default=1.0e-4,
        ge=0.0,
        description=(
            "Fraction of the mean basin recharge, over its own area, below which a releasing cell is not a "
            "stream. A SPECIFIC flux, not a discharge: on a mesh of uneven cells a "
            "fixed m3/s cut would be nine times harsher on a cell three times "
            "smaller and the network would follow the refinement rather than the "
            "physics. 0.0 reproduces the purely geometric criterion of the paper."
        ),
    )
    diagonal_neighbors: Annotated[bool, Profile.EXPERT] = Field(
        default=D8_DESCENT_BY_DEFAULT,
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
        default="heads",
        description=(
            "How the mapped network is drawn on the mesh. 'crossing' keeps the cells "
            "where a line crosses the segment joining two edge-sharing cell centres: "
            "WhiteboxTools VectorLinesToRaster, the tool of the paper, one cell wide "
            "like the simulated network. 'touch' keeps every cell the line touches, "
            "corners included, and replays a session made before 2026-09. 'heads' "
            "keeps the free ends of the map and draws the rest down the model's own "
            "descent, connected to the outlet."
        ),
    )
    clip_map_to_catchment: Annotated[bool, Profile.EXPERT] = Field(
        default=True,
        description=(
            "Cut the mapped network to the delineated catchment before drawing it, the "
            "way the hydrography data family cuts what it loads, so a file and "
            "data.hydrography draw the same map. An end the cut made is no stream "
            "head under the 'heads' rule. False reads the map as it arrives, whole "
            "from a file, and takes every free end as a candidate head."
        ),
    )
    max_catchment_mismatch: Annotated[float, Profile.EXPERT] = Field(
        default=0.05,
        ge=0.0,
        description=(
            "Largest share of the delineated catchment's area the scored catchment "
            "may differ from it by, before the first solve."
        ),
    )
    heads_snap_radius_m: Annotated[float, Profile.EXPERT] = Field(
        default=100.0,
        gt=0.0,
        description=(
            "Under the 'heads' rule, the largest distance in metres between a mapped "
            "stream head and the centre of the cell it lands on. A head with no "
            "landing cell that close is lost and draws nothing."
        ),
    )
    heads_min_drained_area_km2: Annotated[float, Profile.EXPERT] = Field(
        default=0.02,
        ge=0.0,
        description=(
            "Under the 'heads' rule, the drained area in km2 a cell needs before a "
            "head may land on it. It keeps a head off a ridge cell next to its "
            "valley, whose descent would draw a stream down the hillslope."
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


DEFAULT_VISIBLE_FLOW = "1 L/s"
"""The routed discharge a cell must carry to flow in the two-bound mode.

No value is agreed in the literature. The closest precedent thresholds a
simulated discharge at 10 L/s (Zanetti et al., 2024, doi:10.1029/2023WR035631),
and field zero-flow thresholds of about 1 to 3 L/s are in use (Zimmer et al.,
2020, doi:10.1002/wat2.1436). One litre per second is the low end of both."""


@dataclass(frozen=True, slots=True)
class VisibleFlow:
    """The routed discharge below which a cell of the closure does not flow.

    Exactly one of the two is positive, or neither: ``discharge_m3_s`` is an
    absolute discharge, ``outlet_share`` a share of the routed discharge at the
    outlet at the same timestep. Neither positive is the geometric definition,
    the downstream closure alone. A cell size never enters it: the size of a
    cell is a numerical choice, the discharge a cartographer sees is not.
    """

    discharge_m3_s: float = 0.0
    outlet_share: float = 0.0

    def __post_init__(self) -> None:
        for name in ("discharge_m3_s", "outlet_share"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"visible flow {name} must be finite and positive, got {value}.")
        if self.discharge_m3_s > 0.0 and self.outlet_share > 0.0:
            raise ValueError("a visible flow is either a discharge or an outlet share, not both.")
        if self.outlet_share > 1.0:
            raise ValueError(
                f"a visible flow share of the outlet discharge is at most 100%, got "
                f"{100.0 * self.outlet_share:g}%."
            )

    @property
    def geometric(self) -> bool:
        """True when no discharge is required: the downstream closure alone."""
        return self.discharge_m3_s == 0.0 and self.outlet_share == 0.0

    def label(self) -> str:
        """Return the threshold as a user would write it."""
        if self.outlet_share > 0.0:
            return f"{100.0 * self.outlet_share:g}%"
        return f"{1000.0 * self.discharge_m3_s:g} L/s"


GEOMETRIC = VisibleFlow()
"""No visible-flow threshold: a cell flows when it is in the closure."""

_SHARE = re.compile(r"^\s*([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*%\s*$")
_HAS_UNIT = re.compile(r"[A-Za-z]")


def parse_visible_flow(value: str | VisibleFlow) -> VisibleFlow:
    """Read ``"1 L/s"``, ``"0.002 m3/s"`` or ``"1%"`` into a :class:`VisibleFlow`.

    A percentage is a share of the routed discharge at the outlet at the same
    timestep. A discharge needs its unit: a bare number would be read in
    litres by one user and in cubic meters by the next. ``"0 L/s"`` is the
    geometric definition.
    """
    if isinstance(value, VisibleFlow):
        return value
    text = str(value).strip()
    share = _SHARE.match(text)
    if share is not None:
        return VisibleFlow(outlet_share=float(share.group(1)) / 100.0)
    if not _HAS_UNIT.search(text):
        raise ValueError(
            f"visible_flow = {value!r} carries no unit. Write a discharge with its unit, "
            "such as '1 L/s', or a share of the outlet discharge, such as '1%'."
        )
    discharge, _ = parse_to_m3_per_s(text, location="visible_flow", default_unit="m3/s")
    return VisibleFlow(discharge_m3_s=float(discharge))


VALIDITY_PROVENANCE_CODE: dict[str, float] = {
    "auto": 0.0,
    "declared_accuracy": 2.0,
    "user": 3.0,
}
"""The number a trial publishes as ``validity_length_provenance``, since
components are floats."""

VALIDITY_PROVENANCE_BY_CODE: dict[float, str] = {
    code: name for name, code in VALIDITY_PROVENANCE_CODE.items()
}
"""The provenance a published code stands for."""


__all__ = (
    "DEFAULT_VISIBLE_FLOW",
    "GEOMETRIC",
    "STREAM_CRITERION_DEFAULTS",
    "VALIDITY_PROVENANCE_BY_CODE",
    "VALIDITY_PROVENANCE_CODE",
    "ObservedRasterization",
    "StreamCriterionDefaults",
    "VisibleFlow",
    "parse_visible_flow",
)
