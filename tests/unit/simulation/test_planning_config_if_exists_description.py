"""D14e: the ``if_exists`` help text says what a run does with a taken name."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.results.catalog.registration import NameTakenError, check_name_free
from hydromodpy.simulation.planning.config import SimulationConfig
from tests._helpers.run_stores import claim_run
from tests._helpers.sealed_runs import make_project, seal_run


def _if_exists_description() -> str:
    return SimulationConfig.model_fields["if_exists"].description or ""


def test_if_exists_description_does_not_claim_a_name_is_taken_over() -> None:
    description = _if_exists_description()
    assert "takes the name" not in description
    assert "``replace``" not in description
    assert "never reused" in description


def test_if_exists_description_names_the_next_free_version() -> None:
    description = _if_exists_description()
    assert "next free" in description
    assert "stem.vN" in description


def test_replace_is_refused_with_what_to_write_instead() -> None:
    with pytest.raises(ValidationError, match="'replace' is gone.*'version'.*'fail'"):
        SimulationConfig(if_exists="replace")


def test_version_writes_a_taken_name_under_the_next_free_version(tmp_path) -> None:
    """A sealed ``dup`` sends the next run of that name to ``dup.v2``."""
    project = make_project(tmp_path / "project")
    seal_run(project, "dup")

    claim = claim_run(project, "dup")

    assert claim.name == "dup.v2"
    assert (project / "runs" / "dup").is_dir()


def test_fail_refuses_a_taken_name_and_names_its_holder(tmp_path) -> None:
    project = make_project(tmp_path / "project")
    seal_run(project, "dup")

    with pytest.raises(NameTakenError, match=r"runs/dup"):
        check_name_free(project, "dup")
    check_name_free(project, "other")
