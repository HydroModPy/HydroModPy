"""The ``[data]`` section: the types a run lists, and the sections those types need."""

from __future__ import annotations

import pytest

from hydromodpy.core.config_kit.introspect import iter_basemodels
from hydromodpy.core.tracking.input_file import input_file_role
from hydromodpy.data.loading._dispatch import VARIABLE_SPECS, get_config_class
from hydromodpy.data.loading.config_schema import DataConfig


def _file_roles(variable: str) -> set[str]:
    """The roles of the ``path`` of every source a variable accepts."""
    sources = get_config_class(variable).model_fields["sources"]
    roles = (
        input_file_role(m.model_fields.get("path")) for m in iter_basemodels(sources.annotation)
    )
    return {role for role in roles if role is not None}


@pytest.mark.parametrize("variable", sorted(VARIABLE_SPECS))
def test_the_file_of_a_variable_has_the_role_of_its_folder(variable: str) -> None:
    """``workspace:<name>`` reads ``data/<role>/``, where the caches of the variable live."""
    assert _file_roles(variable) <= {variable}


@pytest.mark.fast
def test_a_listed_type_without_its_section_is_refused(tmp_path):
    with pytest.raises(ValueError, match=r"lists 'hydrometry'.*no \[data.hydrometry\]"):
        DataConfig.from_toml_section({"types": ["hydrometry"]}, base_dir=tmp_path)


@pytest.mark.fast
def test_geology_listed_alone_takes_its_default_section(tmp_path):
    config = DataConfig.from_toml_section({"types": ["geology"]}, base_dir=tmp_path)

    assert config.geology is not None


def test_resolved_types_inject_the_default_geology_section() -> None:
    resolved = DataConfig(types=[]).with_resolved_types(["geology"])

    assert resolved.types == ["geology"]
    assert resolved.geology is not None
