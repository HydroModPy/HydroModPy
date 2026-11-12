"""Reading and checking ``request.json``, written by a caller that cannot read a traceback.

A refusal is a ``ConfigValidationError`` that carries the RFC 6901 pointer of the
member at fault, and the whole class of failure exits 14 and never 1. An unknown
member of the envelope is a warning, an unknown member of the inputs is a refusal.
The job id is a content address of the process and its resolved inputs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.cli.exit_codes import EXIT_CONFIG, EXIT_SCHEMA_MISMATCH, exit_code_for
from hydromodpy.core.exceptions import CapabilityVersionMismatchError, ConfigValidationError
from hydromodpy.schema.capability import CapabilityDecl
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.request import (
    check_process,
    content_address,
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


def job_with(tmp_path: Path, document: Any) -> JobDirectory:
    root = tmp_path / "job_4711"
    root.mkdir()
    text = document if isinstance(document, str) else json.dumps(document)
    (root / "request.json").write_text(text, encoding="utf-8")
    return JobDirectory.open(root)


def request_with(tmp_path: Path, **members: Any):
    return read_request(job_with(tmp_path, VALID | members))


def test_valid_request_is_read(tmp_path: Path, demo_capability: CapabilityDecl) -> None:
    # The refusals below start from this document, so it must keep loading.
    request = request_with(tmp_path)

    assert request.process.id == "demo-delineate"
    assert check_process(request, demo_capability) == ()
    assert validate_inputs(request, demo_capability).crs_project == "EPSG:2154"


def test_text_that_is_not_json(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError) as excinfo:
        read_request(job_with(tmp_path, '{"process": {"id": "demo-delineate",}}'))

    assert exit_code_for(excinfo.value) == EXIT_CONFIG
    assert "not valid JSON" in str(excinfo.value)
    assert excinfo.value.details == ()


# (document, pointer of the member at fault, pydantic error type)
READ_REFUSALS = [
    pytest.param([VALID], "", "value_error", id="not an object"),
    pytest.param(
        {key: value for key, value in VALID.items() if key != "process"},
        "/process",
        "missing",
        id="no process",
    ),
    pytest.param(
        VALID | {"process": {"id": "demo-delineate", "revision": 3}},
        "/process/revision",
        "extra_forbidden",
        id="unknown member of the process",
    ),
]


@pytest.mark.parametrize(("document", "pointer", "error_type"), READ_REFUSALS)
def test_read_refusals(tmp_path: Path, document: Any, pointer: str, error_type: str) -> None:
    with pytest.raises(ConfigValidationError) as excinfo:
        read_request(job_with(tmp_path, document))

    assert exit_code_for(excinfo.value) == EXIT_CONFIG
    assert [(d["pointer"], d["type"]) for d in excinfo.value.details] == [(pointer, error_type)]


def test_unknown_envelope_member_is_a_warning(tmp_path: Path) -> None:
    # An OGC client sends members this process ignores. The inputs may still be valid.
    request = request_with(tmp_path, subscriber={"successUri": "https://example.org/done"})

    assert request.undeclared_members == ("subscriber",)


# (process member, pointer of the refusal)
PROCESS_REFUSALS = [
    pytest.param({"id": "data-request"}, "/process/id", id="another capability"),
    pytest.param(
        {"id": "demo-delineate", "version": "latest"}, "/process/version", id="not a version"
    ),
]


@pytest.mark.parametrize(("process", "pointer"), PROCESS_REFUSALS)
def test_process_refusals(
    tmp_path: Path, demo_capability: CapabilityDecl, process: dict, pointer: str
) -> None:
    request = request_with(tmp_path, process=process)

    with pytest.raises(ConfigValidationError) as excinfo:
        check_process(request, demo_capability)

    assert excinfo.value.details[0]["pointer"] == pointer


def test_other_major_version_exits_11(tmp_path: Path, demo_capability: CapabilityDecl) -> None:
    # A shim pins the major, so a bump of it must be told.
    request = request_with(tmp_path, process={"id": "demo-delineate", "version": "2.0.0"})

    with pytest.raises(CapabilityVersionMismatchError) as excinfo:
        check_process(request, demo_capability)

    assert exit_code_for(excinfo.value) == EXIT_SCHEMA_MISMATCH


def test_other_minor_version_is_a_warning(tmp_path: Path, demo_capability: CapabilityDecl) -> None:
    request = request_with(tmp_path, process={"id": "demo-delineate", "version": "1.0.0"})

    warnings = check_process(request, demo_capability)

    assert len(warnings) == 1
    assert "1.2.3" in warnings[0]


def test_every_output_when_none_is_named(tmp_path: Path, demo_capability: CapabilityDecl) -> None:
    request = request_with(tmp_path)

    assert requested_outputs(request, demo_capability) == demo_capability.outputs


def test_named_outputs_follow_declaration_order(
    tmp_path: Path, demo_capability: CapabilityDecl
) -> None:
    request = request_with(tmp_path, outputs={"outcome": {}, "watershed_vector": {}})

    outputs = requested_outputs(request, demo_capability)

    assert [output.id for output in outputs] == ["watershed_vector", "outcome"]


def test_output_nobody_produces_is_refused(tmp_path: Path, demo_capability: CapabilityDecl) -> None:
    # Told before the run, not by finding the file missing after the seal.
    request = request_with(tmp_path, outputs={"flow_direction": {}})

    with pytest.raises(ConfigValidationError) as excinfo:
        requested_outputs(request, demo_capability)

    assert excinfo.value.details[0]["pointer"] == "/outputs/flow_direction"


# (inputs, pointer of the member at fault, pydantic error type)
INPUT_REFUSALS = [
    pytest.param(
        VALID["inputs"] | {"flow_algorithm": "dinf"},
        "/inputs/flow_algorithm",
        "extra_forbidden",
        id="undeclared input",
    ),
    pytest.param(
        {key: value for key, value in VALID["inputs"].items() if key != "crs_project"},
        "/inputs/crs_project",
        "missing",
        id="missing input",
    ),
]


@pytest.mark.parametrize(("inputs", "pointer", "error_type"), INPUT_REFUSALS)
def test_input_refusals(
    tmp_path: Path, demo_capability: CapabilityDecl, inputs: dict, pointer: str, error_type: str
) -> None:
    request = request_with(tmp_path, inputs=inputs)

    with pytest.raises(ConfigValidationError) as excinfo:
        validate_inputs(request, demo_capability)

    assert excinfo.value.details[0]["pointer"] == pointer
    assert excinfo.value.details[0]["type"] == error_type


def test_job_id_is_in_the_content() -> None:
    # The id survives cp, tar and a move. Key order does not matter.
    first = content_address(
        process_id="demo-delineate",
        process_version="1.2.3",
        inputs={"dem": "sha256:" + "a" * 64, "crs_project": "EPSG:2154"},
    )
    second = content_address(
        process_id="demo-delineate",
        process_version="1.2.3",
        inputs={"crs_project": "EPSG:2154", "dem": "sha256:" + "a" * 64},
    )

    assert first == second
    assert first.startswith("sha256:")


def test_another_input_is_another_job() -> None:
    def job_id(digest: str) -> str:
        inputs = {"dem": "sha256:" + digest * 64}
        return content_address(process_id="demo-delineate", process_version="1.2.3", inputs=inputs)

    assert job_id("a") != job_id("b")
