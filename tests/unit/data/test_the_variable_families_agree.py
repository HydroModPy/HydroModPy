"""Every list of ``[data]`` variables names the same 28 variables, and their sources agree.

Adding a variable touches several lists (``hydromodpy/data/README.md``,
"Where to add what"). This test compares them to ``VARIABLE_SPECS`` and names
the list that is incomplete, so a forgotten entry fails here rather than at run
time. The sources agree through the registry: what a section may name in
``source =`` is what ``data_sources`` serves for that section, plus ``custom``,
and the sections this phase still guards behind an discriminated union name the
exception and the lot that lifts it.
"""

from __future__ import annotations

import dataclasses
import typing
from importlib import import_module

import pytest

from hydromodpy.core.state.run_state import LoadedDataContext
from hydromodpy.data import DataManagersConfig
from hydromodpy.data.loading._dispatch import VARIABLE_SPECS
from hydromodpy.data.loading.config_schema import SUPPORTED_DATA_MANAGER_TYPES
from hydromodpy.data.source.registry import data_sources
from hydromodpy.data.workspace.scaffold import VARIABLES
from hydromodpy.schema.sources import source_entry

# The two fields of [data] that configure the planner, not a variable.
_PLANNER_FIELDS = {"types", "inference_mode"}
# The one field of LoadedDataContext that records the load, not a variable.
_LOAD_STATE_FIELDS = {"loaded_plan_types"}

# Sections that still choose a model of options by the value of ``source``.
# Their tags are held equal to the registry by the test below, and the lot that
# makes ``custom`` a source of the port lifts the exception.
_UNION_SECTIONS = {"dem", "geology", "crossings"}
# Sections whose only source is the user's own files. The registry holds nothing
# for them until ``custom`` becomes a source of the port.
_CUSTOM_ONLY_SECTIONS = {
    "lake_abacus",
    "lake_bathymetry",
    "lake_geometry",
    "lake_inflow",
    "lake_levels",
    "lake_outflow",
    "lake_withdrawal",
    "layer_base",
    "soil_capacity",
    "substratum",
}
# Sources computed from the section alone or read from a local file.
# They contact no host.
_LOCAL_SOURCES = {"explore2", "synthetic", "constant"}


def _families() -> dict[str, set[str]]:
    return {
        "DataManagersConfig fields (data/loading/config_schema.py)": (
            set(DataManagersConfig.model_fields) - _PLANNER_FIELDS
        ),
        "SUPPORTED_DATA_MANAGER_TYPES (data/loading/config_schema.py)": set(
            SUPPORTED_DATA_MANAGER_TYPES
        ),
        "LoadedDataContext fields (core/state/run_state.py)": {
            field.name for field in dataclasses.fields(LoadedDataContext)
        }
        - _LOAD_STATE_FIELDS,
        "VARIABLES (data/workspace/scaffold.py)": {spec.name for spec in VARIABLES},
    }


def test_every_variable_list_names_the_same_variables() -> None:
    expected = set(VARIABLE_SPECS)
    gaps = {
        family: {"missing": sorted(expected - names), "extra": sorted(names - expected)}
        for family, names in _families().items()
        if names != expected
    }

    assert gaps == {}, (
        f"These lists disagree with VARIABLE_SPECS (data/loading/_dispatch.py): {gaps}"
    )


def test_there_are_twenty_eight_variables() -> None:
    assert len(VARIABLE_SPECS) == 28


def _source_config_class(variable: str) -> type:
    """The class of one ``[[data.<variable>.sources]]`` entry."""
    spec = VARIABLE_SPECS[variable]
    module = import_module(spec.config_module)
    return getattr(module, spec.config_class)


def _literal_values(annotation: object) -> set[str]:
    """The values a ``Literal`` holds, reached through unions and nested models."""
    if typing.get_origin(annotation) is typing.Literal:
        return set(typing.get_args(annotation))
    values: set[str] = set()
    for member in typing.get_args(annotation):
        values |= _literal_values(member)
    model_fields = getattr(annotation, "model_fields", None)
    if model_fields and "source" in model_fields:
        values |= _literal_values(model_fields["source"].annotation)
    return values


