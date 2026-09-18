"""``data-fetch``: asking one data source for one variable, from outside.

The second externally invocable capability, and the one that closes the
circularity the campaign opened this phase for. ``data.fetch`` used to take its
extent off a ``geographic`` object built by the terrain chain, which took its
DEM from ``data.fetch``: the extent is now an **input**, either a bounding box
that carries its CRS or a vector mask already produced by another job, so the
two steps chain through a directory instead of through an object graph.

Four questions this declaration answers differently from ``terrain-delineate``,
each because the code on this tree says so:

- **The payload shape depends on the source, and the declaration says all four.**
  A source serves ``points``, ``fields``, ``features`` or ``files``
  (:data:`~hydromodpy.data.source.port.PayloadKind`), one per run, so the four
  artefacts are declared and only one is produced. ``outputs/fetch.json`` is the
  one that is always there, and it names which of the four the run wrote. The
  alternative -- one capability per payload kind -- would publish four processes
  that differ by their output extension and by nothing else.
- **``reaches_network`` is derived, not written.** It is the union of the
  ``hosts`` every served source declares, which is exactly why D110 made that
  member a list of hosts rather than a boolean. Adding a member to
  :data:`SourceOptions` moves the declaration, the generated description and the
  firewall rule a caller writes, in one edit.
- **``$TMPDIR`` is declared because a fetch is given a scratch directory, always.**
  :class:`~hydromodpy.data.source.port.FetchRequest` has a mandatory ``out_dir``
  and the sources disagree about whether they write into it: IGN lands archives,
  extracted tiles and a merged GeoTIFF there, the other three leave it alone,
  and SIM2 writes a temporary NetCDF on its own fetch path
  (``sim2_edr.py:127``). None of that belongs under ``outputs/``, which carries
  the declared artefacts and nothing else, so the scratch is a
  ``TemporaryDirectory`` and the capability says it needs one.
- **The three selectors are exclusive.** A request carries an extent, a mask or
  a list of station identifiers, and exactly one of them. The port already
  refuses two at once for every source (D116); refusing it here as well points
  the refusal at the member of ``request.json`` that carries it, before a
  provider is resolved.
"""

from __future__ import annotations

import inspect
from datetime import datetime
from typing import Annotated, Any, Literal, get_args

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.exceptions import (
    CapabilityVersionMismatchError,
    ConfigValidationError,
    DataCapabilityError,
    DataContractViolation,
    DataProductError,
    DataRequestError,
    DataSourceError,
    JobUsageError,
)
from hydromodpy.data.source import registry
from hydromodpy.data.source.bdtopage import DEFAULT_PAGE_SIZE, DEFAULT_TYPENAME
from hydromodpy.data.source.port import DataSource
from hydromodpy.schema.capability import CapabilityDecl, OutputDecl
from hydromodpy.schema.job.request import FileLink
from hydromodpy.schema.media_types import (
    GEOPACKAGE_MEDIA_TYPE,
    GEOTIFF_MEDIA_TYPE,
    JSON_MEDIA_TYPE,
    NETCDF_MEDIA_TYPE,
    PARQUET_MEDIA_TYPE,
)

CAPABILITY_ID = "data-fetch"
CAPABILITY_VERSION = "1.0.0"

MAX_STATIONS = 1_000
"""Declared because ``maxOccurs`` has to be a number in the description."""

CRS_PATTERN = r"^EPSG:[0-9]{4,6}$"
"""How an extent names its CRS at this boundary.

Narrower than :class:`~hydromodpy.data.source.port.Extent`, which takes any
string ``pyproj`` resolves: a document refused for writing ``"lambert93"`` is
better than one accepted and answered by a CRS lookup failure three calls down.
"""


class BdTopageOptions(HydroModelBase):
    """Ask the Sandre WFS for the BD Topage reference river network."""

    id: Annotated[Literal["bdtopage"], Profile.USER] = Field(
        description="identity of the source, as 'hmp process describe' lists it",
    )
    typename: Annotated[str, Profile.USER] = Field(
        default=DEFAULT_TYPENAME,
        min_length=1,
        description="WFS feature type served by the Sandre endpoint",
    )
    page_size: Annotated[int, Profile.USER] = Field(
        default=DEFAULT_PAGE_SIZE,
        gt=0,
        description="features requested per page while the WFS result is walked",
    )

    def build(self) -> DataSource:
        return registry.get(self.id)(typename=self.typename, page_size=self.page_size)


