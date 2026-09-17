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

Its ``layout`` is the one concession the first production callers won. The
geographic pipeline publishes ``watershed.tif`` and ``watershed.shp`` in one
directory that twenty other artefacts share, and every golden in the tree reads
them there. An engine that could only write ``mask.tif`` under a directory named
after the outlet would have made the port unadoptable, so the shape is declared
by the caller and refused when it cannot hold what is asked of it.
"""

from __future__ import annotations

import math
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


OUTLET_LAYER_NAME = "outlet.shp"
SNAPPED_OUTLET_LAYER_NAME = "outlet_snap.shp"
"""The two point layers every engine writes beside a catchment.

Named here rather than in each engine because a flat layout has to refuse a
catchment name that would land on one of them.
"""


@dataclass(frozen=True)
class CatchmentLayout:
    """Where the artefacts of one outlet land under the delineation directory.

    Declared rather than fixed, because the two shapes are not interchangeable
    and nothing in a mask says which one wrote it. A batch needs one directory
    per outlet or the second overwrites the first. A caller whose on-disk
    contract already publishes a name -- ``watershed.tif`` next to twenty other
    files in one geographic directory -- needs the files at that name, in that
    directory, and moving them would move every golden that reads them.
    """

    per_outlet_directory: bool
    mask_name: str
    boundary_name: str

    def __post_init__(self) -> None:
        for field_name, value, suffix in (
            ("mask_name", self.mask_name, ".tif"),
            ("boundary_name", self.boundary_name, ".shp"),
        ):
            if value != Path(value).name or value in ("", ".", ".."):
                raise TerrainRequestError(
                    f"{field_name}={value!r} is not a plain file name. A name carrying a "
                    "separator writes outside the directory the caller named."
                )
            if not value.endswith(suffix):
                raise TerrainRequestError(f"{field_name}={value!r} does not end in {suffix!r}.")
        if not self.per_outlet_directory and self.boundary_name in (
            OUTLET_LAYER_NAME,
            SNAPPED_OUTLET_LAYER_NAME,
        ):
            raise TerrainRequestError(
                f"boundary_name={self.boundary_name!r} is the name of a point layer an "
                "engine writes beside the catchment. In a flat layout the boundary would "
                "overwrite it, and the outlet the delineation ran from would be gone."
            )

    @classmethod
    def per_outlet(cls) -> CatchmentLayout:
        """One directory per outlet, the only shape a batch can be served in."""
        return cls(per_outlet_directory=True, mask_name="mask.tif", boundary_name="boundary.shp")

    @classmethod
    def flat(cls, *, mask_name: str, boundary_name: str) -> CatchmentLayout:
        """Both artefacts straight in the delineation directory, at named files."""
        return cls(
            per_outlet_directory=False,
            mask_name=mask_name,
            boundary_name=boundary_name,
        )

    def site_dir(self, out_dir: Path, outlet: Outlet) -> Path:
        """Return the directory this outlet's artefacts belong in."""
        return Path(out_dir) / outlet.outlet_id if self.per_outlet_directory else Path(out_dir)


DEFAULT_CATCHMENT_LAYOUT = CatchmentLayout.per_outlet()
"""The shape a caller gets when it does not say, and the only one a batch has."""


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
        layout: CatchmentLayout = DEFAULT_CATCHMENT_LAYOUT,
    ) -> tuple[Catchment, ...]:
        """Delineate every outlet against one accumulation, in input order.

        Each outlet is first snapped to the highest accumulation in its snap
        window, because a declared coordinate rarely lands on the talweg. The
        window is the one :func:`snap_window_cells` describes, and
        ``snap_distance_m`` is its **width**, not a maximum displacement.

        Requires a rank-preserving transform, which is all a snap compares, and
        a raster whose stored values still resolve the counts underneath them:
        see :data:`RANK_PRESERVING_TRANSFORMS` and
        :data:`LN_FLOAT32_COLLISION_COUNT`. ``layout`` says where the two
        artefacts of each outlet land.
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


RANK_PRESERVING_TRANSFORMS: frozenset[str] = frozenset({"none", "ln"})
"""Transforms that leave the order of the cells alone, in exact arithmetic.

Both are strictly increasing on the positive counts an accumulation carries, so
the cell that wins a snap window wins it under either -- until float32 storage
stops resolving neighbouring counts. That bound is measured, not argued, and
:data:`LN_FLOAT32_COLLISION_COUNT` carries it.
"""

LN_FLOAT32_COLLISION_COUNT = 1_049_558
"""First cell count whose natural logarithm collides with its successor's.

``float32(ln(1_049_558)) == float32(ln(1_049_559))``, and every smaller pair is
still distinct. Found by scanning every integer, not by sampling: an earlier
sampled probe of this campaign answered 1 059 591, which is **above** the true
value and would therefore have been a bound that does not protect.

