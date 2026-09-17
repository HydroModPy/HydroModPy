"""The terrain port: what a flow-routing engine owes its callers, and no more.

Why eight members and not the facade
------------------------------------
The Whitebox facade this port stands in front of exposes 66 public methods over
its three thematic sub-backends: 30 on ``raster``, 22 on ``delineation``, 14 on
``flow``. A port designed against that census is a design exercise, not a
boundary. This one is sized by what the two real callers of the
chain ask for -- ``build_regional_flow_products`` (a conditioned DEM, a pointer
and an accumulation raster) and ``extract_catchment_from_point`` (a snapped
outlet and a watershed) -- plus the stream threshold that ``river_network``
needs. Everything else in the facade stays where it is and keeps its callers.

Why the products carry declared fields
--------------------------------------
``drainage_directions`` and ``flow_accumulation`` are two members and not one
because they emit two rasters whose meaning cannot be recovered from their
values. Measured on this tree:

- ``d8_flow_accum(out_type="cells")`` counts the cell itself, so a plane
  draining east reads 1, 2, 3 ... along a row;
- ``log=True`` applies the **natural** logarithm, not a base-10 one. The regional
  accumulation raster HydroModPy writes today is therefore ``ln(cells)``, and a
  caller that thresholds it with a cell count silently selects nothing: the
  whole raster of a 961-cell catchment tops out at 6.87. ``river_network``
  escapes that only by recomputing an untransformed accumulation of its own.

So ``units`` and ``transform`` are fields of the product, the vocabulary names
``ln`` rather than the ``log10`` a reader would assume, and ``stream_network``
refuses a transformed product instead of emptying the network. That refusal is
what replaces ``looks_log_scaled``, the runtime shape heuristic that guessed the
transform back from the values it found.

What is deliberately absent
---------------------------
No ``weights`` argument on ``flow_accumulation``: no engine on this tree can
serve one, and a declared parameter no implementation honours is the kind of
false declaration this campaign spent two phases removing. No engine registry
either: a selection point with no caller is decoration, and it arrives with the
capability that has to choose.

Batch delineation means shared products
---------------------------------------
``delineate`` takes N outlets against one accumulation because the products are
what is expensive, not the traversal. An engine is free to serve them in one
call or in a loop; what the signature forbids is conditioning a DEM once per
outlet.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, Protocol, runtime_checkable

from hydromodpy.core.exceptions import TerrainProductError, TerrainRequestError

ConditioningMethod = Literal["fill", "breach"]
"""``fill`` raises depression cells until each drains; ``breach`` carves out."""

PointerConvention = Literal["d8_wbt", "d8_esri", "dinf"]
"""``d8_wbt`` is the encoding of ``spatial.geographic.core.d8.WBT_D8_OFFSETS``."""

AccumulationUnits = Literal["cells", "m2"]
"""Upstream cell count, or that count times the cell area."""

AccumulationTransform = Literal["none", "ln"]
"""``ln`` is the natural logarithm, which is what the Whitebox chain emits."""

ConditioningExtentKind = Literal["regional", "per_outlet_buffer"]

_SAFE_OUTLET_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_MAX_OUTLET_ID = 64
"""Longest id an engine will make a directory name of.

