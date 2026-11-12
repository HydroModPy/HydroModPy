"""The two relative forms of a result directory are spelled and read in one place."""

from __future__ import annotations

import pytest

from hydromodpy.core.state.result_dirs import parse_rel_dir, run_dir_rel, trial_dir_rel


@pytest.mark.parametrize(
    "text",
    [
        "runs",
        "runs/",
        "runs/a/b",
        "/runs/a",
        "share/a",
        "sessions/a/trials",
        "sessions/a/trials/4",
        "sessions/a/trials/00004",
        "sessions/a/trials/-001",
        "sessions/a/phases/0001",
        "runs/..",
        "runs\\a",
    ],
)
def test_any_other_form_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="not a result directory"):
        parse_rel_dir(text)


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a\\b"])
def test_a_name_that_is_not_one_segment_is_refused(name: str) -> None:
    with pytest.raises(ValueError):
        run_dir_rel(name)


def test_a_negative_trial_is_refused() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        trial_dir_rel("s", -1)
