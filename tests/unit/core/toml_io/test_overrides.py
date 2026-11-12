"""--set items and HMP_SET_* variables are one grammar, parsed in one place."""

from __future__ import annotations

import pytest

from hydromodpy.core.toml_io.overrides import env_overrides, set_overrides


def test_an_env_override_and_a_set_item_name_the_same_key():
    env = {"HMP_SET_flow__param__K__field__value": "3e-5"}
    assert env_overrides(env) == set_overrides(["flow.param.K.field.value=3e-5"])


def test_an_item_without_a_value_is_refused():
    with pytest.raises(ValueError, match="PATH=VALUE"):
        set_overrides(["flow.param"])
