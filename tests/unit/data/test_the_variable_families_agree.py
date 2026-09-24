"""Every list of ``[data]`` variables names the same 24 variables, and their sources agree.

Adding a variable touches several lists (``hydromodpy/data/structure.md``,
section 7). This test compares them to ``VARIABLE_SPECS`` and names the list
that is incomplete, so a forgotten entry fails here rather than at run time.
"""

from __future__ import annotations

import dataclasses
import re
import typing

from hydromodpy._lazy import LAZY_IMPORTS
from hydromodpy.core.state.data import LoadedDataContext
from hydromodpy.data import DataManagersConfig
from hydromodpy.data.loading._dispatch import VARIABLE_SPECS, get_manager_class
from hydromodpy.data.loading.config_schema import SUPPORTED_DATA_MANAGER_TYPES
from hydromodpy.data.managers.base_manager_common import CUSTOM_SOURCE
from hydromodpy.data.workspace.scaffold import VARIABLES
from hydromodpy.schema.sources import source_entry

# The two fields of [data] that configure the planner, not a variable.
_PLANNER_FIELDS = {"types", "inference_mode"}
# The one field of LoadedDataContext that records the load, not a variable.
_LOAD_STATE_FIELDS = {"loaded_plan_types"}


def _variable_of_config_name(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name.removesuffix("Config")).lower()


def _families() -> dict[str, set[str]]:
    return {
        "DataManagersConfig fields (data/loading/config_schema.py)": (
            set(DataManagersConfig.model_fields) - _PLANNER_FIELDS
        ),
        "SUPPORTED_DATA_MANAGER_TYPES (data/loading/config_schema.py)": set(
            SUPPORTED_DATA_MANAGER_TYPES
        ),
        "LoadedDataContext fields (core/state/data.py)": {
            field.name for field in dataclasses.fields(LoadedDataContext)
        }
        - _LOAD_STATE_FIELDS,
        "VARIABLES (data/workspace/scaffold.py)": {spec.name for spec in VARIABLES},
        "<V>Config names (hydromodpy/_lazy.py)": {
            _variable_of_config_name(name)
            for name, target in LAZY_IMPORTS.items()
            if target.startswith("hydromodpy.data.variables.")
            and name.endswith("Config")
            and not name.endswith("SourceConfig")
        },
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


def test_there_are_twenty_four_variables() -> None:
    assert len(VARIABLE_SPECS) == 24


# Sources computed from the section alone: they contact no host.
_LOCAL_SOURCES = {"constant", "synthetic"}


def _literal_values(annotation: object) -> set[str]:
    if typing.get_origin(annotation) is typing.Literal:
        return set(typing.get_args(annotation))
    values: set[str] = set()
    for member in typing.get_args(annotation):
        values |= _literal_values(member)
    model_fields = getattr(annotation, "model_fields", None)
    if model_fields and "source" in model_fields:
        values |= _literal_values(model_fields["source"].annotation)
    return values


def _source_values(variable: str) -> set[str] | None:
    """The values ``source =`` may take in ``[data.<variable>]``; None when any name goes."""
    section = DataManagersConfig.model_fields[variable].annotation
    config = next(
        member for member in (*typing.get_args(section), section) if hasattr(member, "model_fields")
    )
    values = _literal_values(config.model_fields["sources"].annotation)
    return values or None


def test_the_source_values_are_the_keys_of_sources() -> None:
    gaps = {}
    for variable in VARIABLE_SPECS:
        values = _source_values(variable)
        if values is None:
            continue
        keys = set(get_manager_class(variable).SOURCES)
        if values - {CUSTOM_SOURCE} != keys:
            gaps[variable] = {
                "in the config, not in SOURCES": sorted(values - {CUSTOM_SOURCE} - keys),
                "in SOURCES, not in the config": sorted(keys - values),
            }
    assert gaps == {}, (
        "The `source` values of a config (variables/<v>/config.py) and the SOURCES "
        f"of its manager (variables/<v>/manager.py) disagree: {gaps}"
    )


def test_every_source_has_a_licence_and_its_hosts() -> None:
    missing = sorted(
        (variable, key)
        for variable in VARIABLE_SPECS
        for key in get_manager_class(variable).SOURCES
        if source_entry(key) is None or (key not in _LOCAL_SOURCES and not source_entry(key).hosts)
    )
    assert missing == [], (
        f"These sources lack an entry with licence and hosts in hydromodpy/schema/sources.py: "
        f"{missing}"
    )


def test_a_port_source_declares_the_hosts_of_its_entry() -> None:
    from hydromodpy.data.source import registry

    disagree = {
        source_id: (registry.get(source_id).hosts, source_entry(source_id).hosts)
        for source_id in registry.builtin_source_ids()
        if registry.get(source_id).hosts != source_entry(source_id).hosts
    }
    assert disagree == {}
