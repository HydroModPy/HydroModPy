"""The rule of a project name and of a run name, in tables."""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.names import MAX_NAME_LENGTH, check_name

FORTY = "a" * MAX_NAME_LENGTH


@pytest.mark.parametrize(
    ("name", "what", "said"),
    [
        pytest.param("", "run", "cannot be empty", id="empty"),
        pytest.param("Baseline", "run", "Write 'baseline'", id="a capital, folded"),
        pytest.param("Bsq island", "run", "Write 'bsq_island'", id="a space, folded"),
        pytest.param("été", "project", "Write 'ete'", id="an accent, folded"),
        pytest.param("nul.txt", "run", "Write 'nul_txt'", id="a dot that is no version"),
        pytest.param(FORTY + "a", "run", "has 41 characters", id="forty-one characters"),
        pytest.param(f"{FORTY}a.v2", "run", "has 41 characters", id="a version of a long stem"),
        pytest.param("con", "run", "reserves", id="con"),
        pytest.param("COM1", "run", "is refused", id="COM1, whose fold is reserved"),
        pytest.param("lpt9.v2", "run", "reserves", id="a version of a reserved stem"),
        pytest.param("base.v2", "project", "is refused", id="a project has no version"),
        pytest.param("a/b", "project", "Write 'a_b'", id="a separator"),
        pytest.param("a__b", "run", "doubled underscore.*Write 'a_b'", id="a doubled underscore"),
        pytest.param(
            "my__project", "project", "Write 'my_project'", id="a project, doubled underscore"
        ),
    ],
)
def test_a_name_off_the_rule_is_refused_with_what_to_write(name: str, what: str, said: str) -> None:
    with pytest.raises(ConfigError, match=said) as refused:
        check_name(name, what=what)  # type: ignore[arg-type]

    assert f"{what} name" in str(refused.value)
