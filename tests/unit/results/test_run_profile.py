"""``profile.json`` goes to disk and back, keeps every attempt, and refuses what it cannot read."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.results.storage.contract import RUN_PROFILE_FILENAME, UNSEALED_RUN_ENTRIES
from hydromodpy.results.storage.run_profile import (
    REUSED_KINDS,
    Profile,
    ProfileLine,
    read_profile,
    write_profile,
)

AT = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)


def _line(name: str, attempt: int = 1, **extra: object) -> ProfileLine:
    return ProfileLine(
        kind=str(extra.pop("kind", "step")),
        name=name,
        attempt=attempt,
        started_at=AT,
        duration_s=float(extra.pop("duration_s", 1.5)),
        max_rss_mb=extra.pop("max_rss_mb", 812.5),
        **extra,
    )


def test_a_resume_adds_its_lines_under_its_attempt(tmp_path: Path) -> None:
    first = Profile().with_start(1, 6.4).with_line(_line("build_mesh"))
    write_profile(tmp_path, first)

    second = (
        read_profile(tmp_path)
        .with_start(2, 7.1)
        .with_line(_line("build_mesh", attempt=2, reused="prefix"))
        .with_line(_line("run_solver", attempt=2))
    )
    write_profile(tmp_path, second)
    back = read_profile(tmp_path)

    assert [line.name for line in back.of_attempt(1)] == ["build_mesh"]
    assert [(line.name, line.reused) for line in back.of_attempt(2)] == [
        ("build_mesh", "prefix"),
        ("run_solver", "no"),
    ]
    assert dict(back.process_age_s) == {1: 6.4, 2: 7.1}


def test_the_reuse_vocabulary_is_no_prefix_store_sealed_rerun() -> None:
    assert REUSED_KINDS == ("no", "prefix", "store", "sealed", "rerun")


REFUSED_LINES = (
    ("kind", {"kind": "trial"}, "kind is one of step, solve, figure, export"),
    ("reuse", {"reused": "cache"}, "reused as one of no, prefix, store"),
    ("store without key", {"reused": "store"}, "store key exactly when"),
    ("key without store", {"key": "recharge-3f2a"}, "store key exactly when"),
    ("attempt zero", {"attempt": 0}, "attempt counts from 1"),
)


@pytest.mark.parametrize(
    ("case", "change", "message"), REFUSED_LINES, ids=[case for case, _, _ in REFUSED_LINES]
)
def test_a_line_refuses_what_it_cannot_hold(case: str, change: dict, message: str) -> None:
    del case
    attempt = int(change.pop("attempt", 1))
    with pytest.raises(ValueError, match=message):
        _line("build_mesh", attempt=attempt, **change)


def test_the_profile_is_outside_the_seal() -> None:
    assert RUN_PROFILE_FILENAME in UNSEALED_RUN_ENTRIES
