"""The data-source port: what a fetch owes its callers, and no more.

One form for every source, the port the campaign measured into place: a request
carries what varies between two calls to one source, a constructor carries what
varies between two sources, and eight declarations answer the four questions
the census of phase 3 found (which CRS the extent is in, what the extent is
called, whether a period is part of the request, what comes back). Why the port
took that shape, with the numbers, is the README of this folder.

Two rules the declarations carry. A source is registered under its
``section`` and its ``source_id``, the two parts of its identity, so a word
that serves nine sections serves each of them under its own key. And a
shipped source writes no host of its own: it reads them from
:func:`shipped_hosts`, the one table the licence pages also read. The registry
is :mod:`hydromodpy.data.source.registry`, which this module must not depend
on, and the check that a declaration matches a real fetch is
``tests/ports/test_data_source.py``.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal, Protocol, runtime_checkable

from hydromodpy.core.exceptions import (
    DataCapabilityError,
    DataProductError,
    DataRequestError,
)
from hydromodpy.core.runtime.bounds import Bounds

if TYPE_CHECKING:
    import geopandas as gpd

    from hydromodpy.data.contracts.file_record import FileRecord
    from hydromodpy.data.contracts.spatial_field import FieldRecord
    from hydromodpy.data.contracts.timeseries import PointRecord


PayloadKind = Literal["points", "fields", "features", "files"]
"""The four shapes a fetch comes back in.

``Path`` and ``list[Path]`` of the census collapse into one kind on purpose:
the difference between a source that hands back one file and one that hands
back three says nothing about how the result is read, and a caller that has to
branch on it branches on an accident of the provider. A single file is a
one-element tuple.
"""

Selector = Literal["extent", "station_ids"]
"""What a source can be asked *for*, beside the period.

Both, in the Hub'Eau adapters, where ``station_ids`` short-circuits bbox
discovery entirely. Only ``extent`` everywhere else.
"""

PeriodNeed = Literal["required", "refused", "optional"]
"""Whether a period is part of the request.

