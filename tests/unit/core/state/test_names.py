"""The rule of a project name and of a run name, in tables."""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.names import MAX_NAME_LENGTH, RESERVED_NAMES, check_name, fold_name

FORTY = "a" * MAX_NAME_LENGTH


@pytest.mark.parametrize(
    ("name", "what"),
    [
        pytest.param("baseline", "run", id="letters"),
        pytest.param("k_2e-5_run3", "run", id="digits, underscore and dash"),
        pytest.param(FORTY, "run", id="forty characters"),
        pytest.param(f"{FORTY}.v2", "run", id="the version is not counted"),
        pytest.param("baseline.v12", "run", id="a two-digit version"),
        pytest.param("nancon", "project", id="a project"),
        pytest.param("con_run", "run", id="a reserved word inside a name"),
    ],
)
def test_a_name_on_the_rule_is_kept_as_written(name: str, what: str) -> None:
    assert check_name(name, what=what) == name  # type: ignore[arg-type]


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


def test_a_reserved_fold_is_not_proposed() -> None:
    with pytest.raises(ConfigError) as refused:
        check_name("COM1", what="run")

    assert "Write" not in str(refused.value)


@pytest.mark.parametrize("reserved", sorted(RESERVED_NAMES))
def test_every_reserved_device_name_is_refused(reserved: str) -> None:
    with pytest.raises(ConfigError, match="reserves"):
        check_name(reserved, what="project")


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        pytest.param(
            "Example 12 launcher fast", "example_12_launcher_fast", id="spaces and capitals"
        ),
        pytest.param("  __Évry / île--  ", "evry_ile", id="ends trimmed, accents dropped"),
        pytest.param("a...b", "a_b", id="a run of other characters is one underscore"),
        pytest.param("!!!", "", id="nothing left"),
    ],
)
def test_a_text_made_by_the_code_folds_into_a_name(text: str, folded: str) -> None:
    assert fold_name(text) == folded


def test_a_fold_is_checked_like_a_written_name() -> None:
    long_fold = fold_name("Example 12 moderate annual flow-only comparison")

    with pytest.raises(ConfigError, match="characters"):
        check_name(long_fold, what="run")
