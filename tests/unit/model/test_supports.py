"""The traits a solver backend can list in ``supports`` come from the modules that own them, each name once."""

from __future__ import annotations

from dataclasses import fields
from itertools import combinations

import pytest

from hydromodpy.model.boundaries.boundary_condition_registry import FLOW_BOUNDARY_DEFINITIONS
from hydromodpy.model.domain.layers_config import LAYERS, PASS_THROUGH
from hydromodpy.model.forcing.soil_config import SOIL
from hydromodpy.model.initial.state import INITIAL_STATE_TYPES, SolvedState
from hydromodpy.model.model import ModelOptions
from hydromodpy.model.properties.property_table import K_TENSOR
from hydromodpy.model.sinks_sources.container import SINK_SOURCE_TRAITS
from hydromodpy.model.supports import INITIAL_STATE_TRAITS, SUPPORT_SOURCES, SUPPORTS

pytestmark = pytest.mark.fast


@pytest.mark.parametrize(
    ("source", "names"),
    [
        ("boundary", frozenset(FLOW_BOUNDARY_DEFINITIONS)),
        ("option", frozenset(field.name for field in fields(ModelOptions))),
        ("initial_state", frozenset({"head_rule", "steady_start", "cyclic_start", "prior_state"})),
        ("sink_source", SINK_SOURCE_TRAITS),
        ("soil", frozenset({SOIL})),
        ("property", frozenset({K_TENSOR})),
        ("layering", frozenset({LAYERS, PASS_THROUGH})),
    ],
)
def test_each_source_gives_the_names_of_its_own_table(source: str, names: frozenset[str]) -> None:
    assert SUPPORT_SOURCES[source] == names


def test_the_sources_are_the_seven_tables_and_their_sizes_are_known() -> None:
    sizes = {source: len(names) for source, names in SUPPORT_SOURCES.items()}

    assert sizes == {
        "boundary": 9,
        "option": 4,
        "initial_state": 4,
        "sink_source": 5,
        "soil": 1,
        "property": 1,
        "layering": 2,
    }


def test_the_new_traits_are_spelled_as_a_backend_lists_them() -> None:
    """A backend writes these names in its ``supports``, so a rename is a contract change."""
    assert SINK_SOURCE_TRAITS == {"recharge", "wells", "etp", "flow_barriers", "cutoff_wall"}
    assert (SOIL, K_TENSOR, LAYERS, PASS_THROUGH) == ("soil", "k_tensor", "layers", "pass_through")


_PAIRS = list(combinations(sorted(SUPPORT_SOURCES), 2))


@pytest.mark.parametrize(("first", "second"), _PAIRS, ids=["-".join(pair) for pair in _PAIRS])
def test_no_name_belongs_to_two_sources(first: str, second: str) -> None:
    """A shared name would let a backend honour a boundary when it meant an option."""
    assert SUPPORT_SOURCES[first] & SUPPORT_SOURCES[second] == frozenset()


def test_the_set_is_the_union_of_the_sources() -> None:
    assert frozenset().union(*SUPPORT_SOURCES.values()) == SUPPORTS
    assert len(SUPPORTS) == sum(len(names) for names in SUPPORT_SOURCES.values())


def test_every_state_a_document_can_choose_has_a_trait_and_the_solved_state_has_none() -> None:
    """The solved state comes from an auxiliary solve, never from a TOML."""
    chosen = tuple(state for state in INITIAL_STATE_TYPES if state is not SolvedState)

    assert tuple(INITIAL_STATE_TRAITS) == chosen
    assert len(set(INITIAL_STATE_TRAITS.values())) == len(chosen)
