"""``terrain-delineate``: what the first externally invocable capability is.

The declaration and the input model live next to the worker they describe, so
a change to what the capability accepts and a change to what it does are one
diff. ``spatial`` may import ``schema``, which is the whole reason the job
vocabulary was put there.

Three places where this declaration says something the specification of the
boundary did not, because the code on this tree says it:

- the accumulation raster carries ``transform: ln``. The chain this capability
  binds over emits the **natural logarithm** of a cell count, and declaring an
  untransformed raster would publish exactly the false statement the port was
  built to end.
- ``snap_distance_m`` is an integer. The delineation path casts it with
  ``int()`` two calls down, so a fractional metre would be silently truncated,
  and a document refused for saying ``49.5`` is better than one accepted and
  run at 49.
- ``outcome.json`` is declared as an output and carries no digest in the
  outcome that names it, because that document cannot hash itself. The seal
  hashes it from disk, which is where its digest comes from.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.exceptions import (
    CapabilityVersionMismatchError,
    ConfigValidationError,
    DataContractViolation,
    EmptyCatchmentError,
    JobUsageError,
    TerrainProductError,
)
from hydromodpy.schema.capability import CapabilityDecl, OutputDecl
from hydromodpy.schema.job.request import FileLink
from hydromodpy.schema.media_types import (
    GEOJSON_MEDIA_TYPE,
    GEOPACKAGE_MEDIA_TYPE,
    GEOTIFF_MEDIA_TYPE,
    JSON_MEDIA_TYPE,
    PARQUET_MEDIA_TYPE,
)

CAPABILITY_ID = "terrain-delineate"
CAPABILITY_VERSION = "1.0.0"

OUTLET_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
"""The spelling the terrain port makes a directory name of.

