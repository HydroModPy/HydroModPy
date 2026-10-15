"""A deleted run name is never given to a new run, whether its bytes are freed or not."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hydromodpy.core.state.paths import RUNS_DIRNAME
from hydromodpy.results.catalog.registration import reserve_version_dirname
from hydromodpy.results.trash import gc_trash, list_trash, read_tombstones, trash_run

AT = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)


def _live_runs(project) -> list[str]:
    return sorted(entry.name for entry in (project / RUNS_DIRNAME).iterdir())


def test_a_trashed_then_collected_version_is_not_reassigned(tmp_path):
    reserve_version_dirname(tmp_path, "run", "nancon")
    second = reserve_version_dirname(tmp_path, "run", "nancon")
    assert second.name == "nancon.v2"

    trash_run(tmp_path, "runs/nancon.v2", now=AT)
    freed = gc_trash(tmp_path, older_than=timedelta(0), now=AT + timedelta(days=31))

    assert [tombstone.rel_dir for tombstone in freed] == ["runs/nancon.v2"]
    assert list_trash(tmp_path) == []
    assert _live_runs(tmp_path) == ["nancon"]
    assert [t.rel_dir for t in read_tombstones(tmp_path)] == ["runs/nancon.v2"]

    third = reserve_version_dirname(tmp_path, "run", "nancon")

    assert third.name == "nancon.v3"


def test_a_trashed_version_is_not_reassigned_before_the_gc(tmp_path):
    reserve_version_dirname(tmp_path, "run", "nancon")
    reserve_version_dirname(tmp_path, "run", "nancon")

    trash_run(tmp_path, "runs/nancon.v2", now=AT)
    assert _live_runs(tmp_path) == ["nancon"]

    third = reserve_version_dirname(tmp_path, "run", "nancon")

    assert third.name == "nancon.v3"


def test_the_bare_name_once_collected_is_not_reassigned(tmp_path):
    reserve_version_dirname(tmp_path, "run", "nancon")
    trash_run(tmp_path, "runs/nancon", now=AT)
    gc_trash(tmp_path, older_than=timedelta(0), now=AT)

    assert reserve_version_dirname(tmp_path, "run", "nancon").name == "nancon.v2"