Three values: ``required`` (time series, forcings), ``refused`` (DEM, river network),
or ``optional`` (constant, synthetic, SHOM).
"""

ALL_PAYLOAD_KINDS: tuple[PayloadKind, ...] = ("points", "fields", "features", "files")
ALL_SELECTORS: tuple[Selector, ...] = ("extent", "station_ids")
ALL_PERIOD_NEEDS: tuple[PeriodNeed, ...] = ("required", "refused", "optional")


# --------------------------------------------------------------------------- #
# What a request is made of
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Extent:
    """A bounding box that says which CRS it is expressed in.

    ``crs`` is kept as the user-input string rather than a ``pyproj.CRS``, so
    the value types of this port stay importable without pyproj and a
    third-party source can build one from a configuration file. It is resolved
    only when :meth:`to_crs` actually has to convert.

    **A box that crosses the antimeridian cannot be expressed here**, and is
    refused as inverted. Every provider this port serves is French-mainland
    only, so the case is a limit and not a defect today; the day one is not,
    the answer is two extents and not an ``xmin`` above its ``xmax``.
    """

    xmin: float
    ymin: float
    xmax: float
    ymax: float
    crs: str

    def __post_init__(self) -> None:
        for name in ("xmin", "ymin", "xmax", "ymax"):
            raw = getattr(self, name)
            if isinstance(raw, bool):
                raise DataRequestError(f"Extent {name}={raw!r} is a boolean, not a coordinate.")
            if not isinstance(raw, numbers.Real):
                raise DataRequestError(f"Extent {name}={raw!r} is not a number.")
            value = float(raw)
            if not math.isfinite(value):
                raise DataRequestError(f"Extent {name}={raw!r} is not finite.")
            object.__setattr__(self, name, value)
        if not isinstance(self.crs, str) or not self.crs.strip():
            raise DataRequestError(
                "An extent carries the CRS it is expressed in; this one declares "
                f"crs={self.crs!r}. A bare bounding box is what this port exists to refuse."
            )
        if self.xmin >= self.xmax or self.ymin >= self.ymax:
            raise DataRequestError(
                f"Extent ({self.xmin}, {self.ymin}, {self.xmax}, {self.ymax}) is empty or "
                "inverted. Expected xmin < xmax and ymin < ymax."
            )

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """The four floats, in the order every fetch function of this tree reads."""
        return (self.xmin, self.ymin, self.xmax, self.ymax)

    def to_crs(self, crs: str) -> Extent:
        """Return this extent in ``crs``, densifying its edges.

        The returned extent always carries ``crs`` **as it was asked for**, so
        a source that converts a caller's ``"epsg:4326"`` into its own
        ``"EPSG:4326"`` reports the spelling it declares and not the one it was
        handed. When the two resolve to the same thing the floats are reused
        exactly, without a round trip through a transformer.
        """
        from pyproj import CRS, Transformer

        try:
            source = CRS.from_user_input(self.crs)
            target = CRS.from_user_input(crs)
        except Exception as exc:  # pyproj raises its own family
            raise DataRequestError(
                f"Cannot resolve a CRS to convert an extent: {self.crs!r} -> {crs!r} ({exc})."
            ) from exc
        if source.equals(target):
            if crs == self.crs:
                return self
            return Extent(xmin=self.xmin, ymin=self.ymin, xmax=self.xmax, ymax=self.ymax, crs=crs)
        transformer = Transformer.from_crs(source, target, always_xy=True)
        xmin, ymin, xmax, ymax = transformer.transform_bounds(
            self.xmin, self.ymin, self.xmax, self.ymax
        )
        if not all(math.isfinite(v) for v in (xmin, ymin, xmax, ymax)):
            raise DataRequestError(
                f"Extent {self.bbox} in {self.crs!r} has no image in {crs!r}: the transform "
                "returned a non-finite bound, which means the box falls outside the area "
                "the target CRS is defined for."
            )
        return Extent(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax, crs=crs)


@dataclass(frozen=True)
class Period:
    """The closed time window a request asks for.

    Closed at both ends, which is what every adapter of this tree does with it:
    Hub'Eau sends ``date_debut``/``date_fin`` inclusive and SIM2 slices a cube
    the same way.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        for name in ("start", "end"):
            value = getattr(self, name)
            if not isinstance(value, datetime):
                raise DataRequestError(f"Period {name}={value!r} is not a datetime.")
        if (self.start.tzinfo is None) != (self.end.tzinfo is None):
            raise DataRequestError(
                "A period mixes an aware bound with a naive one, which no comparison "
                "between them can be trusted to order."
            )
        if self.end < self.start:
            raise DataRequestError(f"Period ends ({self.end}) before it starts ({self.start}).")

    @property
    def as_tuple(self) -> tuple[datetime, datetime]:
        """The pair the SIM2 family reads as ``project_period``."""
        return (self.start, self.end)


@dataclass(frozen=True)
class FetchRequest:
    """One question put to one source.

    ``out_dir`` is not optional even for a source that writes nothing, because
    it is the only place a source is ever allowed to write and a request that
    left it out would have to invent one. A source that declares
    ``writes_out_dir = False`` leaves it alone, and the conformance suite reads
    the directory back to check.

    A request that carries neither an extent nor a station id is accepted **by
    the type**, because a source that selects nothing (a file content, a
    computed constant) is asked exactly that. :func:`require_selectors` refuses
    it for every source that selects, which is the source's first line.

    ``bounds`` carries the hosts and roots the call runs under, the byte
    ceiling and the delay of one download; a caller that passes none gets the
    default of :class:`~hydromodpy.core.runtime.bounds.Bounds`. The fetch
    client applies it, the port only carries and refuses it by name.
    """

    out_dir: Path
    extent: Extent | None = None
    station_ids: tuple[str, ...] = ()
    period: Period | None = None
    bounds: Bounds = field(default_factory=Bounds)

    def __post_init__(self) -> None:
        if not isinstance(self.out_dir, (str, Path)):
            raise DataRequestError(f"out_dir={self.out_dir!r} is not a path.")
        object.__setattr__(self, "out_dir", Path(self.out_dir))
        if self.extent is not None and not isinstance(self.extent, Extent):
            raise DataRequestError(
                f"extent={self.extent!r} is not an Extent. A bare tuple does not say "
                "which CRS it is in."
            )
        if self.period is not None and not isinstance(self.period, Period):
            raise DataRequestError(f"period={self.period!r} is not a Period.")
        if not isinstance(self.bounds, Bounds):
            raise DataRequestError(
                f"bounds={self.bounds!r} is not a Bounds. Build one from "
                "hydromodpy.core.runtime.bounds; a request that carries none "
                "would have to invent what its download may reach."
            )
        if isinstance(self.station_ids, str):
            raise DataRequestError(
                f"station_ids={self.station_ids!r} is a single string, which would be read "
                "one character per station. Pass a sequence."
            )
        ids = tuple(self.station_ids)
        for station_id in ids:
            if not isinstance(station_id, str) or not station_id.strip():
                raise DataRequestError(f"Station id {station_id!r} is empty or not a string.")
        if len(set(ids)) != len(ids):
            duplicates = sorted({sid for sid in ids if ids.count(sid) > 1})
            raise DataRequestError(f"Station ids repeat: {duplicates}.")
        object.__setattr__(self, "station_ids", ids)

    @property
    def selectors(self) -> tuple[Selector, ...]:
        """Which selectors this request actually uses, in a stable order."""
        used: list[Selector] = []
        if self.extent is not None:
            used.append("extent")
        if self.station_ids:
            used.append("station_ids")
        return tuple(used)


