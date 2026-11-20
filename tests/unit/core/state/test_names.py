"""The rule of a project name and of a run name, in tables."""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.names import (
    MAX_NAME_LENGTH,
    check_name,
    fold_name,
    split_stem_version,
    versioned_name,
)

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
        pytest.param(f"{FORTY}a_v2", "run", "has 41 characters", id="a version of a long stem"),
        pytest.param("con", "run", "reserves", id="con"),
        pytest.param("COM1", "run", "is refused", id="COM1, whose fold is reserved"),
        pytest.param("lpt9_v2", "run", "reserves", id="a version of a reserved stem"),
        pytest.param("base.v2", "project", "Write 'base-v2'", id="a project has no version"),
        pytest.param("base.v2", "run", "Write 'base-v2'", id="the dot of a pre-release version"),
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


@pytest.mark.parametrize(
    ("name", "split"),
    [
        pytest.param("steady_api_v4", ("steady_api", 4), id="a version"),
        pytest.param("steady_api", ("steady_api", None), id="the bare name"),
        pytest.param("nancon-v2", ("nancon-v2", None), id="a dash is no version"),
        pytest.param("steady_api.v4", ("steady_api.v4", None), id="the dot of a pre-release"),
        pytest.param("a_v0", ("a_v0", None), id="no version zero"),
    ],
)
def test_a_version_is_read_after_v(name: str, split: tuple[str, int | None]) -> None:
    assert split_stem_version(name) == split


def test_a_version_has_no_dot_so_an_exported_file_has_one_suffix() -> None:
    assert [versioned_name("nancon", n) for n in (1, 2, 12)] == [
        "nancon",
        "nancon_v2",
        "nancon_v12",
    ]


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        pytest.param("calib_v2", "calib-v2", id="a file named like a version"),
        pytest.param("Calib V3", "calib-v3", id="spaces and capitals"),
        pytest.param("calib_v2_k", "calib_v2_k", id="v2 inside the name"),
    ],
)
def test_a_folded_name_never_ends_like_a_version(text: str, folded: str) -> None:
    assert fold_name(text) == folded
    assert split_stem_version(fold_name(text))[1] is None
