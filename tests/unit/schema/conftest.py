"""One capability, small enough to declare in a test and real enough to refuse.

It carries the three input shapes the boundary has to tell apart — a file link,
an array of objects, and a constrained scalar — so a fault injected in any of
them lands on a different member of the document.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.schema.capability import CapabilityDecl, OutputDecl
from hydromodpy.schema.job.request import FileLink


class DemoOutlet(BaseModel):
    """One outlet of the demo capability, in the working projected CRS."""

    model_config = ConfigDict(extra="forbid")

    site_id: str = Field(min_length=1)
    x: float = Field(description="easting in m")
    y: float = Field(description="northing in m")


class DemoRequest(BaseModel):
    """The inputs of the demo capability."""

    model_config = ConfigDict(extra="forbid")

    dem: FileLink
    outlets: list[DemoOutlet] = Field(min_length=1)
    crs_project: str = Field(pattern=r"^EPSG:[0-9]{4,6}$")
    snap_distance_m: float = Field(default=50.0, gt=0, description="snapping window in m")


@pytest.fixture
def demo_capability() -> CapabilityDecl:
    return CapabilityDecl(
        id="demo-delineate",
        version="1.2.3",
        title="Delineate a catchment, for the tests of the boundary",
        description="Declares two artefacts and refuses everything else.",
        keywords=("hydrology", "test"),
        request_model=DemoRequest,
        outputs=(
            OutputDecl(
                id="watershed_vector",
                title="Delineated catchment polygons",
                path="outputs/watershed.gpkg",
                media_type="application/geopackage+sqlite3",
                roles=("data", "primary"),
            ),
            OutputDecl(
                id="outcome",
                title="Typed job outcome",
                path="outcome.json",
                media_type="application/json",
                roles=("metadata",),
            ),
        ),
        exceptions=(ConfigValidationError, FileNotFoundError),
    )
