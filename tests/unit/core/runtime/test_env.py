"""The table of environment variables the code reads."""

from __future__ import annotations

import pytest

from hydromodpy.core.runtime.env import ENV_SCOPES, ENV_VARS, EnvVar, env_var


def test_every_variable_is_listed_once_with_a_known_scope() -> None:
    names = [row.name for row in ENV_VARS]

    assert len(names) == len(set(names))
    assert {row.scope for row in ENV_VARS} <= set(ENV_SCOPES)


def test_a_variable_is_found_by_its_name() -> None:
    row = env_var("HMP_SKIP_DOC_DATA")

    assert row.scope == "docs"
    assert row.display_name == "HMP_SKIP_DOC_DATA"


def test_an_unknown_variable_raises() -> None:
    with pytest.raises(KeyError):
        env_var("HMP_NO_SUCH_VARIABLE")


def test_a_row_is_frozen() -> None:
    assert isinstance(ENV_VARS[0], EnvVar)
    with pytest.raises(AttributeError):
        ENV_VARS[0].name = "x"  # type: ignore[misc]
