"""The forcing-capable boundary ids are stated once, and the registry agrees.

Two places say which boundaries may carry a head chronicle: the validator that
refuses the declaration, and the registry entry a backend reads. They drifted
apart once already, leaving solver code that consumed a series nobody could
declare. This pins them together.
"""

from __future__ import annotations

import pytest

from hydromodpy.physics.flow.boundary_condition_registry import (
    FLOW_BOUNDARY_DEFINITIONS,
)
from hydromodpy.physics.flow.boundary_conditions import (
    FORCING_CAPABLE_DIRICHLET_BC_IDS,
)


def test_every_forcing_capable_dirichlet_id_is_marked_in_the_registry() -> None:
    for bc_id in FORCING_CAPABLE_DIRICHLET_BC_IDS:
        assert FLOW_BOUNDARY_DEFINITIONS[bc_id].supports_forcing is True


def test_no_dirichlet_boundary_is_marked_forcing_capable_behind_the_validator() -> None:
    marked = {
        bc_id
        for bc_id, definition in FLOW_BOUNDARY_DEFINITIONS.items()
        if definition.family == "dirichlet" and definition.supports_forcing
    }
    assert marked == set(FORCING_CAPABLE_DIRICHLET_BC_IDS)


@pytest.mark.parametrize("bc_id", sorted(FORCING_CAPABLE_DIRICHLET_BC_IDS))
def test_a_forcing_capable_boundary_is_a_dirichlet_one(bc_id: str) -> None:
    assert FLOW_BOUNDARY_DEFINITIONS[bc_id].family == "dirichlet"
