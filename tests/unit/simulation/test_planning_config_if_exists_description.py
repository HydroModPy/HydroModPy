"""D14e: the ``if_exists`` help text must say what registration actually does."""

from __future__ import annotations

import uuid

from hydromodpy.simulation.planning.config import SimulationConfig
from tests._helpers.fixtures_catalog import simulation_catalog


def _if_exists_description() -> str:
    return SimulationConfig.model_fields["if_exists"].description or ""


def test_if_exists_description_does_not_claim_replace_takes_the_name() -> None:
    description = _if_exists_description()
    assert "takes the name" not in description


def test_if_exists_description_names_the_versioned_registration_replace_actually_does() -> None:
    description = _if_exists_description()
    assert "next free" in description
    assert "stem.vN" in description


def test_replace_actually_registers_under_the_next_free_version(tmp_path) -> None:
    """Ground the description in the real behavior of registration.py.

    ``replace`` trashes the predecessor but never renames the incoming run
    to the bare, now-free name: it still mints ``stem.vN``, exactly as
    ``version`` mode would for a live collision.
    """
    with simulation_catalog(tmp_path / "workspace") as cat:
        first = str(uuid.uuid4())
        cat.register_simulation(first, project="p", solver="modflow6", name="dup")

        second = str(uuid.uuid4())
        result = cat.register_simulation(
            second, project="p", solver="modflow6", name="dup", if_exists="replace"
        )

        assert result.name == "dup.v2"
        predecessor_name = cat._backend.fetch_one(
            "SELECT name FROM simulations WHERE sim_id = ?", [first]
        )[0]
        assert predecessor_name == "dup"