class HubeauPiezometryOptions(HydroModelBase):
    """Ask Hub'Eau for groundwater levels or depths at piezometers."""

    id: Annotated[Literal["hubeau-piezometry"], Profile.USER] = Field(
        description="identity of the source, as 'hmp process describe' lists it",
    )
    product: Annotated[Literal["level", "depth"], Profile.USER] = Field(
        default="level",
        description="which of the two Hub'Eau products the records carry",
    )
    require_observations: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="drop a piezometer that has no observation inside the period",
    )

    def build(self) -> DataSource:
        return registry.get(self.id)(
            product=self.product,
            require_observations=self.require_observations,
        )


class IgnDemOptions(HydroModelBase):
    """Ask the Geoplateforme for BD ALTI 25 m tiles, merged over the extent."""

    id: Annotated[Literal["ign-bdalti"], Profile.USER] = Field(
        description="identity of the source, as 'hmp process describe' lists it",
    )
    departments: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        max_length=101,
        description=("department codes to download, padded; empty lets the extent select them"),
        examples=[["035", "022"]],
    )

    def build(self) -> DataSource:
        return registry.get(self.id)(departments=tuple(self.departments))


class Sim2PrecipitationOptions(HydroModelBase):
    """Ask the GeoSAS EDR service for daily SIM2 precipitation grids."""

    id: Annotated[Literal["sim2-precipitation"], Profile.USER] = Field(
        description="identity of the source, as 'hmp process describe' lists it",
    )
    components: Annotated[list[Literal["liquid", "solid", "total"]], Profile.USER] = Field(
        default=["total"],
        min_length=1,
        max_length=3,
        description="precipitation components to fetch, one field per component",
    )

    def build(self) -> DataSource:
        return registry.get(self.id)(components=tuple(self.components))


# Why a free-form bag here and nowhere else, since D122 refused one. D122
# refused a bag **for a source this build describes**: there the shape is known
# and publishing a free-form object instead of it throws away what the
# description is for. Here the shape is not knowable -- the description ships in
# a wheel built before the plugin existed -- and the bag is still not validated
# against nothing: it is bound against the plugin's own constructor signature
# before the job starts, which is the only authority that exists for it.
#
# The refusal below reads the **described** set and not the shipped one, which
# is D146. ``euhydro`` and ``osm`` are registered by this build and have no
# options model, so they arrive through this member rather than one of their
# own. That is right: the description does not describe them either, so a
# caller naming one gets the same unchecked bag and the same caveat about hosts
# as a caller naming a third-party source.
class InstalledSourceOptions(HydroModelBase):
    """Ask a source this build does not describe, installed beside it.

    The four members above each name a source shipped here and publish the
    exact shape it accepts. This one carries the id of a source the
    **installation** resolves -- one registered on the
    ``hydromodpy.data.source`` entry-point group -- and the keyword arguments
    its constructor takes. The id is refused before the job starts if nothing
    answers to it, and so is an argument that source cannot be built with.

    **The hosts this capability declares do not cover it.** ``hmp:invocation``
    lists the network of the described sources, and that list ships frozen with
    the build. A run naming an installed source may contact a host outside it;
    ``outputs/fetch.json`` records the hosts the run really reached, and an
    orchestrator that allows egress from the description alone has to widen it
    itself.
    """

    id: Annotated[Literal["installed"], Profile.USER] = Field(
        description="names a source this build does not describe, carried by 'name'",
    )
    name: Annotated[str, Profile.USER] = Field(
        min_length=1,
        description=(
            "source id this installation resolves, registered on the "
            "'hydromodpy.data.source' entry-point group"
        ),
        examples=["acme-radar"],
    )
    options: Annotated[dict[str, Any], Profile.USER] = Field(
        default_factory=dict,
        description=(
            "keyword arguments handed to that source's constructor, verbatim; "
            "bound against its signature before the job starts"
        ),
    )

    @model_validator(mode="after")
    def _refuse_what_this_installation_cannot_answer(self) -> InstalledSourceOptions:
        """Refuse a described name, an unresolvable one, and an option it cannot take.

        All three before the job directory is touched, which is the promise
        D123 made for every other member of this union. A padded name is not a
        fourth refusal: ``HydroModelBase`` strips it, and ``min_length`` then
        refuses a name that was nothing but padding.
        """
        name = self.name
        if name in _served_source_ids():
            raise ValueError(
                f"{name!r} is a source this build describes, so it is named as "
                f'{{"id": "{name}"}} with the shape the process description publishes. '
                "This member is for a source the description cannot know."
            )
        try:
            source_cls = registry.get(name)
        except DataRequestError as exc:
            raise ValueError(str(exc)) from exc
        try:
            inspect.signature(source_cls).bind(**self.options)
        except TypeError as exc:
            raise ValueError(
                f"source {name!r} cannot be built from these options: {exc}. The options are "
                "handed to its constructor as keyword arguments, and this build has no "
                "description of that source to check them against beyond its signature."
            ) from exc
        return self

    def build(self) -> DataSource:
        return registry.get(self.name)(**self.options)


