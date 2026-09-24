"""Every list of ``[data]`` variables names the same 24 variables.

Adding a variable touches several lists (``hydromodpy/data/structure.md``,
section 7). This test compares them to ``VARIABLE_SPECS`` and names the list
that is incomplete, so a forgotten entry fails here rather than at run time.
"""

from __future__ import annotations

import dataclasses
import re

from hydromodpy._lazy import LAZY_IMPORTS
from hydromodpy.core.state.data import LoadedDataContext
from hydromodpy.data import DataManagersConfig
from hydromodpy.data.loading._dispatch import VARIABLE_SPECS
from hydromodpy.data.loading.config_schema import SUPPORTED_DATA_MANAGER_TYPES
from hydromodpy.data.scaffold import VARIABLES

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
        "VARIABLES (data/scaffold.py)": {spec.name for spec in VARIABLES},
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