Repeated here rather than imported so the refusal happens at the boundary,
pointed at the member of ``request.json`` that carries it, instead of deep in
an engine where nothing can say which key was wrong.
"""

MAX_OUTLETS = 10_000
"""Declared because ``maxOccurs`` has to be a number in the description."""


class OutletInput(HydroModelBase):
    """One point to delineate from, in the working projected CRS."""

    site_id: Annotated[str, Profile.USER] = Field(
        min_length=1,
        max_length=64,
        pattern=OUTLET_ID_PATTERN,
        description="identifier of the outlet, usable as a directory name",
        examples=["cheze_downstream"],
    )
    x: Annotated[float, Profile.USER] = Field(
        description="easting in the working projected CRS, in m",
        examples=[300112.5],
        json_schema_extra=field_metadata(unit="m"),
    )
    y: Annotated[float, Profile.USER] = Field(
        description="northing in the working projected CRS, in m",
        examples=[6701262.5],
        json_schema_extra=field_metadata(unit="m"),
    )


class TerrainDelineateRequest(HydroModelBase):
    """The ``inputs`` member of a ``terrain-delineate`` request."""

    dem: Annotated[FileLink, Profile.USER] = Field(
        description="single-band elevation raster in the working projected CRS",
    )
    outlets: Annotated[list[OutletInput], Profile.USER] = Field(
        min_length=1,
        max_length=MAX_OUTLETS,
        description="outlets to delineate, each against the same flow products",
    )
    crs_project: Annotated[str, Profile.USER] = Field(
        pattern=r"^EPSG:[0-9]{4,6}$",
        description="working projected CRS stamped on every product",
        # Declared because the synthetic fallback of ``HydroModelBase`` invents
        # ``"example"`` for an undocumented string, and this field's pattern
        # rejects it: a published description would carry an example its own
        # schema refuses.
        examples=["EPSG:2154"],
    )
    dem_correction_type: Annotated[Literal["fill", "breach"], Profile.USER] = Field(
        default="breach",
        description="how depressions are removed before flow is routed",
    )
    snap_distance_m: Annotated[int, Profile.USER] = Field(
        default=50,
        gt=0,
        description="width of the square window an outlet is snapped inside, in m",
        json_schema_extra=field_metadata(unit="m"),
    )

    @model_validator(mode="after")
    def _refuse_repeated_site_ids(self) -> TerrainDelineateRequest:
        """Refuse two outlets that would write into one directory.

        Case-folded, because the collision is on a directory name and a
        case-insensitive filesystem makes ``Left`` and ``left`` one directory.
        Refusing the pair everywhere is the only answer that does not depend
        on which machine the job lands on.
        """
        seen: set[str] = set()
        repeated: list[str] = []
        for outlet in self.outlets:
            folded = outlet.site_id.casefold()
            if folded in seen:
                repeated.append(outlet.site_id)
            seen.add(folded)
        if repeated:
            raise ValueError(
                "outlets repeat the site id(s) "
                f"{', '.join(sorted(repeated))}, case-folded; each one names a directory"
            )
        return self


WATERSHED_VECTOR_PATH = "outputs/watershed.gpkg"
WATERSHED_TABLE_PATH = "outputs/watershed.parquet"
OUTLETS_SNAPPED_PATH = "outputs/outlets_snapped.geojson"
FLOW_DIRECTION_PATH = "outputs/flow_direction.tif"
FLOW_ACCUMULATION_PATH = "outputs/flow_accumulation.tif"
DEM_CORRECTED_PATH = "outputs/dem_corrected.tif"

TERRAIN_DELINEATE = CapabilityDecl(
    id=CAPABILITY_ID,
    version=CAPABILITY_VERSION,
    title="Watershed delineation from a DEM and one or more outlets",
    description=(
        "Corrects a digital elevation model, computes D8 flow direction and flow "
        "accumulation, snaps each outlet to the drainage network and delineates the "
        "upstream contributing area of each."
    ),
    keywords=("hydrology", "watershed", "delineation", "DEM", "D8"),
    request_model=TerrainDelineateRequest,
    outputs=(
        OutputDecl(
            id="watershed_vector",
            title="Delineated catchment polygons",
            path=WATERSHED_VECTOR_PATH,
            media_type=GEOPACKAGE_MEDIA_TYPE,
            roles=("data", "primary"),
        ),
        OutputDecl(
            id="watershed_table",
            title="Delineated catchment polygons, columnar",
            path=WATERSHED_TABLE_PATH,
            media_type=PARQUET_MEDIA_TYPE,
            roles=("data",),
            extra={"hmp:conformsTo": ["GeoParquet-1.1"]},
        ),
        OutputDecl(
            id="outlets_snapped",
            title="Every declared outlet, its status and the snap distance of each",
            path=OUTLETS_SNAPPED_PATH,
            media_type=GEOJSON_MEDIA_TYPE,
            roles=("data",),
            extra={"hmp:crs": "OGC:CRS84"},
        ),
        OutputDecl(
            id="flow_direction",
            title="D8 pointer raster",
            path=FLOW_DIRECTION_PATH,
            media_type=GEOTIFF_MEDIA_TYPE,
            roles=("data", "intermediate"),
            extra={"hmp:pointer_convention": "d8_wbt"},
        ),
        OutputDecl(
            id="flow_accumulation",
            title="Flow accumulation raster",
            path=FLOW_ACCUMULATION_PATH,
            media_type=GEOTIFF_MEDIA_TYPE,
            roles=("data", "intermediate"),
            extra={"hmp:units": "cells", "hmp:transform": "ln"},
        ),
        OutputDecl(
            id="dem_corrected",
            title="Depression-removed DEM",
            path=DEM_CORRECTED_PATH,
            media_type=GEOTIFF_MEDIA_TYPE,
            roles=("data", "intermediate"),
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
        TerrainProductError,
        EmptyCatchmentError,
    ),
    env=("HMP_NO_PROGRESS", "HMP_LOG_LEVEL", "TMPDIR"),
    # The delineation writes one catchment per outlet under a scratch root
    # before the two vector products are assembled, and that root is a
    # ``TemporaryDirectory`` (``worker.py``). It is removed when the job ends,
    # but while it runs the process needs a writable ``TMPDIR``, and an
    # orchestrator mounting everything but the job directory read-only has to
    # know it. Declaring ``false`` here would be a boolean that is not true.
    writes_outside_jobdir=("$TMPDIR",),
)
"""The one capability this build can be invoked as, from outside."""


__all__ = [
    "CAPABILITY_ID",
    "CAPABILITY_VERSION",
    "DEM_CORRECTED_PATH",
    "FLOW_ACCUMULATION_PATH",
    "FLOW_DIRECTION_PATH",
    "MAX_OUTLETS",
    "OUTLETS_SNAPPED_PATH",
    "OUTLET_ID_PATTERN",
    "TERRAIN_DELINEATE",
    "WATERSHED_TABLE_PATH",
    "WATERSHED_VECTOR_PATH",
    "OutletInput",
    "TerrainDelineateRequest",
]
