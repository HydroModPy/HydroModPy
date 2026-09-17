"""A request this process refuses names the member the caller got wrong.

``request.json`` is written by a stranger — a workflow engine, a shell script,
a portal — which cannot read a Python traceback and cannot parse a paragraph.
Every refusal here is a ``ConfigValidationError`` carrying the RFC 6901
pointer of the member at fault, and the exit code of the whole class of
failure is 14 and never 1.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_SCHEMA_MISMATCH, exit_code_for
from hydromodpy.core.exceptions import CapabilityVersionMismatchError, ConfigValidationError
from hydromodpy.schema.capability import CapabilityDecl
from hydromodpy.schema.job import JobDirectory
from hydromodpy.schema.job.request import (
    check_process,
    read_request,
    requested_outputs,
    validate_inputs,
)

VALID: dict[str, Any] = {
    "process": {"id": "demo-delineate", "version": "1.2.3"},
    "inputs": {
        "dem": {"href": "inputs/dem.tif", "type": "image/tiff; application=geotiff"},
        "outlets": [{"site_id": "cheze_outlet", "x": 348120.0, "y": 6781450.0}],
        "crs_project": "EPSG:2154",
        "snap_distance_m": 50,
    },
    "outputs": {},
    "response": "document",
}


def _job(tmp_path: Path, document: Any) -> JobDirectory:
    root = tmp_path / "job_4711"
    root.mkdir()
    text = document if isinstance(document, str) else json.dumps(document)
    (root / "request.json").write_text(text, encoding="utf-8")
    return JobDirectory.open(root)


def _refusal(tmp_path: Path, document: Any) -> ConfigValidationError:
    with pytest.raises(ConfigValidationError) as excinfo:
        read_request(_job(tmp_path, document))
    return excinfo.value


def test_the_baseline_request_is_read(tmp_path: Path, demo_capability: CapabilityDecl) -> None:
    """Guards every refusal below: a baseline that stopped loading would make
    each case pass on a fault it did not inject."""
    request = read_request(_job(tmp_path, VALID))

    assert request.process.id == "demo-delineate"
    assert check_process(request, demo_capability) == ()
    assert validate_inputs(request, demo_capability).crs_project == "EPSG:2154"


def test_a_request_that_is_not_json_is_refused_at_14(tmp_path: Path) -> None:
    refusal = _refusal(tmp_path, '{"process": {"id": "demo-delineate",}}')

    assert exit_code_for(refusal) == EXIT_CONFIG
    assert "not valid JSON" in str(refusal)
    assert refusal.details == ()


def test_a_request_that_is_not_an_object_is_refused_at_the_root(tmp_path: Path) -> None:
    refusal = _refusal(tmp_path, [VALID])

    assert exit_code_for(refusal) == EXIT_CONFIG
    assert refusal.details[0]["pointer"] == ""


def test_a_missing_process_member_is_pointed_at(tmp_path: Path) -> None:
    document = {key: value for key, value in VALID.items() if key != "process"}

    refusal = _refusal(tmp_path, document)

    assert [detail["pointer"] for detail in refusal.details] == ["/process"]


def test_an_unknown_member_inside_the_process_reference_is_pointed_at(tmp_path: Path) -> None:
    document = dict(VALID, process={"id": "demo-delineate", "revision": 3})

    refusal = _refusal(tmp_path, document)

    assert refusal.details[0]["pointer"] == "/process/revision"
    assert refusal.details[0]["type"] == "extra_forbidden"


def test_an_unknown_envelope_member_is_a_warning_and_not_a_refusal(tmp_path: Path) -> None:
    """An OGC client sends envelope members this process has no use for.

    Refusing the job over one of them would refuse a request whose inputs are
    all valid; the caller is told instead, and the run goes on.
    """
    document = dict(VALID, subscriber={"successUri": "https://example.org/done"})

    request = read_request(_job(tmp_path, document))

    assert request.undeclared_members == ("subscriber",)


def test_a_request_for_another_capability_is_refused(
    tmp_path: Path, demo_capability: CapabilityDecl
) -> None:
    request = read_request(_job(tmp_path, dict(VALID, process={"id": "data-fetch"})))

    with pytest.raises(ConfigValidationError) as excinfo:
        check_process(request, demo_capability)

    assert excinfo.value.details[0]["pointer"] == "/process/id"


def test_another_major_version_is_refused_at_11(
    tmp_path: Path, demo_capability: CapabilityDecl
) -> None:
    """The major is what a shim pins, so a bump of it must be told, not ignored."""
    document = dict(VALID, process={"id": "demo-delineate", "version": "2.0.0"})
    request = read_request(_job(tmp_path, document))

    with pytest.raises(CapabilityVersionMismatchError) as excinfo:
        check_process(request, demo_capability)

    assert exit_code_for(excinfo.value) == EXIT_SCHEMA_MISMATCH


def test_another_minor_version_is_a_warning(
    tmp_path: Path, demo_capability: CapabilityDecl
) -> None:
    document = dict(VALID, process={"id": "demo-delineate", "version": "1.0.0"})
    request = read_request(_job(tmp_path, document))

    warnings = check_process(request, demo_capability)

    assert len(warnings) == 1
    assert "1.2.3" in warnings[0]


def test_an_absent_version_is_accepted(tmp_path: Path, demo_capability: CapabilityDecl) -> None:
    request = read_request(_job(tmp_path, dict(VALID, process={"id": "demo-delineate"})))

    assert check_process(request, demo_capability) == ()


def test_a_version_that_is_not_a_version_is_refused(
    tmp_path: Path, demo_capability: CapabilityDecl
) -> None:
    document = dict(VALID, process={"id": "demo-delineate", "version": "latest"})
    request = read_request(_job(tmp_path, document))

    with pytest.raises(ConfigValidationError) as excinfo:
        check_process(request, demo_capability)

    assert excinfo.value.details[0]["pointer"] == "/process/version"


def test_no_named_output_means_every_declared_output(
    tmp_path: Path, demo_capability: CapabilityDecl
) -> None:
    request = read_request(_job(tmp_path, VALID))

    assert requested_outputs(request, demo_capability) == demo_capability.outputs


def test_named_outputs_come_back_in_declaration_order(
    tmp_path: Path, demo_capability: CapabilityDecl
) -> None:
    document = dict(VALID, outputs={"outcome": {}, "watershed_vector": {}})
    request = read_request(_job(tmp_path, document))

    assert [output.id for output in requested_outputs(request, demo_capability)] == [
        "watershed_vector",
        "outcome",
    ]


def test_asking_for_an_output_nobody_produces_is_refused(
    tmp_path: Path, demo_capability: CapabilityDecl
) -> None:
    """Told before the run, not by finding the file missing after the seal."""
    document = dict(VALID, outputs={"flow_direction": {}})
    request = read_request(_job(tmp_path, document))

    with pytest.raises(ConfigValidationError) as excinfo:
        requested_outputs(request, demo_capability)

    assert excinfo.value.details[0]["pointer"] == "/outputs/flow_direction"


@pytest.mark.parametrize(
    ("member", "value", "pointer"),
    [
        ("crs_project", "lambert93", "/inputs/crs_project"),
        ("snap_distance_m", -5, "/inputs/snap_distance_m"),
        ("outlets", [], "/inputs/outlets"),
        ("dem", {"href": "dem.tif", "kind": "raster"}, "/inputs/dem/kind"),
    ],
)
def test_a_bad_input_is_pointed_at_the_member_the_document_wrote(
    tmp_path: Path,
    demo_capability: CapabilityDecl,
    member: str,
    value: Any,
    pointer: str,
) -> None:
    document = dict(VALID, inputs=dict(VALID["inputs"], **{member: value}))
    request = read_request(_job(tmp_path, document))

    with pytest.raises(ConfigValidationError) as excinfo:
        validate_inputs(request, demo_capability)

    assert exit_code_for(excinfo.value) == EXIT_CONFIG
    assert [detail["pointer"] for detail in excinfo.value.details] == [pointer]


def test_an_input_the_capability_does_not_declare_is_refused(
    tmp_path: Path, demo_capability: CapabilityDecl
) -> None:
    """The envelope accepts unknown members; the inputs never do."""
    document = dict(VALID, inputs=dict(VALID["inputs"], flow_algorithm="dinf"))
    request = read_request(_job(tmp_path, document))

    with pytest.raises(ConfigValidationError) as excinfo:
        validate_inputs(request, demo_capability)

    assert excinfo.value.details[0]["pointer"] == "/inputs/flow_algorithm"
    assert excinfo.value.details[0]["type"] == "extra_forbidden"


def test_a_missing_input_keeps_the_pointer_of_the_key_it_lacks(
    tmp_path: Path, demo_capability: CapabilityDecl
) -> None:
    inputs = {key: value for key, value in VALID["inputs"].items() if key != "crs_project"}
    request = read_request(_job(tmp_path, dict(VALID, inputs=inputs)))

    with pytest.raises(ConfigValidationError) as excinfo:
        validate_inputs(request, demo_capability)

    assert excinfo.value.details[0]["pointer"] == "/inputs/crs_project"
    assert excinfo.value.details[0]["type"] == "missing"
