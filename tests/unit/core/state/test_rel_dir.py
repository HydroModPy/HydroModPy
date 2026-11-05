"""The two relative forms of a result directory are spelled and read in one place."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.state.result_dirs import (
    RelDir,
    is_sealed_run_config,
    parse_rel_dir,
    run_dir_rel,
    session_dir_rel,
    trial_dir_rel,
)


def test_a_run_directory_round_trips() -> None:
    rel = run_dir_rel("nancon_monthly.v2")
    assert rel == "runs/nancon_monthly.v2"
    assert parse_rel_dir(rel) == RelDir("run", "nancon_monthly.v2")
    assert parse_rel_dir(rel).as_posix() == rel


def test_a_session_directory_round_trips() -> None:
    rel = session_dir_rel("calibration")
    assert rel == "sessions/calibration"
    assert parse_rel_dir(rel) == RelDir("session", "calibration")


def test_a_trial_directory_is_zero_padded_and_round_trips() -> None:
    rel = trial_dir_rel("J0014010-calage", 4)
    assert rel == "sessions/J0014010-calage/trials/0004"
    parsed = parse_rel_dir(rel)
    assert parsed == RelDir("trial", "J0014010-calage", 4)
    assert parsed.as_posix() == rel
    assert trial_dir_rel("big", 12345) == "sessions/big/trials/12345"


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


def test_a_sealed_config_is_the_config_of_a_run_or_a_kept_trial(tmp_path: Path) -> None:
    assert is_sealed_run_config(tmp_path / "runs" / "nancon" / "config.toml")
    assert is_sealed_run_config(tmp_path / "sessions" / "cal" / "trials" / "0004" / "config.toml")
    assert not is_sealed_run_config(tmp_path / "project.toml")
    assert not is_sealed_run_config(tmp_path / "sessions" / "cal" / "config.toml")
    assert not is_sealed_run_config(tmp_path / "configs" / "a" / "run.toml")
