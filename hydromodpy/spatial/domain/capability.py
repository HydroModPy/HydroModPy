"""``domain-build``: a terrain and a depth model in, a sealed vertical extent out.

The extent is the geometry a mesh is cut out of, handed to the meshing as a
sealed artefact instead of a live object.

The request takes the depth model of ``[domain]``, not the whole section:
``supports`` and ``zone_ids`` read artefacts this process never receives. The
working CRS is the one of the DEM, and a DEM without one is refused.

The top surface is not written again. ``domain.json`` carries the digest of the
raster the bottom was derived from, so a reader holding a DEM can prove it is
that one.

The two elevation rasters are float64 and carry NaN outside the domain. The
nodata of the DEM is not kept by ``Surface.flat_like``, and a finite sentinel
could collide with an elevation: a flat substratum at 0 m on a terrain whose
nodata is 0 would make every active cell read as no data. NaN cannot collide
with an elevation, and ``active_cells.tif`` says the same thing in integers.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.exceptions import (
    CapabilityVersionMismatchError,
    ConfigValidationError,
    DataContractViolation,
    JobUsageError,
)
from hydromodpy.schema.capability import CapabilityDecl, OutputDecl
from hydromodpy.schema.job.request import FileLink
from hydromodpy.schema.media_types import GEOTIFF_MEDIA_TYPE, JSON_MEDIA_TYPE
from hydromodpy.spatial.domain.depth_model_config import DepthModelConfig

CAPABILITY_ID = "domain-build"
CAPABILITY_VERSION = "1.0.0"

DOMAIN_SCHEMA = "hmp-domain/v1"
"""The profile ``domain.json`` conforms to. Resolves to nothing, by design."""


class DomainBuildRequest(HydroModelBase):
    """The ``inputs`` member of a ``domain-build`` request."""

    dem: Annotated[FileLink, Profile.USER] = Field(
        description=(
            "elevation raster carrying its own CRS and an axis-aligned grid; band 1 "
            "is the top surface of the domain and its grid is what every output is "
            "written on"
        ),
    )
    depth_model: Annotated[DepthModelConfig, Profile.USER] = Field(
        description=(
            "how the bottom of the aquifer is placed below the top surface; "
            "the [domain.depth_model] section of a project, verbatim"
        ),
    )
    substratum: Annotated[FileLink | None, Profile.USER] = Field(
        default=None,
        description=(
            "raster the substratum is read from, carrying its own CRS; required by a "
            "depth model of kind 'raster_substratum' or 'raster_thickness' and refused "
            "by any other. Once reprojected onto the grid of the dem it must cover "
            "every active cell"
        ),
    )
    mask: Annotated[FileLink | None, Profile.USER] = Field(
        default=None,
        description=(
            "polygon layer bounding the active part of the grid, for example the "
            "catchment terrain-delineate seals; a layer of lines or points is "
            "refused, and without a mask every cell carrying data is active"
        ),
    )
    mask_layer: Annotated[str | None, Profile.USER] = Field(
        default=None,
        min_length=1,
        max_length=128,
        description=(
            "layer of the mask file to read; required only when the file holds "
            "more than one, and refused when it names none of them"
        ),
        examples=["watershed"],
    )


BOTTOM_PATH = "outputs/bottom.tif"
THICKNESS_PATH = "outputs/thickness.tif"
ACTIVE_CELLS_PATH = "outputs/active_cells.tif"
DOMAIN_DOCUMENT_PATH = "outputs/domain.json"

DOMAIN_BUILD = CapabilityDecl(
    id=CAPABILITY_ID,
    version=CAPABILITY_VERSION,
    title="Aquifer domain geometry from a terrain and a depth model",
    description=(
        "Places the bottom of the aquifer below a topographic surface, bounds the "
        "active grid with an optional polygon, and describes the resulting vertical "
        "extent as one document a mesh generator can be handed."
    ),
    keywords=("hydrogeology", "domain", "aquifer", "geometry", "substratum"),
    request_model=DomainBuildRequest,
    outputs=(
        OutputDecl(
            id="domain",
            title="Grid, depth model and vertical extent of the domain",
            path=DOMAIN_DOCUMENT_PATH,
            media_type=JSON_MEDIA_TYPE,
            roles=("data", "primary"),
            extra={"hmp:conformsTo": [DOMAIN_SCHEMA]},
        ),
        OutputDecl(
            id="bottom",
            title="Bottom elevation of the aquifer on the active cells",
            path=BOTTOM_PATH,
            media_type=GEOTIFF_MEDIA_TYPE,
            roles=("data",),
            extra={"hmp:units": "m", "hmp:nodata": "nan"},
        ),
        OutputDecl(
            id="thickness",
            title="Aquifer thickness on the active cells",
            path=THICKNESS_PATH,
            media_type=GEOTIFF_MEDIA_TYPE,
            roles=("data",),
            extra={"hmp:units": "m", "hmp:nodata": "nan"},
        ),
        OutputDecl(
            id="active_cells",
            title="Cells the domain is defined on",
            path=ACTIVE_CELLS_PATH,
            media_type=GEOTIFF_MEDIA_TYPE,
            roles=("data", "intermediate"),
            extra={"hmp:values": {"0": "inactive", "1": "active"}},
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
    ),
    env=("HMP_NO_PROGRESS", "HMP_VERBOSITY"),
    # Empty, and measured rather than assumed: the rasters are written straight
    # into ``outputs/`` and the vector is read in place, so nothing needs a
    # scratch root. The test that runs the capability with a controlled TMPDIR
    # is what holds this to be true.
    writes_outside_jobdir=(),
    # Up to three files in, four files out, and no provider of any kind. This is the
    # first capability of the build that is a pure function of its inputs, and
    # the egress gate is what makes the claim refutable.
    reaches_network=(),
)
"""The capability that sits between the terrain and the mesh."""


__all__ = [
    "ACTIVE_CELLS_PATH",
    "BOTTOM_PATH",
    "CAPABILITY_ID",
    "CAPABILITY_VERSION",
    "DOMAIN_BUILD",
    "DOMAIN_DOCUMENT_PATH",
    "DOMAIN_SCHEMA",
    "THICKNESS_PATH",
    "DomainBuildRequest",
]
