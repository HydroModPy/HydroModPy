"""The committed process descriptions, and the drift that must never happen.

A generated artifact without a gate drifts. So the first assertion here is the
byte comparison, and everything after it is about what the document may not
claim. The capabilities are the three declarations the descriptions are
generated from; no CLI verb runs a capability by its id.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import hydromodpy.schema.processes as processes_package
from hydromodpy.core.exceptions import JobUsageError
from hydromodpy.schema.processes import described_ids, read_description, read_description_text

REFRESH = "python -m tools.processes"
DESCRIPTIONS_DIR = Path(processes_package.__file__).resolve().parent


def capability_decls() -> tuple[Any, ...]:
    """Return the declarations the descriptions are generated from."""
    from hydromodpy.data.request.job import DATA_REQUEST
    from hydromodpy.model.domain.capability import DOMAIN_BUILD

    return (DATA_REQUEST, DOMAIN_BUILD)


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


@pytest.mark.parametrize("decl", capability_decls(), ids=lambda decl: decl.id)
def test_the_description_declares_the_inputs_the_model_accepts(decl) -> None:
    document = read_description(decl.id)
    assert set(document["inputs"]) == set(decl.request_model.model_fields)


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