# --------------------------------------------------------------------------- #
# What comes back
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FetchResult:
    """What one source produced, and what it claims about it.

    ``kind`` is declared rather than recovered from the payload, so a consumer
    dispatches on a closed vocabulary instead of on ``isinstance`` against five
    third-party types. ``variables`` is declared for the same reason: a
    ``features`` payload is a table of geometries that carries no variable name
    anywhere, so the only place the answer can live is here.

    ``extent`` is the extent that was really queried, in the CRS it was really
    queried in -- not the one the caller passed. It is what lets a caller see
    that its WGS84 box reached IGN as Lambert-93 meters.

    ``records`` is the number of records a source wrote behind a ``files``
    payload, when it counts them; a source that cannot leaves ``None``. It is
    how :attr:`is_empty` answers for a cached empty file, a file a source
    wrote so an empty answer is one no caller has to ask the provider for
    again.
    """

    source_id: str
    kind: PayloadKind
    variables: tuple[str, ...]
    extent: Extent | None = None
    period: Period | None = None
    points: tuple[PointRecord, ...] = ()
    fields: tuple[FieldRecord, ...] = ()
    features: gpd.GeoDataFrame | None = None
    files: tuple[FileRecord, ...] = ()
    records: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise DataProductError(f"A result carries source_id={self.source_id!r}.")
        if self.records is not None and (
            isinstance(self.records, bool) or not isinstance(self.records, int) or self.records < 0
        ):
            raise DataProductError(
                f"A result carries records={self.records!r}, which is not a record count. "
                "A source that knows how many records it handed back declares the number; "
                "one that cannot leaves it as None."
            )
        if self.kind not in ALL_PAYLOAD_KINDS:
            raise DataProductError(
                f"Unknown payload kind {self.kind!r}. Expected one of {list(ALL_PAYLOAD_KINDS)}."
            )
        object.__setattr__(self, "variables", tuple(self.variables))
        if not self.variables:
            raise DataProductError(
                f"Result of {self.source_id!r} names no variable. A payload nobody can name "
                "is a payload nobody can ask for again."
            )
        object.__setattr__(self, "points", tuple(self.points))
        object.__setattr__(self, "fields", tuple(self.fields))
        from hydromodpy.data.contracts.file_record import FileRecord

        bare = [value for value in self.files if not isinstance(value, FileRecord)]
        if bare:
            raise DataProductError(
                f"Result of {self.source_id!r} carries files as {type(bare[0]).__name__} "
                "instead of FileRecord. A bare path says nothing about the bytes it names, "
                "and the seal needs what it says: build them with FileRecord.of."
            )
        object.__setattr__(self, "files", tuple(self.files))
        filled = {
            "points": bool(self.points),
            "fields": bool(self.fields),
            "features": self.features is not None,
            "files": bool(self.files),
        }
        strangers = sorted(name for name, is_filled in filled.items() if is_filled)
        if any(name != self.kind for name in strangers):
            raise DataProductError(
                f"Result of {self.source_id!r} declares kind={self.kind!r} but carries "
                f"{strangers}. A result holds one payload, in the member its kind names."
            )

    @property
    def is_empty(self) -> bool:
        """True when the source reached its provider and it held nothing here.

        Not an error: a bbox over the sea has no gauging station, and a caller
        decides what that means. ``features`` counts as empty when the frame
        holds no row, which is how the hydrography adapters report it -- all
        three return ``GeoDataFrame(geometry=[], crs="EPSG:4326")``, never
        ``None``. A ``files`` answer that cached an empty file alongside (the
        writes-a-file sources) still held nothing: the source says so with
        ``records = 0``, rather than the port opening the bytes to count them.
        """
        if self.kind == "features":
            return self.features is None or len(self.features) == 0
        if self.kind == "files" and self.records is not None:
            return self.records == 0
        return not (self.points or self.fields or self.files)