SourceOptions = Annotated[
    BdTopageOptions
    | HubeauPiezometryOptions
    | IgnDemOptions
    | InstalledSourceOptions
    | Sim2PrecipitationOptions,
    Field(discriminator="id"),
]
"""The source, and everything that configures it, as one tagged document.

Tagged on ``id`` rather than spelled as a source name beside a free-form option
bag: a bag would be validated against nothing, and the description a shim reads
would list an input whose shape it cannot know.

**This union is the list.** ``SERVED_SOURCES`` used to be a second tuple of the
same four sources beside it; it is now read off the discriminator of this one
and resolved through the registry, so a source cannot be served without a
document shape and a shape cannot be published without a source behind it.

The fifth member tags no source, and that is what makes the union closed and
the installation open: ``{"id": "installed", "name": ...}`` reaches anything the
registry resolves, without this build naming it.
"""


def _served_source_ids() -> tuple[str, ...]:
    """The ids the union tags that are sources this build ships.

    Every member tags something; only four of them tag a **source**. The fifth
    tags the door to the ones this build does not ship, so its tag resolves to
    no class and has no host, no payload kind and no options model to compare.
    Filtering on :func:`~hydromodpy.data.source.registry.builtin_source_ids`
    rather than on a marker means the filter states a fact the registry owns,
    and ``test_the_union_tags_the_shipped_sources_and_one_door`` refuses the
    day a member tags neither.
    """
    union, _ = get_args(SourceOptions)
    tags = tuple(get_args(member.model_fields["id"].annotation)[0] for member in get_args(union))
    shipped = set(registry.builtin_source_ids())
    return tuple(tag for tag in tags if tag in shipped)


SERVED_SOURCES: tuple[type, ...] = tuple(
    registry.get(source_id) for source_id in _served_source_ids()
)
"""The source classes this build describes, in the order the union names them.

Resolved through :mod:`hydromodpy.data.source.registry`, which is also what
``build()`` calls, so substituting the class registered under an id substitutes
what a run of this capability actually asks.

Deliberately **not** ``registry.list_source_ids()``. A plugin installed beside
this build is resolvable and is not describable: the description that would
name it ships in the wheel, and the wheel was built before the plugin existed.
The two answers are kept apart by ``builtin_source_ids`` and
``list_source_ids``, and this is the member that needs the first.
"""

REACHED_HOSTS: tuple[str, ...] = tuple(
    sorted({host for source in SERVED_SOURCES for host in source.hosts})
)
"""Every host any served source contacts, which is what the capability declares.

The union and not the host of the source a given request names: an orchestrator
allows egress before it reads the request, so what it has to allow is the set a
run *may* reach. ``outputs/fetch.json`` records the one it did reach.
"""