def _source_values_of(variable: str) -> set[str] | None:
    """The values a ``Literal`` of ``source =`` holds, or None when the field is open."""
    section = _source_config_class(variable)
    sources = section.model_fields["sources"].annotation
    config = next(
        (
            member
            for member in (*typing.get_args(sources), section)
            if hasattr(member, "model_fields")
        ),
        section,
    )
    if "source" in config.model_fields:
        values = _literal_values(config.model_fields["source"].annotation)
        return values or None
    # A discriminated union: the tag is the ``source`` field of each entry model.
    values: set[str] = set()
    stack = [typing.get_args(sources)]
    while stack:
        for member in stack.pop():
            if hasattr(member, "model_fields"):
                field = member.model_fields.get("source")
                if field is not None:
                    values |= _literal_values(field.annotation)
            else:
                stack.append(typing.get_args(member))
    return values or None


def _shipped_pairs() -> set[tuple[str, str]]:
    """The (section, source id) pairs this build ships, read off the joined keys."""
    pairs = set()
    for key in data_sources.names(shipped_only=True):
        for section in VARIABLE_SPECS:
            if key.startswith(f"{section}_"):
                pairs.add((section, key[len(section) + 1 :]))
    return pairs


def test_the_shipped_keys_cut_into_one_section_each() -> None:
    """Every shipped key matches exactly one section; a second match would hide a collision."""
    pairs = _shipped_pairs()
    assert len(pairs) == len(data_sources.names(shipped_only=True))
    assert len({section for section, _id in pairs}) == 18


@pytest.mark.parametrize("variable", sorted(VARIABLE_SPECS))
def test_the_source_values_of_a_section_are_the_sources_of_its_registry(variable: str) -> None:
    """What a section may name and what its manager can serve are one list now.

    An open ``source`` field is checked on the registry at read time, so the
    agreement is by construction: the values are the section's served ids plus
    ``custom``. The sections that still choose a model of options by the value
    of ``source`` keep their ``Literal``, and its tags are held equal to the
    registry below until the lot that lifts it.
    """
    values = _source_values_of(variable)
    served = set(data_sources.names(variable, shipped_only=True))
    if values is None:
        assert variable not in _UNION_SECTIONS | _CUSTOM_ONLY_SECTIONS, (
            f"{variable} holds an open source field and does not belong there"
        )
        return
    if variable in _CUSTOM_ONLY_SECTIONS:
        # ``custom`` becomes a source of the port with the file-content lot.
        assert values == {"custom"}, variable
        return
    assert values - {"custom"} == served, (
        f"The `source` values of {variable} and the sources registered for its section "
        f"disagree: config {sorted(values - {'custom'})}, registry {sorted(served)}"
    )


def test_the_union_sections_name_the_lot_that_lifts_their_exception() -> None:
    """dem, geology and crossings keep a discriminated union until custom is a source.

    The arbiter kept the unions on A3: three of the eight tags are ``custom``,
    which the registry does not hold yet, so an open string would need a case
    apart for them, rewritten by the same lot that lifts the exception.
    """
    assert sorted(_UNION_SECTIONS) == ["crossings", "dem", "geology"]
    for variable in _UNION_SECTIONS:
        assert _source_values_of(variable) is not None, variable


def test_every_shipped_source_has_a_licence_entry() -> None:
    """A source this build ships is one the licence pages speak of."""
    missing = sorted(
        (section, source_id)
        for section, source_id in _shipped_pairs()
        if source_entry(source_id) is None
    )
    assert missing == [], f"These sources lack an entry in hydromodpy/schema/sources.py: {missing}"


def test_every_shipped_source_that_contacts_a_provider_declares_its_host() -> None:
    """A downloading source publishes the host it reaches, on the licence table."""
    missing = sorted(
        (section, source_id)
        for section, source_id in _shipped_pairs()
        if source_id not in _LOCAL_SOURCES and not source_entry(source_id).hosts
    )
    assert missing == [], f"These sources reach a provider without writing its host: {missing}"


def test_a_local_source_answers_no_host() -> None:
    """The computed constants and the local grids contact nobody, by construction."""
    from hydromodpy.data.source.port import shipped_hosts

    for section, source_id in _shipped_pairs():
        if source_id in _LOCAL_SOURCES:
            assert source_entry(source_id).hosts == (), (section, source_id)


def test_an_opened_section_refuses_a_name_nothing_serves() -> None:
    """The registry check a config runs, read on one section of each opened family."""
    from hydromodpy.data.managers.timeseries_config import registered_section_source

    with pytest.raises(ValueError, match="serves"):
        registered_section_source("not-a-source", "hydrometry")
    assert registered_section_source("hubeau", "hydrometry") == "hubeau"
