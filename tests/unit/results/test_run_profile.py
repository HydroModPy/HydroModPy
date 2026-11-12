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


def test_a_resume_adds_lines_under_its_attempt(tmp_path: Path) -> None:
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


def test_reuse_vocabulary() -> None:
    assert REUSED_KINDS == ("no", "prefix", "store", "sealed", "rerun")


REFUSED_LINES = [
    pytest.param({"kind": "trial"}, "kind is one of step, solve, figure, export", id="kind"),
    pytest.param({"reused": "cache"}, "reused as one of no, prefix, store", id="reuse"),
    pytest.param({"reused": "store"}, "store key exactly when", id="store without key"),
    pytest.param({"key": "recharge-3f2a"}, "store key exactly when", id="key without store"),
    pytest.param({"attempt": 0}, "attempt counts from 1", id="attempt zero"),
]


@pytest.mark.parametrize(("change", "message"), REFUSED_LINES)
def test_a_line_refuses_what_it_cannot_hold(change: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _line("build_mesh", **change)


def test_profile_is_outside_the_seal() -> None:
    assert RUN_PROFILE_FILENAME in UNSEALED_RUN_ENTRIES
