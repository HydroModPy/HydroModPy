"""Terrain port: five members, the product types and the checks the two engines share.

The README of this folder holds the facts a caller must not guess, such as the natural
logarithm of ``ln``, the width of a snap window and the float32 bound of an accumulation.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import ClassVar, Literal, Protocol, runtime_checkable

from hydromodpy.core.exceptions import (
    TerrainCapabilityError,
    TerrainProductError,
    TerrainRequestError,
)

MASK_INSIDE = 1
MASK_NODATA = -32768  # absent cell of every mask and every pointer, as Whitebox writes it
D8_WBT_OFFSETS: dict[int, tuple[int, int]] = {  # (drow, dcol), drow downward, NOT the ESRI table
    1: (-1, 1),  # NE
    2: (0, 1),  # E
    4: (1, 1),  # SE
    8: (1, 0),  # S
    16: (1, -1),  # SW
    32: (0, -1),  # W
    64: (-1, -1),  # NW
    128: (-1, 0),  # N
}
LN_FLOAT32_COLLISION_COUNT = 1_049_558  # first count whose float32 ln equals its successor's
RANK_PRESERVING_TRANSFORMS = frozenset({"none", "ln"})
OUTLET_LAYER_NAME = "outlet.shp"
SNAPPED_OUTLET_LAYER_NAME = "outlet_snap.shp"
OUTLET_LAYER_COLUMNS = ("outlet_id", "x", "y")
_SAFE_OUTLET_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_MAX_OUTLET_ID = 64

PointerConvention = Literal["d8_wbt", "d8_esri", "dinf"]
AccumulationUnits = Literal["cells", "m2"]
AccumulationTransform = Literal["none", "ln"]
ConditioningExtentKind = Literal["regional", "per_outlet_buffer"]


def _ensure(ok: bool, message: str, error: type[Exception] = TerrainRequestError) -> None:
    if not ok:
        raise error(message)


@dataclass(frozen=True)
class CappedBreach:
    """Least-cost breach within a cap, then a fill of what the cap refused (Lindsay 2016).

    ``max_depth_m`` is the cumulative lowering of one path, not the depth of one cell.
    ``max_distance_m`` is counted in cells along the path.
    """

    max_depth_m: float
    max_distance_m: float

    def __post_init__(self) -> None:
        for name in ("max_depth_m", "max_distance_m"):
            value = getattr(self, name)
            _ensure(
                math.isfinite(value) and value > 0.0,
                f"A capped breach needs {name} > 0 and finite, got {value!r}.",
            )


ConditioningMethod = Literal["fill", "breach", "provided"] | CappedBreach
"""``provided`` is a DEM the user conditioned: no engine runs, see ``ConditionedDem.provided``."""


@dataclass(frozen=True)
class ConditioningExtent:
    """The footprint a conditioning pass may alter."""

    kind: ConditioningExtentKind
    buffer_distance_m: float | None = None

    def __post_init__(self) -> None:
        _ensure(
            self.kind in ("regional", "per_outlet_buffer"),
            f"Unknown conditioning extent {self.kind!r}. Expected 'regional' or 'per_outlet_buffer'.",
        )
        buffered = self.kind == "per_outlet_buffer"
        _ensure(
            not buffered or (self.buffer_distance_m or 0.0) > 0.0,
            "A per-outlet conditioning extent needs a buffer distance > 0 m.",
        )
        _ensure(
            buffered or self.buffer_distance_m is None,
            "A regional conditioning extent carries no buffer distance.",
        )

    @classmethod
    def regional(cls) -> ConditioningExtent:
        return cls("regional")

    @classmethod
    def per_outlet_buffer(cls, distance_m: float) -> ConditioningExtent:
        return cls("per_outlet_buffer", float(distance_m))


@dataclass(frozen=True)
class CappedBreachReport:
    """What a capped breach did, measured on the two rasters (cells moved by > threshold)."""

    cells_lowered: int
    cells_raised: int
    max_lowering_m: float
    max_raise_m: float
    max_dist_cells: int
    max_cost_m: float
    move_threshold_m: float

    @classmethod
    def from_document(cls, document: Mapping[str, float]) -> CappedBreachReport:
        """Read back what ``to_document`` wrote. A key this class does not know is ignored."""
        counts = ("cells_lowered", "cells_raised", "max_dist_cells")
        return cls(
            **{
                f.name: int(document[f.name]) if f.name in counts else float(document[f.name])
                for f in fields(cls)
            }
        )

    def to_document(self) -> dict[str, float | int]:
        return asdict(self)


@dataclass(frozen=True)
class ConditionedDem:
    """A DEM that drains, and the two choices that made it so."""

    path: Path
    method: ConditioningMethod
    extent: ConditioningExtent
    crs: str  # CRS of every raster derived from this DEM, as a user-input string
    breach_report: CappedBreachReport | None = None

    @classmethod
    def provided(cls, path: Path) -> ConditionedDem:
        """Take a DEM the user conditioned as it is. The CRS is read from the file."""
        from hydromodpy.catchment.terrain.artifacts import raster_crs

        return cls(Path(path), "provided", ConditioningExtent.regional(), raster_crs(path))


@dataclass(frozen=True)
class DrainageDirections:
    path: Path
    pointer_convention: PointerConvention
    conditioned_dem: ConditionedDem


@dataclass(frozen=True)
class FlowAccumulation:
    """Units and transform are declared. ``nodata`` is never a value a product can hold."""

    path: Path
    units: AccumulationUnits
    transform: AccumulationTransform
    directions: DrainageDirections
    nodata: float


@dataclass(frozen=True)
class StreamNetwork:
    path: Path
    threshold: float
    threshold_units: AccumulationUnits
    directions: DrainageDirections


@dataclass(frozen=True)
class JensonSnap:
    """Snap an outlet to the nearest cell of ``streams`` (Jenson and Domingue 1988)."""

    streams: StreamNetwork


SnapMethod = Literal["window"] | JensonSnap
"""``window`` takes the largest accumulation of the snap window."""


@dataclass(frozen=True)
class Outlet:
    """One point to delineate from, in the CRS of the conditioned DEM."""

    outlet_id: str
    x: float
    y: float

    def __post_init__(self) -> None:
        _ensure(
            bool(_SAFE_OUTLET_ID.match(self.outlet_id)),
            f"Outlet id {self.outlet_id!r} is not usable as a directory name. "
            "Expected letters, digits, '_' and '-', starting with a letter or digit.",
        )
        _ensure(
            len(self.outlet_id) <= _MAX_OUTLET_ID,
            f"Outlet id is {len(self.outlet_id)} characters, over the "
            f"{_MAX_OUTLET_ID} an engine will make a directory name of.",
        )


@dataclass(frozen=True)
class CatchmentLayout:
    """Where the artifacts of one outlet land. A batch needs one directory per outlet."""

    per_outlet_directory: bool
    mask_name: str
    boundary_name: str

    def __post_init__(self) -> None:
        for field, value, suffix in (
            ("mask_name", self.mask_name, ".tif"),
            ("boundary_name", self.boundary_name, ".shp"),
        ):
            _ensure(
                value == Path(value).name and value not in ("", ".", ".."),
                f"{field}={value!r} is not a plain file name. "
                "A name carrying a separator writes outside the directory the caller named.",
            )
            _ensure(value.endswith(suffix), f"{field}={value!r} does not end in {suffix!r}.")
        _ensure(
            self.per_outlet_directory
            or self.boundary_name not in (OUTLET_LAYER_NAME, SNAPPED_OUTLET_LAYER_NAME),
            f"boundary_name={self.boundary_name!r} is the name of a point layer an engine "
            "writes beside the catchment. In a flat layout it would overwrite the outlet.",
        )

    @classmethod
    def per_outlet(cls) -> CatchmentLayout:
        return cls(True, "mask.tif", "boundary.shp")

    @classmethod
    def flat(cls, *, mask_name: str, boundary_name: str) -> CatchmentLayout:
        return cls(False, mask_name, boundary_name)

    def site_dir(self, out_dir: Path, outlet: Outlet) -> Path:
        return Path(out_dir) / outlet.outlet_id if self.per_outlet_directory else Path(out_dir)

    def make_site(self, out_dir: Path, outlet: Outlet) -> tuple[Path, Path, Path]:
        """Create the directory of an outlet. Return it, then its mask and boundary files."""
        site = self.site_dir(out_dir, outlet)
        site.mkdir(parents=True, exist_ok=True)
        return site, site / self.mask_name, site / self.boundary_name


DEFAULT_CATCHMENT_LAYOUT = CatchmentLayout.per_outlet()


@dataclass(frozen=True)
class Catchment:
    """One catchment. The snapped point, not the declared one, is what was delineated."""

    outlet: Outlet
    mask_path: Path
    boundary_path: Path
    cell_count: int
    area_m2: float
    snapped_x: float
    snapped_y: float
    snap_distance_m: float

    @classmethod
    def from_files(
        cls, outlet: Outlet, mask_path: Path, boundary_path: Path, x: float, y: float
    ) -> Catchment:
        """Build the catchment of a snapped point. Count and area are read back from the files."""
        from hydromodpy.catchment.terrain.artifacts import boundary_area_m2, mask_cell_count

        return cls(
            outlet,
            mask_path,
            boundary_path,
            mask_cell_count(mask_path),
            boundary_area_m2(boundary_path),
            x,
            y,
            math.hypot(x - outlet.x, y - outlet.y),
        )


@runtime_checkable
class TerrainEngine(Protocol):
    """Five members and two identifying strings. Every member writes where the caller says.

    An option an engine cannot serve raises ``TerrainCapabilityError`` naming it. A product it
    cannot use raises ``TerrainProductError``.
    """

    engine_id: ClassVar[str]
    engine_version: ClassVar[str]

    def engine_digest(self) -> str:
        """Identify the code that made a product, not the request. Moves with the library."""
        ...

    def condition_dem(
        self, dem: Path, *, method: ConditioningMethod, extent: ConditioningExtent, out: Path
    ) -> ConditionedDem:
        """Remove the depressions. A nodata hole is no drainage target, on both engines.

        ``method="provided"`` is refused: build that product with ``ConditionedDem.provided``.
        """
        ...

    def drainage_directions(
        self, conditioned: ConditionedDem, *, out: Path
    ) -> DrainageDirections: ...

    def flow_accumulation(
        self,
        directions: DrainageDirections,
        *,
        units: AccumulationUnits,
        transform: AccumulationTransform,
        out: Path,
    ) -> FlowAccumulation: ...

    def stream_network(
        self, accumulation: FlowAccumulation, *, threshold: float, out: Path
    ) -> StreamNetwork:
        """Cells that carry strictly more than ``threshold``. Needs ``transform="none"``."""
        ...

    def delineate(
        self,
        accumulation: FlowAccumulation,
        outlets: Sequence[Outlet],
        *,
        out_dir: Path,
        snap_distance_m: float,
        snap: SnapMethod = "window",
        layout: CatchmentLayout = DEFAULT_CATCHMENT_LAYOUT,
    ) -> tuple[Catchment, ...]:
        """Snap each outlet inside its window, then delineate, in input order."""
        ...


def stamp(engine_id: str, engine_version: str, convention: str = "d8_wbt") -> str:
    """The ``engine_digest`` both engines share: id, library version and pointer table."""
    return hashlib.sha256("\n".join((engine_id, engine_version, convention)).encode()).hexdigest()


def require_conditioning(
    engine_id: str,
    method: ConditioningMethod,
    extent: ConditioningExtent,
    *,
    serves: tuple[str, ...],
) -> None:
    """Refuse an extent or method the engine does not serve. ``capped`` names a CappedBreach."""
    _ensure(
        method != "provided",
        f"{engine_id} conditions no 'provided' DEM; build it with ConditionedDem.provided(path).",
    )
    _ensure(
        extent.kind == "regional",
        f"{engine_id} conditions the whole DEM; extent {extent.kind!r} is not implemented.",
        TerrainCapabilityError,
    )
    name = "capped" if isinstance(method, CappedBreach) else method
    _ensure(
        name in serves,
        f"{engine_id} conditions with {', '.join(serves)}; "
        f"{'capped breach' if name == 'capped' else repr(method)} is not implemented.",
        TerrainCapabilityError,
    )


def require_accumulation(engine_id: str, units: str, transform: str) -> None:
    _ensure(
        units in ("cells", "m2") and transform in ("none", "ln"),
        f"{engine_id} accumulates in 'cells' or 'm2' with 'none' or 'ln'; "
        f"{units!r} with {transform!r} is not implemented.",
        TerrainCapabilityError,
    )


def require_stream(accumulation: FlowAccumulation, threshold: float) -> None:
    _ensure(
        accumulation.transform == "none",
        "stream_network needs an untransformed accumulation; this one declares "
        f"transform={accumulation.transform!r}. A threshold on a transformed raster "
        "selects the wrong cells.",
        TerrainProductError,
    )
    _ensure(threshold > 0.0, "A stream threshold must be > 0.")


def require_resolvable_counts(
    accumulation: FlowAccumulation, *, max_stored_value: float, member: str
) -> None:
    """Refuse a transformed accumulation whose largest stored value float32 cannot order."""
    bound = math.log(LN_FLOAT32_COLLISION_COUNT)
    _ensure(
        accumulation.transform == "none" or not max_stored_value >= bound,
        f"{member} cannot rank this accumulation: its largest stored value is "
        f"{max_stored_value:.4f} under transform={accumulation.transform!r}, at or above "
        f"ln({LN_FLOAT32_COLLISION_COUNT}) = {bound:.4f}, where float32 stops telling "
        "neighbouring cell counts apart. Pass an accumulation with transform='none'.",
        TerrainProductError,
    )


def require_delineable(
    accumulation: FlowAccumulation,
    outlets: Sequence[Outlet],
    *,
    snap: SnapMethod,
    snap_distance_m: float,
    layout: CatchmentLayout,
) -> None:
    """Refuse a request the snap cannot rank or the layout cannot hold, before any write.

    The raster is read only for a window snap on a transformed accumulation, to find the
    largest value around the outlets.
    """
    if isinstance(snap, JensonSnap):
        _ensure(
            snap.streams.directions == accumulation.directions,
            "delineate snaps onto a stream network drawn from another pointer than the one it "
            "delineates down. Draw the network from this accumulation, with stream_network.",
            TerrainProductError,
        )
    else:
        _ensure(
            snap == "window", f"Unknown snap method {snap!r}. Expected 'window' or a JensonSnap."
        )
        _ensure(
            accumulation.transform in RANK_PRESERVING_TRANSFORMS,
            "delineate snaps to the largest accumulation of a window, so it needs a transform "
            "that preserves the order of the cells; this one declares "
            f"transform={accumulation.transform!r}.",
            TerrainProductError,
        )
        _ensure(
            accumulation.transform == "none" or accumulation.units == "cells",
            "delineate accepts a transformed accumulation only in 'cells'; this one declares "
            f"units={accumulation.units!r} under transform={accumulation.transform!r}. "
            "Only the bare-count float32 bound is measured.",
            TerrainProductError,
        )
    _ensure(len(outlets) > 0, "delineate needs at least one outlet.")
    _ensure(snap_distance_m > 0.0, "A snap distance must be > 0 m.")
    seen = Counter(outlet.outlet_id.casefold() for outlet in outlets)
    repeated = sorted({o.outlet_id for o in outlets if seen[o.outlet_id.casefold()] > 1})
    _ensure(
        not repeated,
        f"Outlet ids must be unique within one batch, case-folded; repeated: {', '.join(repeated)}.",
    )
    _ensure(
        layout.per_outlet_directory or len(outlets) == 1,
        f"A flat layout holds one catchment, and this batch carries {len(outlets)}.",
    )
    if not isinstance(snap, JensonSnap) and accumulation.transform != "none":
        from hydromodpy.catchment.terrain.artifacts import raster_max_near

        points = [(outlet.x, outlet.y) for outlet in outlets]
        largest = raster_max_near(accumulation.path, points, snap_distance_m)
        require_resolvable_counts(accumulation, max_stored_value=largest, member="delineate")


def stream_window_refusal(outlet: Outlet, snap_distance_m: float, snap: JensonSnap) -> str:
    """The message of an outlet with no stream cell in its window, said once for every engine."""
    streams = snap.streams
    return (
        f"Snapping outlet {outlet.outlet_id!r} found no cell of the stream network in a snap "
        f"window of {snap_distance_m} m around ({outlet.x}, {outlet.y}). The network is the "
        f"cells that drain more than {streams.threshold:g} {streams.threshold_units}."
    )


def snap_window_cells(snap_distance_m: float, *, dx: float, dy: float) -> tuple[int, int]:
    """Half-width in cells of the snap window, per axis (measured on a 25 m grid)."""
    _ensure(snap_distance_m > 0.0, "A snap distance must be > 0 m.")
    return int(snap_distance_m // (2.0 * dy)), int(snap_distance_m // (2.0 * dx))


def engine_members() -> tuple[str, ...]:
    """The member names ``TerrainEngine`` requires, read from the Protocol."""
    defined = {n for n, v in vars(TerrainEngine).items() if callable(v) and not n.startswith("_")}
    return tuple(sorted(set(TerrainEngine.__annotations__) | defined))


def missing_engine_members(candidate: object) -> tuple[str, ...]:
    """The members ``candidate`` has no attribute for. Presence only, not conformance."""
    return tuple(name for name in engine_members() if not hasattr(candidate, name))