# --------------------------------------------------------------------------- #
# The port
# --------------------------------------------------------------------------- #


@runtime_checkable
class DataSource(Protocol):
    """One source answers one question about one provider.

    Sources conform structurally: there is no base class, just ``fetch`` and
    the declarations, two of which -- ``variables`` and ``hosts`` -- belong to
    the built instance and the rest to the class. A third-party source needs
    no import of HydroModPy beyond this module and ``hydromodpy.data.contracts``,
    which holds the record types its payload is made of.

    A source that cannot serve what it is asked raises
    :class:`~hydromodpy.core.exceptions.DataCapabilityError` naming the option;
    a request that is malformed before any provider is contacted raises
    :class:`~hydromodpy.core.exceptions.DataRequestError`. Neither is ever
    answered by a capability probe on the object.
    """

    source_id: ClassVar[str]
    """Stable identity of this adapter within its section.

    The word the TOML writes, ``hubeau`` or ``bdtopage``, not necessarily the
    ``source`` its records carry, and the difference is deliberate: a record
    names the provider while the identity names the question put to it. One
    word serves up to nine sections here, so it is never unique on its own;
    the section beside it makes it a key.
    """

    section: ClassVar[str]
    """The ``[data.<section>]`` this class serves, exactly one.

    The registry keys a source on this pair, so a word serving nine sections is
    nine sources, one per section, and a section cannot reach a source another
    section names. A third-party source that serves no section of the TOML
    writes its own word here and is then reachable only through ``installed``.
    """

    variables: tuple[str, ...]
    """Every variable name **this source** emits, configuration included.

    The one member of the declaration that is neither a ``ClassVar``, and the
    adversarial gate is what settled it. A Hub'Eau piezometry class can serve
    two products; an instance built with ``product="level"`` serves one.
    Declared on the class, the set would have been the union, and
    :func:`require_declared_variables` would have accepted a depth-labeled
    record from a level source while the result it returned still said
    ``("groundwater_level",)``. Declared on the instance, the check is exactly
    as tight as the claim.

    Compared against what a real fetch puts on its records: a source that
    returns a variable it does not declare has a declaration nobody checked,
    which is what F1 and F2 spent two phases removing.
    """

    payload_kind: ClassVar[PayloadKind]
    """Which member of :class:`FetchResult` this source fills."""

    extent_crs: ClassVar[str]
    """The CRS this source's provider is queried in.

    Declared because it is not negotiable and not guessable: IGN and SIM2
    answer in Lambert-93, the Sandre WFS and Hub'Eau in WGS84, and a caller
    that had to know which would be back to carrying the defect.
    """

    selectors: ClassVar[tuple[Selector, ...]]
    """What this source can be asked for beside a period."""

    period_need: ClassVar[PeriodNeed]
    """Whether a period is required or refused; see :data:`PeriodNeed`."""

    hosts: tuple[str, ...]
    """Every host this source contacts, on the pattern F5a set for a capability.

    A member of the instance, like ``variables``: it is read only once a source
    is built, and a source this repository ships does not write it -- it reads
    :func:`shipped_hosts`, which holds the one table the licence pages read too.
    A third-party source writes its own, and a list and not a boolean, so the
    capability that composes several sources publishes the union rather than an
    opaque "yes".
    """

    writes_out_dir: ClassVar[bool]
    """Whether this source writes anything under ``request.out_dir``.

    Declared because the divergence is real and invisible from the return type:
    ``oceanic/apis/shom.py`` returns point records and writes a CSV cache on
    the way, while the four Hub'Eau adapters return the same kind and touch no
    file at all.
    """

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Serve ``request``, or refuse it by name.

        The extent of the request arrives in whatever CRS the caller had; the
        source converts it with :func:`extent_for` and reports on the result
        the extent it really queried.
        """
        ...


SOURCE_MEMBERS: tuple[str, ...] = (
    "source_id",
    "section",
    "variables",
    "payload_kind",
    "extent_crs",
    "selectors",
    "period_need",
    "hosts",
    "writes_out_dir",
    "fetch",
)
"""Everything the port asks of a source, declarations first.

