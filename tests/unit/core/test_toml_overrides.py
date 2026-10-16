"""--set items and HMP_SET_* variables are one grammar, parsed in one place."""

from __future__ import annotations

from datetime import date

import pytest

from hydromodpy.core.toml_io.overrides import (
    env_overrides,
    env_set_names,
    parse_override_value,
    set_overrides,
)


def test_set_items_become_a_payload_of_toml_values() -> None:
    payload = set_overrides(["flow.param.K.field.value=2e-5", "simulation.name=x", 'a."b.c"=true'])
    assert payload == {
        "flow": {"param": {"K": {"field": {"value": 2e-5}}}},
        "simulation": {"name": "x"},
        "a": {"b.c": True},
    }


def test_a_value_that_is_not_toml_stays_text() -> None:
    assert parse_override_value("not toml [") == "not toml ["
    assert parse_override_value("300 m") == "300 m"


def test_a_value_that_is_toml_is_read_as_toml() -> None:
    assert parse_override_value("2000-01-01") == date(2000, 1, 1)
    assert parse_override_value(" 7 ") == 7
    assert parse_override_value("true") is True
    assert parse_override_value('"quoted"') == "quoted"


def test_an_item_without_a_value_is_refused() -> None:
    with pytest.raises(ValueError, match="PATH=VALUE"):
        set_overrides(["flow.param"])


def test_env_names_keep_their_case_and_double_underscores_are_dots() -> None:
    env = {
        "HMP_SET_flow__param__K__field__value": "3e-5",
        "HOME": "/x",
        "HMP_SET_simulation__name": '"y"',
    }
    assert env_set_names(env) == [
        "HMP_SET_flow__param__K__field__value",
        "HMP_SET_simulation__name",
    ]
    assert env_overrides(env) == {
        "flow": {"param": {"K": {"field": {"value": 3e-5}}}},
        "simulation": {"name": "y"},
    }
    assert env_overrides({"HOME": "/x"}) == {}


def test_an_env_override_and_a_set_item_name_the_same_key() -> None:
    env = {"HMP_SET_flow__param__K__field__value": "3e-5"}
    assert env_overrides(env) == set_overrides(["flow.param.K.field.value=3e-5"])