``NAME_MAX`` is 255 on the filesystems this project runs on, but the directory
sits inside a job directory that has its own path budget, and the test scratch
root already guards the 259-character Windows limit. 64 is a declared choice,
and a refusal here is the difference between a named error and an
``OSError: File name too long`` from ``mkdir``.
"""


@dataclass(frozen=True)
class ConditioningExtent:
    """The footprint a conditioning pass is allowed to alter.

    Declared rather than implied: filling a regional DEM and filling a buffer
    around one outlet do not produce the same catchment, and nothing in the
    output says which was done.
    """

    kind: ConditioningExtentKind
    buffer_distance_m: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("regional", "per_outlet_buffer"):
            raise TerrainRequestError(
                f"Unknown conditioning extent {self.kind!r}. "
                "Expected 'regional' or 'per_outlet_buffer'."
            )
        if self.kind == "regional" and self.buffer_distance_m is not None:
            raise TerrainRequestError("A regional conditioning extent carries no buffer distance.")
        if self.kind == "per_outlet_buffer" and not (
            self.buffer_distance_m is not None and self.buffer_distance_m > 0.0
        ):
            raise TerrainRequestError(
                "A per-outlet conditioning extent needs a buffer distance > 0 m."
            )

    @classmethod
    def regional(cls) -> ConditioningExtent:
        """Condition the whole DEM, which is what every caller does today."""
        return cls(kind="regional")

    @classmethod
    def per_outlet_buffer(cls, distance_m: float) -> ConditioningExtent:
        """Condition a buffer of ``distance_m`` around each outlet."""
        return cls(kind="per_outlet_buffer", buffer_distance_m=float(distance_m))


@dataclass(frozen=True)
class ConditionedDem:
    """A hydrologically conditioned DEM and the two choices that produced it."""

    path: Path
    method: ConditioningMethod
    extent: ConditioningExtent
    crs: str
    """CRS every raster derived from this DEM carries, as a user-input string."""


@dataclass(frozen=True)
class DrainageDirections:
    """A flow-pointer raster that says which code table it was written with."""

    path: Path
    pointer_convention: PointerConvention
    conditioned_dem: ConditionedDem
    """The DEM this pointer descends, kept so a product chain is traceable."""


@dataclass(frozen=True)
class FlowAccumulation:
    """An accumulation raster that declares its units and its transform."""

    path: Path
    units: AccumulationUnits
    transform: AccumulationTransform
    directions: DrainageDirections
    nodata: float
    """The value the raster marks as absent.

    Declared because it cannot be chosen freely: an accumulation in cells is
    never below 1, but ``ln(1)`` is 0, so a nodata of 0 turns every headwater
    cell into a hole under any masked read. An engine picks a value no product
    of any transform can produce, and says which.
    """


@dataclass(frozen=True)
class StreamNetwork:
    """A channel mask and the threshold that selected it.

    ``threshold_units`` repeats the units of the accumulation the threshold was
    compared against, because a stream mask outlives the raster it came from.
    """

    path: Path
    threshold: float
    threshold_units: AccumulationUnits
    directions: DrainageDirections


@dataclass(frozen=True)
class Outlet:
    """One point to delineate from, in the CRS of the conditioned DEM."""

    outlet_id: str
    x: float
    y: float

    def __post_init__(self) -> None:
        if not _SAFE_OUTLET_ID.match(self.outlet_id):
            raise TerrainRequestError(
                f"Outlet id {self.outlet_id!r} is not usable as a directory name. "
                "Expected letters, digits, '_' and '-', starting with a letter or digit."
            )
        if len(self.outlet_id) > _MAX_OUTLET_ID:
            raise TerrainRequestError(
                f"Outlet id is {len(self.outlet_id)} characters, over the "
                f"{_MAX_OUTLET_ID} an engine will make a directory name of."
            )


@dataclass(frozen=True)
class Catchment:
    """The catchment of one outlet, and where the delineation really started.

    ``mask_path`` holds ``1`` on the catchment and the raster nodata elsewhere.
    ``boundary_path`` holds its polygons. The snapped coordinate is reported
    because it, and not the declared one, is what was delineated -- the same
    reason ``CatchmentFromPointProducts`` carries it.
    """

    outlet: Outlet
    mask_path: Path
    boundary_path: Path
    cell_count: int
    area_m2: float
    snapped_x: float
    snapped_y: float
    snap_distance_m: float


@runtime_checkable
class TerrainEngine(Protocol):
    """One engine routes flow over a DEM and delineates from outlets.

    Engines conform structurally: there is no base class, just five methods and
    two ``ClassVar`` strings that identify the implementation. A third-party
    engine needs no import from HydroModPy beyond this module.

    Every member writes to the path the caller names and returns the product
    that describes what it wrote. An engine that cannot serve an option raises
    :class:`~hydromodpy.core.exceptions.TerrainCapabilityError` naming it, and
    one handed a product it cannot use raises
    :class:`~hydromodpy.core.exceptions.TerrainProductError`. Neither is ever
    answered by a capability probe on the object.
    """

    engine_id: ClassVar[str]
    engine_version: ClassVar[str]

    def engine_digest(self) -> str:
        """Return a stable digest of this engine build.

        Identifies the code that produced a product, not the request that asked
        for it: two engines never share one, and it moves when the underlying
        library version moves.
        """
        ...

    def condition_dem(
        self,
        dem: Path,
        *,
        method: ConditioningMethod,
        extent: ConditioningExtent,
        out: Path,
    ) -> ConditionedDem:
        """Remove the depressions that stop a cell from draining.

        Absent cells are not a drainage target. A depression whose only low way
        out crosses a nodata hole -- a lake or a sea mask inside the domain --
        therefore stays a depression, and the cell keeps no downstream
        neighbour. Measured identical on both engines shipped here, so the port
        states it rather than either one hiding it.
        """
        ...

    def drainage_directions(
        self,
        conditioned: ConditionedDem,
        *,
        out: Path,
    ) -> DrainageDirections:
        """Write the flow pointer of a conditioned DEM."""
        ...

    def flow_accumulation(
        self,
        directions: DrainageDirections,
        *,
        units: AccumulationUnits,
        transform: AccumulationTransform,
        out: Path,
    ) -> FlowAccumulation:
        """Accumulate along ``directions``, in the declared units and transform.

        Counting includes the cell itself, so the headwater value is ``1`` and
        an outlet draining the whole domain reads the cell count of the domain.
        """
        ...

    def stream_network(
        self,
        accumulation: FlowAccumulation,
        *,
        threshold: float,
        out: Path,
    ) -> StreamNetwork:
        """Select the cells that carry strictly more than ``threshold``.

        Requires ``transform="none"``: a threshold compared against a
        transformed accumulation selects the wrong cells, or none at all.
        """
        ...

    def delineate(
        self,
        accumulation: FlowAccumulation,
        outlets: Sequence[Outlet],
        *,
        out_dir: Path,
        snap_distance_m: float,
    ) -> tuple[Catchment, ...]:
        """Delineate every outlet against one accumulation, in input order.

        Each outlet is first snapped to the highest accumulation in its snap
        window, because a declared coordinate rarely lands on the talweg. The
        window is the one :func:`snap_window_cells` describes, and
        ``snap_distance_m`` is its **width**, not a maximum displacement.

        Requires ``units="cells"`` and ``transform="none"`` so the snap compares
        comparable numbers.
        """
        ...


def require_untransformed(accumulation: FlowAccumulation, *, member: str) -> None:
    """Refuse a transformed accumulation where a raw one is needed."""
    if accumulation.transform != "none":
        raise TerrainProductError(
            f"{member} needs an untransformed accumulation; this one declares "
            f"transform={accumulation.transform!r}. A threshold compared against a "
            "transformed raster selects the wrong cells."
        )


def require_cell_counts(accumulation: FlowAccumulation, *, member: str) -> None:
    """Refuse an accumulation that is not an untransformed cell count."""
    require_untransformed(accumulation, member=member)
    if accumulation.units != "cells":
        raise TerrainProductError(
            f"{member} needs an accumulation in cells; this one declares "
            f"units={accumulation.units!r}."
        )


def require_batch(outlets: Sequence[Outlet], *, snap_distance_m: float) -> None:
    """Refuse a batch an engine cannot serve without overwriting its own output.

    Two outlets sharing an id write to one directory, and the first
    :class:`Catchment` then names a file holding the second one's mask. Nothing
    downstream can notice, so the refusal happens before anything is written.

    Ids are compared case-folded, because the collision is on a directory name
    and a case-insensitive filesystem makes ``Left`` and ``left`` one directory.
    Refusing the pair everywhere is the only answer that does not depend on
    which machine the job lands on.
    """
    if not outlets:
        raise TerrainRequestError("delineate needs at least one outlet.")
    if snap_distance_m <= 0.0:
        raise TerrainRequestError("A snap distance must be > 0 m.")
    seen: set[str] = set()
    collisions: list[str] = []
    for outlet in outlets:
        folded = outlet.outlet_id.casefold()
        if folded in seen:
            collisions.append(outlet.outlet_id)
        seen.add(folded)
    if collisions:
        raise TerrainRequestError(
            "Outlet ids must be unique within one batch, case-folded; "
            f"repeated: {', '.join(sorted(collisions))}."
        )


def snap_window_cells(snap_distance_m: float, *, dx: float, dy: float) -> tuple[int, int]:
    """Return the half-width, in cells, of the window a snap searches.

    ``floor(snap_distance_m / (2 * cell size))`` per axis. This is not a
    convention chosen here, it is what ``snap_pour_points`` was measured to do
    on a 25 m grid: no displacement at all up to 25 m, one cell from 50 m, two
    cells from 100 m. So the parameter every HydroModPy configuration calls
    ``snap_dist`` is the **width** of a square window, and the docstring that
    called it a maximum snapping distance was wrong twice over -- a value equal
    to one cell size snaps nowhere, and a value of 100 m on a 25 m grid can move
    an outlet 70.7 m, diagonally.

    On a grid whose two resolutions differ, each axis gets its own half-width.
    What Whitebox does in that case is not measured here.
    """
    if snap_distance_m <= 0.0:
        raise TerrainRequestError("A snap distance must be > 0 m.")
    return (
        int(snap_distance_m // (2.0 * dy)),
        int(snap_distance_m // (2.0 * dx)),
    )


def engine_members() -> tuple[str, ...]:
    """Return the member names :class:`TerrainEngine` requires.

    Derived from the Protocol so a member added there is named by the refusal
    message without a second list to keep in step.
    """
    annotated = set(TerrainEngine.__annotations__)
    defined = {
        name
        for name, value in vars(TerrainEngine).items()
        if callable(value) and not name.startswith("_")
    }
    return tuple(sorted(annotated | defined))


def missing_engine_members(candidate: object) -> tuple[str, ...]:
    """Return the members *candidate* has no attribute for.

    Presence only, for a refusal message. Conformance is decided by
    ``isinstance(candidate, TerrainEngine)``, which also rejects a member bound
    to ``None``: an empty tuple does not mean the candidate conforms.
    """
    return tuple(name for name in engine_members() if not hasattr(candidate, name))


__all__ = [
    "AccumulationTransform",
    "AccumulationUnits",
    "Catchment",
    "ConditionedDem",
    "ConditioningExtent",
    "ConditioningExtentKind",
    "ConditioningMethod",
    "DrainageDirections",
    "FlowAccumulation",
    "Outlet",
    "PointerConvention",
    "StreamNetwork",
    "TerrainEngine",
    "engine_members",
    "missing_engine_members",
    "require_batch",
    "require_cell_counts",
    "require_untransformed",
    "snap_window_cells",
]
