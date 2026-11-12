"""D14e: the ``if_exists`` help text says what a run does with a taken name."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.solver.base.simulation_config import SimulationConfig


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
