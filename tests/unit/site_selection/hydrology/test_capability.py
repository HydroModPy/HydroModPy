"""The declaration of ``terrain-delineate``, and what its document refuses.

The process description publishes one exit code per declared exception, read
from ``exit_code_for``. A class falling through to ``EXIT_GENERIC`` would publish
"report this as a bug" for an ordinary refusal, the defect F4a repaired.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.cli import helpers as codes
from hydromodpy.core import exceptions as errors
from hydromodpy.schema.capability import NAMES_THE_JOB_DOES_NOT_PRODUCE
from hydromodpy.spatial.site_selection.hydrology.capability import (
    TERRAIN_DELINEATE,
    TerrainDelineateRequest,
)

pytestmark = pytest.mark.fast

VALID_INPUTS = {
    "dem": {"href": "dem.tif", "type": "image/tiff; application=geotiff"},
    "outlets": [{"site_id": "cheze", "x": 348120.0, "y": 6781450.0}],
    "crs_project": "EPSG:2154",
}


def test_the_capability_declares_the_artefacts_the_worker_writes():
    accumulation = TERRAIN_DELINEATE.output("flow_accumulation")

    assert (TERRAIN_DELINEATE.id, TERRAIN_DELINEATE.major) == ("terrain-delineate", 1)
    assert TERRAIN_DELINEATE.output_ids == (
        "watershed_vector", "watershed_table", "outlets_snapped", "flow_direction",
        "flow_accumulation", "dem_corrected", "inputset", "outcome",
    )  # fmt: skip
    # No declared output claims a name the job does not produce.
    assert (
        not {output.path for output in TERRAIN_DELINEATE.outputs} & NAMES_THE_JOB_DOES_NOT_PRODUCE
    )
    # The accumulation declares the transform the chain really writes.
    assert (accumulation.extra["hmp:transform"], accumulation.extra["hmp:units"]) == ("ln", "cells")


DECLARED = [
    (errors.JobUsageError("bad invocation"), codes.EXIT_USAGE),
    (errors.CapabilityVersionMismatchError("major moved"), codes.EXIT_SCHEMA_MISMATCH),
    (errors.ConfigValidationError("refused"), codes.EXIT_CONFIG),
    (FileNotFoundError("no dem"), codes.EXIT_NOT_FOUND),
    (errors.DataContractViolation("digest"), codes.EXIT_VALIDATION),
    (errors.TerrainCapabilityError("no breach"), codes.EXIT_SOLVER_ERROR),
    (errors.TerrainProductError("engine"), codes.EXIT_SOLVER_ERROR),
    (errors.EmptyCatchmentError("nothing"), codes.EXIT_SOLVER_ERROR),
]


def test_every_declared_exception_and_only_those_maps_to_a_typed_exit_code():
    assert TERRAIN_DELINEATE.exceptions == tuple(type(exception) for exception, _ in DECLARED)
    for exception, expected in DECLARED:
        assert codes.exit_code_for(exception) == expected


def test_the_base_document_validates_with_the_defaults_so_every_refusal_is_the_injected_one():
    from hydromodpy.spatial.terrain import registry

    request = TerrainDelineateRequest.model_validate(VALID_INPUTS)
    distinct = VALID_INPUTS | {"outlets": _outlets("cheze", "cheze-2")}

    assert (request.dem_correction_type, request.snap_distance_m) == ("breach", 50)
    assert request.engine == registry.DEFAULT_ENGINE_ID
    # Two outlets that differ by more than case are accepted.
    assert len(TerrainDelineateRequest.model_validate(distinct).outlets) == 2


def _outlets(*ids: str) -> list[dict[str, object]]:
    return [{"site_id": one, "x": 1.0, "y": 2.0} for one in ids]


@pytest.mark.parametrize(
    "members",
    [
        {"crs_project": "lambert93"}, {"dem_correction_type": "carve"}, {"snap_distance_m": 0},
        {"snap_distance_m": -1}, {"snap_distance_m": 49.5}, {"outlets": []}, {"dem": "dem.tif"},
        {"dem": {"href": "dem.tif", "kind": "raster"}}, {"burn_streams": True},
        *({"outlets": _outlets(one)} for one in ["", "../escape", "a/b", "-leading", "x" * 65]),
        {"outlets": _outlets("cheze", "cheze")}, {"outlets": _outlets("cheze", "CHEZE")},
    ],
)  # fmt: skip
def test_a_member_the_capability_cannot_serve_is_refused(members):
    """A fractional snap is refused rather than truncated, two ids sharing one folder too."""
    shared = len(members.get("outlets") or []) == 2
    with pytest.raises(ValidationError, match="site id" if shared else None):
        TerrainDelineateRequest.model_validate(VALID_INPUTS | members)
