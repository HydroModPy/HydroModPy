"""The public surfaces cannot change without someone saying so.

``tools/surface_snapshot.py`` writes each surface to a file under ``surface/``, and this
gate compares the build with those files. A difference fails and says what changed.
Regenerating accepts it, and regenerating refuses a stable TOML key that left with no
rewrite in ``config_migration.py``. A key that left stays in ``removed_toml_keys.tsv``,
so its migration is still held after the old snapshot is gone, until its delay ends.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config import config_migration as migration
from hydromodpy.core.version import __version__
from tools import surface_snapshot as surface

pytestmark = pytest.mark.fast

ROW_ONE = "a.b\tint\t1\tstable"


@pytest.mark.parametrize("name", sorted(surface.SURFACES))
def test_a_surface_equals_its_snapshot(name: str) -> None:
    difference = surface.compare(
        surface.read_rows(surface.SNAPSHOT_DIR / name), surface.rows_of(name)
    )
    assert not difference, (
        f"tests/unit/architecture/surface/{name} no longer matches this build:\n"
        f"{difference.describe()}\n"
        f"If this is on purpose, run `{surface.REGENERATE}` and commit the files. A removed "
        "public name goes in the changelog with its replacement, and a removed TOML key needs "
        "its row in hydromodpy/config/config_migration.py first."
    )


def test_a_removed_toml_key_keeps_its_migration_until_its_delay_ends() -> None:
    ledger = surface.read_rows(surface.SNAPSHOT_DIR / surface.REMOVED_TOML_KEYS)
    missing = [
        row.split("\t")[0]
        for row in ledger
        if surface.migration_for(row.split("\t")[0]) is None
        and not migration.OldForm("", None, row.split("\t")[1]).outlived_by(__version__)
    ]
    assert missing == [], f"{missing} left the grammar and config_migration.py has no row for them."


def test_a_change_is_named_by_kind() -> None:
    difference = surface.compare(
        [ROW_ONE, "gone\tint\t1\tstable"], ["a.b\tint\t2\tstable", "new\tint\t1\tstable"]
    )
    assert difference.removed == ("gone",)
    assert difference.added == ("new",)
    assert difference.changed == (("a.b", (ROW_ONE,), ("a.b\tint\t2\tstable",)),)
    assert "removed: gone" in difference.describe()
    assert not surface.compare([ROW_ONE], [ROW_ONE])


def test_an_experimental_key_can_leave_and_a_stable_one_is_counted() -> None:
    before = ["a\tint\t1\tstable", f"b\tint\t1\t{surface.EXPERIMENTAL}", ROW_ONE]
    assert surface.stable_removals(before, [ROW_ONE]) == ["a"]


def _snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, keys: list[str]) -> Path:
    """Stand in for the real surfaces with one fake TOML surface and the snapshot of it."""
    monkeypatch.setattr(surface, "SURFACES", {surface.TOML_SURFACE: lambda: list(keys)})
    (tmp_path / surface.TOML_SURFACE).write_text(
        "calibration.max_iter\tint\t1\tstable\nnever.migrated\tint\t1\tstable\nkept\tint\t1\tstable\n",
        encoding="utf-8",
    )
    return tmp_path


def test_regenerating_refuses_a_stable_key_without_a_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _snapshots(
        tmp_path, monkeypatch, keys=["calibration.max_iter\tint\t1\tstable", "kept\tint\t1\tstable"]
    )
    before = (directory / surface.TOML_SURFACE).read_text(encoding="utf-8")

    refused = surface.regenerate(directory)

    assert len(refused) == 1
    assert "never.migrated" in refused[0] and "config_migration.py" in refused[0]
    assert (directory / surface.TOML_SURFACE).read_text(encoding="utf-8") == before


def test_regenerating_records_a_key_that_has_its_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _snapshots(
        tmp_path, monkeypatch, keys=["never.migrated\tint\t1\tstable", "kept\tint\t1\tstable"]
    )

    assert surface.regenerate(directory) == []

    ledger = surface.read_rows(directory / surface.REMOVED_TOML_KEYS)
    assert ledger == [f"calibration.max_iter\t{surface.installed_release()}"]
    assert surface.read_rows(directory / surface.TOML_SURFACE) == [
        "kept\tint\t1\tstable",
        "never.migrated\tint\t1\tstable",
    ]


@pytest.mark.parametrize(
    ("path", "covered"),
    [
        ("calibration.max_iter", True),
        ("calibration.phases.max_iter", True),
        ("calibration.parameters.transform", True),
        ("modflow6.sgrid.vertical.nlay", True),
        ("modflow6.sgrid", False),
        ("calibration.max_trials", False),
    ],
)
def test_a_path_finds_the_old_form_that_covers_it(path: str, covered: bool) -> None:
    assert (surface.migration_for(path) is not None) is covered
