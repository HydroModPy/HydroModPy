"""``profile.json`` goes to disk and back, keeps every attempt, and refuses what it cannot read."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.runtime.stopwatch import measured
from hydromodpy.results.storage.contract import RUN_PROFILE_FILENAME, UNSEALED_RUN_ENTRIES
from hydromodpy.results.storage.run_profile import (
    PROFILE_SCHEMA,
    REUSED_KINDS,
    Profile,
    ProfileLine,
    collect_line,
    collected_profile,
    profile_path,
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


def test_a_profile_comes_back_as_it_was_written(tmp_path: Path) -> None:
    profile = (
        Profile()
        .with_start(1, 6.4)
        .with_line(_line("build_mesh"))
        .with_line(_line("flow_main::modflow6", kind="solve", duration_s=42.0))
        .with_line(_line("load_data", reused="store", key="recharge-3f2a"))
        .with_line(_line("heads_map", kind="figure", max_rss_mb=None))
    )

    path = write_profile(tmp_path, profile)

    assert path == profile_path(tmp_path) == tmp_path / RUN_PROFILE_FILENAME
    assert read_profile(tmp_path) == profile
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == PROFILE_SCHEMA


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


def test_a_line_is_made_from_a_measure() -> None:
    with measured("export", "heads.nc") as measure:
        pass

    line = ProfileLine.of(measure, attempt=3)

    assert (line.kind, line.name, line.attempt, line.reused, line.key) == (
        "export",
        "heads.nc",
        3,
        "no",
        None,
    )
    assert line.duration_s == measure.duration_s
    assert line.started_at == measure.started_at


def test_the_reuse_vocabulary_is_no_prefix_store_sealed_rerun() -> None:
    assert REUSED_KINDS == ("no", "prefix", "store", "sealed", "rerun")


def test_a_rerun_solve_line_round_trips(tmp_path: Path) -> None:
    line = _line("flow", kind="solve", reused="rerun")
    assert ProfileLine.from_dict(line.to_dict()) == line


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


def test_a_run_without_a_profile_reads_none(tmp_path: Path) -> None:
    assert read_profile(tmp_path) is None


def test_an_unknown_schema_is_refused(tmp_path: Path) -> None:
    profile_path(tmp_path).write_text(
        json.dumps({"schema": "hydromodpy.profile.v9", "lines": []}), encoding="utf-8"
    )

    with pytest.raises(SchemaVersionMismatchError, match="hydromodpy.profile.v9"):
        read_profile(tmp_path)


def test_the_profile_is_outside_the_seal() -> None:
    assert RUN_PROFILE_FILENAME in UNSEALED_RUN_ENTRIES


def test_a_rewrite_leaves_no_temporary_file(tmp_path: Path) -> None:
    for count in range(3):
        write_profile(tmp_path, Profile(lines=tuple(_line(f"s{i}") for i in range(count))))

    assert sorted(path.name for path in tmp_path.iterdir()) == [RUN_PROFILE_FILENAME]


def test_a_line_goes_to_the_collector_open_in_its_context() -> None:
    assert collect_line(_line("outside")) is False
    with collected_profile() as outer:
        assert collect_line(_line("a")) is True
        with collected_profile() as inner:
            collect_line(_line("b"))
        collect_line(_line("c"))
    assert [line.name for line in outer] == ["a", "c"]
    assert [line.name for line in inner] == ["b"]
    assert collect_line(_line("after")) is False
