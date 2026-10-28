"""The declaration of ``terrain-delineate``, and what its document refuses.

The exit-code assertions are the point of the first half: the generated
process description publishes one code per declared exception, read from
``exit_code_for`` and never from the specification, so a class that falls
through to ``EXIT_GENERIC`` would publish "report this as a bug" for an
ordinary refusal. That is exactly the defect F4a repaired for one code, and
this pins it for the six the capability can raise.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.cli.helpers import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_SCHEMA_MISMATCH,
    EXIT_SOLVER_ERROR,
    EXIT_USAGE,
    EXIT_VALIDATION,
    exit_code_for,
)
from hydromodpy.core.exceptions import (
    CapabilityVersionMismatchError,
    ConfigValidationError,
    DataContractViolation,
    EmptyCatchmentError,
    JobUsageError,
    TerrainCapabilityError,
    TerrainProductError,
)
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
    assert TERRAIN_DELINEATE.id == "terrain-delineate"
    assert TERRAIN_DELINEATE.major == 1
    assert TERRAIN_DELINEATE.output_ids == (
        "watershed_vector",
        "watershed_table",
        "outlets_snapped",
        "flow_direction",
        "flow_accumulation",
        "dem_corrected",
        "inputset",
        "outcome",
    )


def test_no_declared_output_claims_a_name_the_job_does_not_produce():
    paths = {output.path for output in TERRAIN_DELINEATE.outputs}

    assert not paths & NAMES_THE_JOB_DOES_NOT_PRODUCE


def test_the_accumulation_declares_the_transform_the_chain_really_writes():
    accumulation = TERRAIN_DELINEATE.output("flow_accumulation")

    assert accumulation.extra["hmp:transform"] == "ln"
    assert accumulation.extra["hmp:units"] == "cells"


DECLARED = [
    (JobUsageError("bad invocation"), EXIT_USAGE),
    (CapabilityVersionMismatchError("major moved"), EXIT_SCHEMA_MISMATCH),
    (ConfigValidationError("refused"), EXIT_CONFIG),
    (FileNotFoundError("no dem"), EXIT_NOT_FOUND),
    (DataContractViolation("digest"), EXIT_VALIDATION),
    (TerrainCapabilityError("no breach"), EXIT_SOLVER_ERROR),
    (TerrainProductError("engine"), EXIT_SOLVER_ERROR),
    (EmptyCatchmentError("nothing"), EXIT_SOLVER_ERROR),
]


def test_every_declared_exception_and_only_those_maps_to_a_typed_exit_code():
    assert TERRAIN_DELINEATE.exceptions == tuple(type(exception) for exception, _ in DECLARED)
    for exception, expected in DECLARED:
        assert exit_code_for(exception) == expected


def test_the_base_document_validates_so_every_refusal_below_is_the_injected_one():
    request = TerrainDelineateRequest.model_validate(VALID_INPUTS)

    assert request.dem_correction_type == "breach"
    assert request.snap_distance_m == 50


def _outlets(*ids: str) -> list[dict[str, object]]:
    return [{"site_id": one, "x": 1.0, "y": 2.0} for one in ids]


@pytest.mark.parametrize(
    "members",
    [
        {"crs_project": "lambert93"},
        {"dem_correction_type": "carve"},
        {"snap_distance_m": 0},
        {"snap_distance_m": -1},
        {"snap_distance_m": 49.5},
        {"outlets": []},
        {"dem": "dem.tif"},
        {"dem": {"href": "dem.tif", "kind": "raster"}},
        {"burn_streams": True},
        *(
            {"outlets": _outlets(site_id)}
            for site_id in ["", "../escape", "a/b", "-leading", "x" * 65]
        ),
        {"outlets": _outlets("cheze", "cheze")},
        {"outlets": _outlets("cheze", "CHEZE")},
    ],
)
def test_a_member_the_capability_cannot_serve_is_refused(members):
    """A fractional snap is refused rather than truncated, two ids sharing one folder too."""
    shared = len(members.get("outlets") or []) == 2
    with pytest.raises(ValidationError, match="site id" if shared else None):
        TerrainDelineateRequest.model_validate(VALID_INPUTS | members)


def test_two_outlets_that_differ_by_more_than_case_are_accepted():
    payload = VALID_INPUTS | {"outlets": _outlets("cheze", "cheze-2")}

    assert len(TerrainDelineateRequest.model_validate(payload).outlets) == 2


# --------------------------------------------------------------------------- #
# The terrain engine a request names (from the terrain registry tests)
# --------------------------------------------------------------------------- #


def test_a_request_that_names_no_engine_carries_the_default():
    from hydromodpy.spatial.terrain import registry

    assert TerrainDelineateRequest.model_validate(VALID_INPUTS).engine == registry.DEFAULT_ENGINE_ID


def test_the_capability_refuses_an_engine_this_installation_does_not_serve():
    from hydromodpy.spatial.site_selection.hydrology.worker import (
        refuse_an_engine_this_installation_does_not_serve,
    )
    from hydromodpy.spatial.terrain import registry

    inputs = TerrainDelineateRequest.model_validate(VALID_INPUTS | {"engine": "pysheds"})

    with pytest.raises(ConfigValidationError) as raised:
        refuse_an_engine_this_installation_does_not_serve(inputs)

    assert "inputs.engine" in str(raised.value)
    assert registry.ENTRY_POINT_GROUP in str(raised.value)
