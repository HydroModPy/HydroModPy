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


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (JobUsageError("bad invocation"), EXIT_USAGE),
        (CapabilityVersionMismatchError("major moved"), EXIT_SCHEMA_MISMATCH),
        (ConfigValidationError("refused"), EXIT_CONFIG),
        (FileNotFoundError("no dem"), EXIT_NOT_FOUND),
        (DataContractViolation("digest"), EXIT_VALIDATION),
        (TerrainProductError("engine"), EXIT_SOLVER_ERROR),
        (EmptyCatchmentError("nothing"), EXIT_SOLVER_ERROR),
    ],
)
def test_every_declared_exception_maps_to_a_typed_exit_code(exception, expected):
    assert exit_code_for(exception) == expected
    assert isinstance(exception, TERRAIN_DELINEATE.exceptions)


def test_the_declared_exceptions_are_the_ones_the_test_above_covers():
    assert TERRAIN_DELINEATE.exceptions == (
        JobUsageError,
        CapabilityVersionMismatchError,
        ConfigValidationError,
        FileNotFoundError,
        DataContractViolation,
        TerrainProductError,
        EmptyCatchmentError,
    )


def test_the_base_document_validates_so_every_refusal_below_is_the_injected_one():
    request = TerrainDelineateRequest.model_validate(VALID_INPUTS)

    assert request.dem_correction_type == "breach"
    assert request.snap_distance_m == 50


@pytest.mark.parametrize(
    ("member", "value"),
    [
        ("crs_project", "lambert93"),
        ("dem_correction_type", "carve"),
        ("snap_distance_m", 0),
        ("snap_distance_m", -1),
        ("outlets", []),
        ("dem", "dem.tif"),
        ("dem", {"href": "dem.tif", "kind": "raster"}),
    ],
)
def test_a_member_the_capability_cannot_serve_is_refused(member, value):
    payload = dict(VALID_INPUTS) | {member: value}

    with pytest.raises(ValidationError):
        TerrainDelineateRequest.model_validate(payload)


def test_an_unknown_member_of_inputs_is_refused():
    with pytest.raises(ValidationError):
        TerrainDelineateRequest.model_validate(dict(VALID_INPUTS) | {"burn_streams": True})


@pytest.mark.parametrize("site_id", ["", "../escape", "a/b", "-leading", "x" * 65])
def test_a_site_id_that_cannot_be_a_directory_name_is_refused(site_id):
    payload = dict(VALID_INPUTS) | {"outlets": [{"site_id": site_id, "x": 1.0, "y": 2.0}]}

    with pytest.raises(ValidationError):
        TerrainDelineateRequest.model_validate(payload)


def test_a_fractional_snap_distance_is_refused_rather_than_truncated():
    payload = dict(VALID_INPUTS) | {"snap_distance_m": 49.5}

    with pytest.raises(ValidationError):
        TerrainDelineateRequest.model_validate(payload)


@pytest.mark.parametrize("second_id", ["cheze", "CHEZE"])
def test_two_outlets_that_would_share_one_directory_are_refused(second_id):
    payload = dict(VALID_INPUTS) | {
        "outlets": [
            {"site_id": "cheze", "x": 1.0, "y": 2.0},
            {"site_id": second_id, "x": 3.0, "y": 4.0},
        ]
    }

    with pytest.raises(ValidationError, match="site id"):
        TerrainDelineateRequest.model_validate(payload)


def test_two_outlets_that_differ_by_more_than_case_are_accepted():
    payload = dict(VALID_INPUTS) | {
        "outlets": [
            {"site_id": "cheze", "x": 1.0, "y": 2.0},
            {"site_id": "cheze-2", "x": 3.0, "y": 4.0},
        ]
    }

    assert len(TerrainDelineateRequest.model_validate(payload).outlets) == 2