class BboxExtentInput(HydroModelBase):
    """A bounding box and the CRS it is expressed in."""

    bbox: Annotated[list[float], Profile.USER] = Field(
        min_length=4,
        max_length=4,
        description="xmin, ymin, xmax, ymax, in the units of crs",
        examples=[[-1.85, 48.05, -1.55, 48.25]],
    )
    crs: Annotated[str, Profile.USER] = Field(
        pattern=CRS_PATTERN,
        description="CRS the four bounds are expressed in",
        examples=["EPSG:4326"],
    )

    @model_validator(mode="after")
    def _refuse_an_empty_or_inverted_box(self) -> BboxExtentInput:
        """Refuse here what the port would refuse later, pointed at the member.

        The port raises on the same condition, and its message names an
        ``Extent`` the caller never wrote. Refusing in the model turns it into a
        fault located at ``inputs.extent.bbox``, which is what a shim shows.
        """
        xmin, ymin, xmax, ymax = self.bbox
        if xmin >= xmax or ymin >= ymax:
            raise ValueError(
                f"bbox ({xmin}, {ymin}, {xmax}, {ymax}) is empty or inverted; "
                "expected xmin < xmax and ymin < ymax"
            )
        return self


class PeriodInput(HydroModelBase):
    """The closed time window a request asks for, both ends included."""

    start: Annotated[datetime, Profile.USER] = Field(
        description="first instant of the window, inclusive",
        examples=["2020-01-01"],
    )
    end: Annotated[datetime, Profile.USER] = Field(
        description="last instant of the window, inclusive",
        examples=["2020-12-31"],
    )

    @model_validator(mode="after")
    def _refuse_a_window_that_ends_before_it_starts(self) -> PeriodInput:
        if self.end < self.start:
            raise ValueError(f"period ends ({self.end}) before it starts ({self.start})")
        return self


class DataFetchRequest(HydroModelBase):
    """The ``inputs`` member of a ``data-fetch`` request."""

    source: Annotated[SourceOptions, Profile.USER] = Field(
        description="which source to ask, and everything that configures it",
    )
    extent: Annotated[BboxExtentInput | None, Profile.USER] = Field(
        default=None,
        description="bounding box to fetch over, in the CRS it declares",
    )
    mask: Annotated[FileLink | None, Profile.USER] = Field(
        default=None,
        description=(
            "vector file whose bounds are the extent, typically a watershed "
            "produced by terrain-delineate"
        ),
    )
    station_ids: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        max_length=MAX_STATIONS,
        description="station codes to fetch, for a source that selects by station",
    )
    period: Annotated[PeriodInput | None, Profile.USER] = Field(
        default=None,
        description=(
            "time window, required by a source with a time axis and refused by one without"
        ),
    )

    @model_validator(mode="after")
    def _refuse_anything_but_one_selector(self) -> DataFetchRequest:
        """Refuse a request that selects nothing, or that selects twice.

        Two selectors at once is the defect D116 measured at the port: every
        Hub'Eau adapter resolves it with ``if station_ids: ... elif bbox:``, so
        the box is dropped without a word and the result looks exactly like a box
        that held those stations and no others. The port refuses the pair for
        every source; this refusal is the same one, one layer out, so that the
        fault names the member of the document rather than a value type.
        """
        chosen = [
            name
            for name, given in (
                ("extent", self.extent is not None),
                ("mask", self.mask is not None),
                ("station_ids", bool(self.station_ids)),
            )
            if given
        ]
        if not chosen:
            raise ValueError(
                "the request selects nothing: give exactly one of extent, mask or station_ids"
            )
        if len(chosen) > 1:
            raise ValueError(
                f"the request carries {', '.join(chosen)} at once, and no source of this "
                "tree intersects them; ask for one, or submit two jobs"
            )
        repeated = sorted({code for code in self.station_ids if self.station_ids.count(code) > 1})
        if repeated:
            # Refused here although ``FetchRequest`` refuses it too. The port's
            # check runs inside the fetch, after ``ensure_workspace`` has made
            # ``outputs/`` and ``logs/`` -- which broke the one promise this
            # model exists to keep, that a refused document leaves the directory
            # exactly as the caller staged it.
            raise ValueError(
                f"station_ids repeat {repeated}; a station asked for twice is asked for once"
            )
        return self


REPORT_PATH = "outputs/fetch.json"
POINTS_PATH = "outputs/points.parquet"
FIELDS_PATH = "outputs/fields.nc"
FEATURES_PATH = "outputs/features.gpkg"
RASTER_PATH = "outputs/raster.tif"

PAYLOAD_PATHS: dict[str, str] = {
    "points": POINTS_PATH,
    "fields": FIELDS_PATH,
    "features": FEATURES_PATH,
    "files": RASTER_PATH,
}
"""Where each payload kind lands. One entry per value of ``PayloadKind``.

``files`` maps to a single raster because that is what the one ``files`` source
of this tree produces: ``fetch_ign_dem`` merges the tiles it downloaded and
returns one GeoTIFF. A result carrying anything else is refused by the worker
rather than sealed under a name that would not describe it.
"""

