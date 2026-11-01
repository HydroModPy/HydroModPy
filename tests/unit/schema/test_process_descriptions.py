"""The committed process descriptions, and the drift that must never happen.

A generated artefact without a gate drifts. So the first assertion here is the
byte comparison, and everything after it is about what the document may not
claim. The capabilities are the three declarations the descriptions are
generated from; no CLI verb runs a capability by its id.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

import hydromodpy.schema.processes as processes_package
from hydromodpy.cli.helpers import exit_code_for
from hydromodpy.core.exceptions import JobUsageError
from hydromodpy.schema.capability import NAMES_THE_JOB_DOES_NOT_PRODUCE
from hydromodpy.schema.processes import (
    INDEX_FILENAME,
    described_ids,
    description_filename,
    read_description,
    read_description_text,
    read_index,
)

REFRESH = "python -m tools.processes"
DESCRIPTIONS_DIR = Path(processes_package.__file__).resolve().parent


def capability_decls() -> tuple[Any, ...]:
    """Return the declarations the descriptions are generated from."""
    from hydromodpy.data.request.job import DATA_REQUEST
    from hydromodpy.site_selection.hydrology.capability import TERRAIN_DELINEATE
    from hydromodpy.spatial.domain.capability import DOMAIN_BUILD

    return (DATA_REQUEST, DOMAIN_BUILD, TERRAIN_DELINEATE)


def _render_all() -> dict[str, str]:
    from tools.processes.generate import render_all

    return render_all()


def _committed(name: str) -> str:
    return (DESCRIPTIONS_DIR / name).read_text(encoding="utf-8")


def _nodes_with_examples(node: Any) -> list[dict[str, Any]]:
    """Return every sub-schema that publishes examples of itself."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if "examples" in node:
            found.append(node)
        for value in node.values():
            found.extend(_nodes_with_examples(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_nodes_with_examples(item))
    return found


@pytest.mark.parametrize("name", sorted(path.name for path in DESCRIPTIONS_DIR.glob("*.json")))
def test_the_committed_file_is_what_the_generator_writes(name: str) -> None:
    assert _committed(name) == _render_all()[name], (
        f"hydromodpy/schema/processes/{name} is stale. Run `{REFRESH}` to refresh."
    )


def test_the_generator_owns_every_json_file_that_is_committed() -> None:
    on_disk = {path.name for path in DESCRIPTIONS_DIR.glob("*.json")}
    assert on_disk == set(_render_all()), (
        f"a JSON file under hydromodpy/schema/processes/ has no generator. Run `{REFRESH}`."
    )


def test_the_index_names_every_capability_this_build_declares() -> None:
    assert described_ids() == tuple(sorted(decl.id for decl in capability_decls()))


def test_every_index_entry_points_at_a_file_that_reads() -> None:
    for entry in read_index()["processes"]:
        assert entry["file"] == description_filename(entry["id"], entry["major"])
        assert read_description(entry["id"], entry["major"])["id"] == entry["id"]


def test_the_index_is_not_described_as_a_process() -> None:
    assert INDEX_FILENAME not in {entry["file"] for entry in read_index()["processes"]}


@pytest.mark.parametrize("decl", capability_decls(), ids=lambda decl: decl.id)
def test_the_description_declares_the_inputs_the_model_accepts(decl) -> None:
    document = read_description(decl.id)
    assert set(document["inputs"]) == set(decl.request_model.model_fields)


@pytest.mark.parametrize("decl", capability_decls(), ids=lambda decl: decl.id)
def test_every_embedded_input_schema_is_a_valid_2020_12_document(decl) -> None:
    for name, entry in read_description(decl.id)["inputs"].items():
        assert entry["schema"]["$schema"] == "https://json-schema.org/draft/2020-12/schema", name
        Draft202012Validator.check_schema(entry["schema"])


@pytest.mark.parametrize("decl", capability_decls(), ids=lambda decl: decl.id)
def test_no_published_example_is_refused_by_the_schema_that_publishes_it(decl) -> None:
    """An example its own schema rejects is a lie a shim would paste into a request."""
    checked = 0
    for name, entry in read_description(decl.id)["inputs"].items():
        for node in _nodes_with_examples(entry["schema"]):
            assert "$ref" not in node, f"{name}: an example sits next to a $ref, unresolvable here"
            validator = Draft202012Validator(node)
            for example in node["examples"]:
                validator.validate(example)
                checked += 1
    assert checked, f"{decl.id} publishes no example at all"


@pytest.mark.parametrize("decl", capability_decls(), ids=lambda decl: decl.id)
def test_the_description_cannot_claim_an_exit_code_the_mapper_does_not_produce(decl) -> None:
    declared = {
        entry["code"]: entry["exit_code"] for entry in read_description(decl.id)["hmp:exceptions"]
    }
    for exc_cls in decl.exceptions:
        code = getattr(exc_cls, "code", None)
        code = code if isinstance(code, str) else exc_cls.__name__
        assert declared[code] == exit_code_for(exc_cls.__new__(exc_cls))
    assert len(declared) == len(decl.exceptions)


@pytest.mark.parametrize("decl", capability_decls(), ids=lambda decl: decl.id)
def test_the_description_declares_the_paths_the_capability_declares(decl) -> None:
    outputs = read_description(decl.id)["outputs"]
    assert set(outputs) == set(decl.output_ids)
    for output in decl.outputs:
        entry = outputs[output.id]
        assert entry["hmp:path"] == output.path
        assert entry["hmp:role"] == list(output.roles)
        assert entry["schema"]["contentMediaType"] == output.media_type
        assert entry["hmp:path"] not in NAMES_THE_JOB_DOES_NOT_PRODUCE


@pytest.mark.parametrize("decl", capability_decls(), ids=lambda decl: decl.id)
def test_the_description_names_no_command_to_invoke_it(decl) -> None:
    """No CLI verb runs a capability by its id, so the document names none."""
    assert "hmp:invocation" not in read_description(decl.id)


def test_reading_an_unknown_capability_is_an_invocation_error() -> None:
    with pytest.raises(JobUsageError, match="no process description for 'nope'"):
        read_description_text("nope")


def test_reading_a_major_this_build_does_not_serve_is_an_invocation_error() -> None:
    with pytest.raises(JobUsageError, match="at major 99"):
        read_description_text(described_ids()[0], 99)


def test_the_reader_returns_the_committed_bytes_and_does_not_re_render_them() -> None:
    capability_id = described_ids()[0]
    entry = next(e for e in read_index()["processes"] if e["id"] == capability_id)
    assert read_description_text(capability_id) == _committed(entry["file"])
