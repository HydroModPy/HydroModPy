"""What the ``chain`` verb adds to the chain: a registry, and two refusals.

The composition is tested where it lives, in ``tests/unit/schema``. What lives
here is the wiring: an id resolved against the declarations this build serves,
and the two ways a caller can point the verb at something that is not a chain.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.cli._workers.process import declaration_for, run_capability_chain
from hydromodpy.cli.main import _build_parser
from hydromodpy.core.exceptions import JobUsageError


def test_a_served_capability_resolves_to_its_declaration() -> None:
    decl = declaration_for("terrain-delineate")

    assert decl is not None
    assert decl.id == "terrain-delineate"


def test_an_unserved_capability_resolves_to_nothing_rather_than_raising() -> None:
    """``None`` and not an exception: in a chain document it is bad input."""
    assert declaration_for("no-such-capability") is None


def test_a_directory_that_does_not_exist_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(JobUsageError, match="does not exist"):
        run_capability_chain(tmp_path / "absent")


def test_a_directory_without_the_document_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(JobUsageError, match="chain.json"):
        run_capability_chain(tmp_path)


def test_a_chain_of_one_unserved_step_imports_no_engine(tmp_path: Path) -> None:
    """A refused document costs a JSON parse, never a capability body."""
    (tmp_path / "chain.json").write_text(
        json.dumps({"steps": [{"id": "only", "process": {"id": "no-such-capability"}}]}),
        encoding="utf-8",
    )

    with pytest.raises(Exception, match="does not serve"):
        run_capability_chain(tmp_path)

    assert [entry.name for entry in tmp_path.iterdir()] == ["chain.json"]


def test_the_verb_takes_the_chain_root_and_nothing_else() -> None:
    args = _build_parser().parse_args(["process", "chain", "--root", "/scratch/chains/17"])

    assert args.root == "/scratch/chains/17"