DATA_FETCH = CapabilityDecl(
    id=CAPABILITY_ID,
    version=CAPABILITY_VERSION,
    title="Fetch one variable from one data source over a declared extent",
    description=(
        "Asks one declared data source for one variable over a bounding box, a "
        "vector mask or a list of stations, and seals what came back as a single "
        "artefact beside a report naming the extent that was really queried."
    ),
    keywords=("data", "fetch", "download", "hydrology", "France"),
    request_model=DataFetchRequest,
    outputs=(
        OutputDecl(
            id="report",
            title="What was fetched, and the extent that was really queried",
            path=REPORT_PATH,
            media_type=JSON_MEDIA_TYPE,
            roles=("metadata", "primary"),
        ),
        OutputDecl(
            id="points",
            title="Station time series, one row per observation",
            path=POINTS_PATH,
            media_type=PARQUET_MEDIA_TYPE,
            roles=("data",),
            required=False,
        ),
        OutputDecl(
            id="fields",
            title="Gridded fields, one data variable per fetched variable",
            path=FIELDS_PATH,
            media_type=NETCDF_MEDIA_TYPE,
            roles=("data",),
            required=False,
            extra={"hmp:conformsTo": ["NetCDF-4"]},
        ),
        OutputDecl(
            id="features",
            title="Vector features, one layer",
            path=FEATURES_PATH,
            media_type=GEOPACKAGE_MEDIA_TYPE,
            roles=("data",),
            required=False,
        ),
        OutputDecl(
            id="raster",
            title="Merged raster covering the extent",
            path=RASTER_PATH,
            media_type=GEOTIFF_MEDIA_TYPE,
            roles=("data",),
            required=False,
        ),
        OutputDecl(
            id="inputset",
            title="Resolved, hashed, licence-annotated input set",
            path="inputset.json",
            media_type=JSON_MEDIA_TYPE,
            roles=("metadata", "provenance"),
        ),
        OutputDecl(
            id="outcome",
            title="Typed job outcome",
            path="outcome.json",
            media_type=JSON_MEDIA_TYPE,
            roles=("metadata",),
        ),
    ),
    exceptions=(
        JobUsageError,
        CapabilityVersionMismatchError,
        ConfigValidationError,
        FileNotFoundError,
        DataContractViolation,
        DataRequestError,
        DataCapabilityError,
        DataSourceError,
        DataProductError,
    ),
    env=("HMP_NO_PROGRESS", "HMP_LOG_LEVEL", "TMPDIR"),
    # Every fetch is handed a scratch directory it owns, because ``out_dir`` is
    # mandatory on a FetchRequest and what a source leaves there is provider
    # junk -- IGN alone lands an archive tree beside its merged raster. Only the
    # one artefact the declaration names is moved under ``outputs/``.
    writes_outside_jobdir=("$TMPDIR",),
    reaches_network=REACHED_HOSTS,
)
"""The capability that reaches a provider, and says which ones it may reach."""


WATERSHED_MASK_LAYER_HINT = (
    "a mask is read with geopandas: any single-layer vector file it opens, and "
    "the GeoPackage terrain-delineate seals is one"
)
"""Spelled once, and quoted in the refusal a bad mask produces."""


__all__ = [
    "CAPABILITY_ID",
    "CAPABILITY_VERSION",
    "CRS_PATTERN",
    "DATA_FETCH",
    "FEATURES_PATH",
    "FIELDS_PATH",
    "MAX_STATIONS",
    "PAYLOAD_PATHS",
    "POINTS_PATH",
    "RASTER_PATH",
    "REACHED_HOSTS",
    "REPORT_PATH",
    "SERVED_SOURCES",
    "WATERSHED_MASK_LAYER_HINT",
    "BboxExtentInput",
    "BdTopageOptions",
    "DataFetchRequest",
    "HubeauPiezometryOptions",
    "IgnDemOptions",
    "InstalledSourceOptions",
    "PeriodInput",
    "Sim2PrecipitationOptions",
    "SourceOptions",
]