Named here rather than derived from ``DataSource.__protocol_attrs__`` because
that attribute is a CPython implementation detail, and because a conformance
suite that read the members off the Protocol would pass for a Protocol that had
silently lost one.
"""


INSTANCE_SOURCE_MEMBERS: tuple[str, ...] = ("variables", "hosts")
"""The members only an instance carries, so a class cannot be asked for them.

Two members, and each was moved off the class on purpose. ``variables``: a
Hub'Eau piezometry class serves two products and an instance built with
``product="level"`` serves one, so the set is the instance's or it is a union
that no check can falsify. ``hosts``: a shipped source reads them from
:func:`shipped_hosts`, the one table the licence pages read, and what it reads
belongs to the built source, not to the class. The consequence is that
``hasattr`` on the class is ``False`` for both, and anything that validates a
*class* -- the registry, which resolves a name before anyone can construct it
-- has to know that and say so rather than report a conformance failure that is
really a design choice.
"""

CLASS_SOURCE_MEMBERS: tuple[str, ...] = tuple(
    name for name in SOURCE_MEMBERS if name not in INSTANCE_SOURCE_MEMBERS
)
"""What a source class promises before anybody builds one.

:data:`SOURCE_MEMBERS` minus :data:`INSTANCE_SOURCE_MEMBERS`, and
``test_the_two_member_sets_partition_the_port`` refuses the day the two stop
covering it exactly.
"""


def missing_source_members(candidate: object) -> tuple[str, ...]:
    """Return the members of :data:`SOURCE_MEMBERS` ``candidate`` does not have."""
    return tuple(name for name in SOURCE_MEMBERS if not hasattr(candidate, name))


# --------------------------------------------------------------------------- #
# What an implementation calls on its first line
# --------------------------------------------------------------------------- #


def require_selectors(source: DataSource, request: FetchRequest) -> None:
    """Refuse a request this source would have to answer by ignoring part of it.

    Three refusals. A selector the source does not declare is obvious. A
    request that carries **neither** an extent nor a station id is accepted by
    the type and refused here, unless the source declares ``selectors = ()``:
    a file content and a computed constant are asked exactly nothing, and that
    is the declaration saying so. And a request that carries **both** an
    extent and station identifiers is not: no provider of this tree serves
    them together, and every Hub'Eau adapter resolves it the same silent way --
    ``if station_ids: ... elif bbox:`` -- so the box is dropped and the result
    looks exactly like a box that held those stations and no others.

    Combining is refused for every source rather than declared per source,
    because no implementation can serve it today. The declaration arrives with
    the first provider that can, and not before.
    """
    if not request.selectors and source.selectors:
        raise DataRequestError(
            f"A request to {source.source_id!r} selects nothing: it carries neither an "
            f"extent nor a station id, and the source selects by {list(source.selectors)}. "
            "Only a source that declares selectors = () answers such a request."
        )
    unsupported = [name for name in request.selectors if name not in source.selectors]
    if unsupported:
        raise DataCapabilityError(
            f"Source {source.source_id!r} does not select by {unsupported}; it declares "
            f"{list(source.selectors)}. Asking anyway would return a result that silently "
            "ignores the argument."
        )
    if len(request.selectors) > 1:
        raise DataCapabilityError(
            f"A request to {source.source_id!r} carries {list(request.selectors)} at once, "
            "and no provider of this tree intersects them: the station list wins and the "
            "extent is dropped without a word. Ask twice, or ask for one."
        )


def require_period(source: DataSource, request: FetchRequest) -> Period | None:
    """Return the period this source should use, or refuse the mismatch."""
    if source.period_need == "refused" and request.period is not None:
        raise DataCapabilityError(
            f"Source {source.source_id!r} has no time axis to cut, and the request carries "
            f"a period {request.period.start.isoformat()}..{request.period.end.isoformat()}. "
            "Serving it would return the same rows under a window that means nothing."
        )
    if source.period_need == "required" and request.period is None:
        raise DataRequestError(
            f"Source {source.source_id!r} needs a period and the request carries none."
        )
    return request.period


def extent_for(source: DataSource, request: FetchRequest) -> Extent:
    """Return the request's extent in the CRS ``source`` is queried in.

    This is where the reprojection lives, and it is the reason the port exists.
    A source calls it on its first line; the conformance suite hands every
    source an extent in a CRS it did not declare and reads back
    :attr:`FetchResult.extent` to check that it did.
    """
    if request.extent is None:
        raise DataRequestError(
            f"Source {source.source_id!r} was asked for an extent the request does not carry."
        )
    return request.extent.to_crs(source.extent_crs)


def require_declared_variables(source: DataSource, names: Sequence[str]) -> None:
    """Refuse variable names the source does not declare."""
    undeclared = sorted({name for name in names if name not in source.variables})
    if undeclared:
        raise DataProductError(
            f"Source {source.source_id!r} produced {undeclared}, which its declaration "
            f"{list(source.variables)} does not name."
        )


def shipped_hosts(source_id: str) -> tuple[str, ...]:
    """Return the hosts the licence table records for a source this build ships.

    The one place hosts are written is ``hydromodpy.schema.sources``: the entry
    of a slug carries the licence, the pages it was read on, and the hosts a
    fetch contacts. A shipped source reads this function instead of writing its
    own copy, so the two can never disagree -- the test that used to hold them
    equal compares one table with itself now.

    Raises
    ------
    DataRequestError
        When the slug has no entry, which is a source this repository ships
        without a licence page, or a source of a third party reaching for a
        table that was never its side of the fence. A third-party source writes
        ``hosts`` itself.
    """
    from hydromodpy.schema.sources import source_entry

    entry = source_entry(source_id)
    if entry is None:
        raise DataRequestError(
            f"No licence entry exists for the source id {source_id!r}, so its hosts are "
            "not known here. A source this build ships has an entry in "
            "hydromodpy.schema.sources; a third-party source declares its own hosts."
        )
    return tuple(entry.hosts)


def fetch_within(source: DataSource, request: FetchRequest) -> FetchResult:
    """Refuse a source whose hosts the bounds do not allow, then serve the request.

    The one way a call reaches the provider of a source: every caller of a
    ``source.fetch`` goes through here, so the hosts a source declares are
    checked against ``request.bounds`` before any connection. The checks of
    each redirect and of a resolved address live in the fetch client, which
    owns the download.
    """
    request.bounds.require_hosts(
        tuple(source.hosts or ()),
        why=f"asking {getattr(source, 'section', '?')}_{getattr(source, 'source_id', '?')}",
    )
    return source.fetch(request)


__all__ = [
    "ALL_PAYLOAD_KINDS",
    "ALL_PERIOD_NEEDS",
    "ALL_SELECTORS",
    "CLASS_SOURCE_MEMBERS",
    "INSTANCE_SOURCE_MEMBERS",
    "SOURCE_MEMBERS",
    "DataSource",
    "Extent",
    "FetchRequest",
    "FetchResult",
    "PayloadKind",
    "Period",
    "PeriodNeed",
    "Selector",
    "extent_for",
    "fetch_within",
    "missing_source_members",
    "require_declared_variables",
    "require_period",
    "require_selectors",
    "shipped_hosts",
]
