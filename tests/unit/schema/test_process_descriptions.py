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


@pytest.mark.parametrize("name", sorted(path.name for path in DESCRIPTIONS_DIR.glob("*.json")))
def test_committed_file_matches_generator(name: str) -> None:
    assert _committed(name) == _render_all()[name], (
        f"hydromodpy/schema/processes/{name} is stale. Run `{REFRESH}` to refresh."
    )


def test_every_json_has_a_generator() -> None:
    on_disk = {path.name for path in DESCRIPTIONS_DIR.glob("*.json")}
    assert on_disk == set(_render_all()), (
        f"a JSON file under hydromodpy/schema/processes/ has no generator. Run `{REFRESH}`."
    )


def test_index_lists_declared_capabilities() -> None:
    assert described_ids() == tuple(sorted(decl.id for decl in capability_decls()))


@pytest.mark.parametrize("decl", capability_decls(), ids=lambda decl: decl.id)
def test_description_inputs_match_model(decl) -> None:
    document = read_description(decl.id)
    assert set(document["inputs"]) == set(decl.request_model.model_fields)


@pytest.mark.parametrize("decl", capability_decls(), ids=lambda decl: decl.id)
def test_description_names_no_command(decl) -> None:
    assert "hmp:invocation" not in read_description(decl.id)


def test_unknown_capability_refused() -> None:
    with pytest.raises(JobUsageError, match="no process description for 'nope'"):
        read_description_text("nope")


def test_unserved_major_refused() -> None:
    with pytest.raises(JobUsageError, match="at major 99"):
        read_description_text(described_ids()[0], 99)