Above it, a snap window holding two cells whose raw counts differ by one sees
one value, ties, and breaks the tie on something other than upstream area. A
25 m grid reaches it at about 656 km2 of contributing area, which no DEM in this
repository approaches -- the largest accumulates 28 230 -- and which regional
multi-basin work walks straight into.
"""

_MAX_TRANSFORMED_UNITS = "cells"
"""The only units :data:`LN_FLOAT32_COLLISION_COUNT` was measured for.

Multiplying a count by a cell area raises the magnitude of its logarithm without
changing the spacing between neighbours, so float32 gives up earlier: measured,
a 625 m2 cell collides at 525 125 counts and a 2 500 m2 cell at 524 705, against
1 049 558 for a bare count. One bound cannot cover them, and no caller in this
tree asks for a transformed area, so a transformed accumulation has to be in
cells.
"""


def require_rank_preserving(accumulation: FlowAccumulation, *, member: str) -> None:
    """Refuse an accumulation whose transform cannot order the cells.

    Checks the declaration only. What the raster actually carries is checked by
    :func:`require_resolvable_counts`, which needs the data.
    """
    if accumulation.transform not in RANK_PRESERVING_TRANSFORMS:
        raise TerrainProductError(
            f"{member} snaps to the largest accumulation of a window, so it needs a "
            f"transform that preserves the order of the cells; this one declares "
            f"transform={accumulation.transform!r}."
        )
    if accumulation.transform != "none" and accumulation.units != _MAX_TRANSFORMED_UNITS:
        raise TerrainProductError(
            f"{member} accepts a transformed accumulation only in "
            f"{_MAX_TRANSFORMED_UNITS!r}; this one declares "
            f"units={accumulation.units!r} under transform={accumulation.transform!r}. "
            "The count at which float32 stops resolving neighbouring cells depends on "
            "the cell area, and only the bare-count bound is measured."
        )


def require_resolvable_counts(
    accumulation: FlowAccumulation,
    *,
    max_stored_value: float,
    member: str,
) -> None:
    """Refuse a transformed accumulation whose values float32 can no longer order.

    ``max_stored_value`` is the largest value the **raster** carries, read back
    from the file. The comparison happens in that stored space rather than on a
    count recovered with ``exp``: exponentiating a value that turns out not to be
    a logarithm overflows, and the refusal would then quote a count no grid could
    hold instead of naming the real problem.

    Untransformed products are never refused: an integer count is exact in
    float32 well past any grid this runs on.
    """
    if accumulation.transform == "none":
        return
    bound = math.log(LN_FLOAT32_COLLISION_COUNT)
    if max_stored_value >= bound:
        raise TerrainProductError(
            f"{member} cannot rank this accumulation: its largest stored value is "
            f"{max_stored_value:.4f} under transform={accumulation.transform!r}, at or "
            f"above ln({LN_FLOAT32_COLLISION_COUNT}) = {bound:.4f}, where float32 stops "
            "telling neighbouring cell counts apart. Snapping would tie on cells that do "
            "not carry the same upstream area. Pass an accumulation with transform='none'."
        )


def require_batch(
    outlets: Sequence[Outlet],
    *,
    snap_distance_m: float,
    layout: CatchmentLayout = DEFAULT_CATCHMENT_LAYOUT,
) -> None:
    """Refuse a batch an engine cannot serve without overwriting its own output.

    Two outlets sharing an id write to one directory, and the first
    :class:`Catchment` then names a file holding the second one's mask. Nothing
    downstream can notice, so the refusal happens before anything is written.

    Ids are compared case-folded, because the collision is on a directory name
    and a case-insensitive filesystem makes ``Left`` and ``left`` one directory.
    Refusing the pair everywhere is the only answer that does not depend on
    which machine the job lands on.

    A flat layout has no directory to separate two outlets at all, so it holds
    exactly one.
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
    if not layout.per_outlet_directory and len(outlets) > 1:
        raise TerrainRequestError(
            f"A flat layout holds one catchment, and this batch carries {len(outlets)}. "
            "They would all write the same two files, and every product but the last "
            "would name a file holding another outlet's mask."
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
    "DEFAULT_CATCHMENT_LAYOUT",
    "OUTLET_LAYER_NAME",
    "SNAPPED_OUTLET_LAYER_NAME",
    "Catchment",
    "CatchmentLayout",
    "ConditionedDem",
    "ConditioningExtent",
    "ConditioningExtentKind",
    "ConditioningMethod",
    "DrainageDirections",
    "FlowAccumulation",
    "Outlet",
    "LN_FLOAT32_COLLISION_COUNT",
    "RANK_PRESERVING_TRANSFORMS",
    "PointerConvention",
    "StreamNetwork",
    "TerrainEngine",
    "engine_members",
    "missing_engine_members",
    "require_batch",
    "require_rank_preserving",
    "require_resolvable_counts",
    "require_untransformed",
    "snap_window_cells",
]
