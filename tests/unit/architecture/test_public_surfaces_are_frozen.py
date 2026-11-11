"""The public surfaces cannot change without someone saying so.

``tools/surface_snapshot.py`` writes each surface to a file under ``surface/``, and this
gate compares the build with those files. A difference fails and says what changed.
Regenerating accepts it, and regenerating refuses a stable TOML key that left with no
``[[migration]]`` row of ``hydromodpy/schema/changes.toml`` that rewrites it. A key that
left stays in ``removed_toml_keys.tsv``, so its migration is still held after the old
snapshot is gone, until its delay ends. The delay is written once, in
``schema.changes.outlived``. A key that only a pre-release of 2.0 wrote is held by its line
of ``prerelease_forms.txt`` until that list leaves. From the first stable version on, the
same holds for a name of ``hydromodpy.__all__`` and for a command or a flag of ``hmp``,
with their entries in ``OLD_NAMES`` and ``OLD_CLI_FORMS`` and their ledger
``removed_names.tsv``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from hydromodpy import _lazy
from hydromodpy._lazy import OLD_NAMES, OldName
from hydromodpy.cli import conventions
from hydromodpy.core.version import __version__
from hydromodpy.schema import changes
from hydromodpy.schema.changes import outlived
from tools import surface_snapshot as surface

pytestmark = pytest.mark.fast

ROW_ONE = "a.b\tint\t1\tstable"


def test_the_frozen_step_names_are_the_steps_of_the_pipeline() -> None:
    from hydromodpy.core.pipeline_steps import STEP_NAMES
    from hydromodpy.workflow.steps.sequence import standard_steps

    assert tuple(step.name for step in standard_steps()) == STEP_NAMES


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
        "its [[migration]] row in hydromodpy/schema/changes.toml first. From the first stable "
        "version on, a removed Python name or hmp flag needs its entry in hydromodpy/_lazy.py "
        "or hydromodpy/cli/conventions.py first."
    )


def _without_their_entry(rows: list[str], entry_of: Callable[[str], Any]) -> list[str]:
    """Return the names of a ledger whose delay runs and that nothing keeps working."""
    return [
        row.split("\t")[0]
        for row in rows
        if entry_of(row.split("\t")[0]) is None and not outlived(row.split("\t")[1], __version__)
    ]


def test_a_removed_toml_key_keeps_its_migration_until_its_delay_ends() -> None:
    """A row of the register or a line of ``prerelease_forms.txt`` keeps each key answered."""
    ledger = surface.read_rows(surface.SNAPSHOT_DIR / surface.REMOVED_TOML_KEYS)
    missing = _without_their_entry(ledger, surface.toml_entry_for)
    assert missing == [], (
        f"{missing} left the grammar and hydromodpy/schema/changes.toml has no row for them."
    )


def test_a_removed_name_keeps_its_entry_until_its_delay_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = surface.read_rows(surface.SNAPSHOT_DIR / surface.REMOVED_NAMES)
    missing = _without_their_entry(ledger, surface.entry_for)
    assert missing == [], f"{missing} left the surface and no table keeps them working."

    assert _without_their_entry(["gone\t2.0.0"], surface.entry_for) == ["gone"]
    monkeypatch.setitem(OLD_NAMES, "gone", OldName("run", "2.0.0"))
    assert _without_their_entry(["gone\t2.0.0"], surface.entry_for) == []


def test_an_entry_that_outlives_its_delay_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_lazy, "OLD_NAMES", {"gone": OldName("run", "2.0.0")})
    form = conventions.OldCliForm("hmp old", "hmp new", "2.0.0")
    monkeypatch.setattr(conventions, "OLD_CLI_FORMS", (form,))

    assert surface.outlived_interface_forms("2.1.9") == ()
    late = surface.outlived_interface_forms("2.2.0a1")
    assert [entry.old for entry in late] == ["gone", "hmp old"]


def test_the_delay_of_the_interface_tables_is_the_one_of_the_register(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``schema.changes`` writes the delay once, and the surface gate reads no other."""
    monkeypatch.setattr(_lazy, "OLD_NAMES", {"gone": OldName("run", "2.0.0")})
    monkeypatch.setattr(
        conventions, "OLD_CLI_FORMS", (conventions.OldCliForm("hmp old", "hmp new", "2.1.0"),)
    )

    assert [entry.old for entry in surface.outlived_interface_forms("2.2.0")] == ["gone"]
    assert [entry.old for entry in surface.outlived_interface_forms("2.3.0")] == ["gone", "hmp old"]

    monkeypatch.setattr(changes, "DELAY_MINORS", changes.DELAY_MINORS + 1)

    assert surface.outlived_interface_forms("2.2.0") == ()
    assert [entry.old for entry in surface.outlived_interface_forms("2.3.0")] == ["gone"]


def test_an_old_form_of_hmp_is_not_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    before = surface.rows_of(surface.CLI_SURFACE)
    forms = (
        conventions.OldCliForm("hmp ls --old", "hmp ls --format", "2.3.0"),
        conventions.OldCliForm("hmp status", "hmp ls", "2.3.0"),
    )
    monkeypatch.setattr(conventions, "OLD_CLI_FORMS", forms)

    assert surface.rows_of(surface.CLI_SURFACE) == before


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
    assert surface.stable_removals(before, [ROW_ONE], demoted=["b"]) == ["a", "b"]


def _snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, keys: list[str]) -> Path:
    """Stand in for the real surfaces with one fake TOML surface and the snapshot of it."""
    monkeypatch.setattr(surface, "SURFACES", {surface.TOML_SURFACE: lambda: list(keys)})
    (tmp_path / surface.TOML_SURFACE).write_text(
        "modflow6.hclose\tfloat\t1.0\tstable\nnever.migrated\tint\t1\tstable\nkept\tint\t1\tstable\n",
        encoding="utf-8",
    )
    return tmp_path


def test_regenerating_refuses_a_stable_key_without_a_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _snapshots(
        tmp_path, monkeypatch, keys=["modflow6.hclose\tfloat\t1.0\tstable", "kept\tint\t1\tstable"]
    )
    before = (directory / surface.TOML_SURFACE).read_text(encoding="utf-8")

    refused = surface.regenerate(directory)

    assert len(refused) == 1
    assert "never.migrated" in refused[0] and "hydromodpy/schema/changes.toml" in refused[0]
    assert (directory / surface.TOML_SURFACE).read_text(encoding="utf-8") == before


def test_regenerating_records_a_key_that_has_its_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _snapshots(
        tmp_path, monkeypatch, keys=["never.migrated\tint\t1\tstable", "kept\tint\t1\tstable"]
    )

    assert surface.regenerate(directory) == []

    ledger = surface.read_rows(directory / surface.REMOVED_TOML_KEYS)
    assert ledger == [f"modflow6.hclose\t{surface.installed_release()}"]
    assert surface.read_rows(directory / surface.TOML_SURFACE) == [
        "kept\tint\t1\tstable",
        "never.migrated\tint\t1\tstable",
    ]


def _fake_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, before: dict[str, Any], after: dict[str, Any]
) -> Path:
    """Stand in for the real surfaces: write the snapshots *before*, build gives *after*."""
    monkeypatch.setattr(
        surface,
        "SURFACES",
        {name: (lambda rows=rows: list(rows)) for name, rows in after.items()},
    )
    for name, rows in before.items():
        (tmp_path / name).write_text("".join(f"{row}\n" for row in rows), encoding="utf-8")
    return tmp_path


def _at_the_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(surface, "before_the_tag", lambda: False)


NAMES_THAT_LEAVE = (
    (surface.FACADE_SURFACE, ["gone\tfunction\t()", "kept\tfunction\t()"], "gone"),
    (surface.CLI_SURFACE, ["hmp a\tcommand", "hmp a --gone,-g\t"], "hmp a --gone"),
    (surface.CLI_SURFACE, ["hmp a\tcommand", "hmp a --gone,-g\t"], "hmp a -g"),
    (surface.CLI_SURFACE, ["hmp a\tcommand", "hmp gone\tcommand", "hmp gone --x\t"], "hmp gone"),
)
"""A surface, its rows before, and one name that leaves when only the first command stays."""


def _kept(rows: list[str]) -> list[str]:
    return [row for row in rows if "gone" not in row]


def _entries_for(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    if name.startswith("hmp "):
        forms = tuple(
            conventions.OldCliForm(old, "hmp a", "2.3.0")
            for old in ("hmp a --gone", "hmp a -g", "hmp gone")
        )
        monkeypatch.setattr(conventions, "OLD_CLI_FORMS", forms)
    else:
        monkeypatch.setitem(OLD_NAMES, name, OldName("kept", "2.3.0"))


@pytest.mark.parametrize(("name", "rows", "gone"), NAMES_THAT_LEAVE)
def test_before_the_tag_a_name_leaves_with_no_entry(
    name: str, rows: list[str], gone: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(surface, "before_the_tag", lambda: True)
    directory = _fake_surfaces(
        tmp_path,
        monkeypatch,
        {name: rows},
        {name: _kept(rows), surface.TOML_SURFACE: []},
    )

    assert surface.regenerate(directory) == []
    assert surface.read_rows(directory / surface.REMOVED_NAMES) == []


@pytest.mark.parametrize(("name", "rows", "gone"), NAMES_THAT_LEAVE)
def test_from_the_tag_a_name_needs_its_entry_to_leave(
    name: str, rows: list[str], gone: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _at_the_tag(monkeypatch)
    directory = _fake_surfaces(
        tmp_path,
        monkeypatch,
        {name: rows},
        {name: _kept(rows), surface.TOML_SURFACE: []},
    )

    refused = surface.regenerate(directory)
    assert any(line.startswith(f"{gone}: ") for line in refused)
    assert surface.read_rows(directory / name) == rows

    _entries_for(gone, monkeypatch)
    assert surface.regenerate(directory) == []
    ledger = surface.read_rows(directory / surface.REMOVED_NAMES)
    assert f"{gone}\t{surface.installed_release()}" in ledger
    assert surface.read_rows(directory / name) == _kept(rows)


def test_a_positional_may_leave_with_no_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _at_the_tag(monkeypatch)
    rows = ["hmp a\tcommand", "hmp a <gone>\t"]
    directory = _fake_surfaces(
        tmp_path,
        monkeypatch,
        {surface.CLI_SURFACE: rows},
        {surface.CLI_SURFACE: rows[:1], surface.TOML_SURFACE: []},
    )

    assert surface.regenerate(directory) == []


def test_a_stable_key_marked_experimental_still_needs_its_migration_to_leave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(surface, "before_the_tag", lambda: True)
    stable, marked = (
        "never.migrated\tint\t1\tstable",
        f"never.migrated\tint\t1\t{surface.EXPERIMENTAL}",
    )
    directory = _fake_surfaces(
        tmp_path, monkeypatch, {surface.TOML_SURFACE: [stable]}, {surface.TOML_SURFACE: [marked]}
    )
    assert surface.regenerate(directory) == []
    assert surface.read_rows(directory / surface.DEMOTED_TOML_KEYS) == ["never.migrated"]

    _fake_surfaces(tmp_path, monkeypatch, {}, {surface.TOML_SURFACE: []})
    refused = surface.regenerate(directory)

    assert len(refused) == 1 and refused[0].startswith("never.migrated: ")


def test_from_the_tag_a_stable_key_cannot_be_marked_experimental(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _at_the_tag(monkeypatch)
    stable, marked = "a.b\tint\t1\tstable", f"a.b\tint\t1\t{surface.EXPERIMENTAL}"
    directory = _fake_surfaces(
        tmp_path, monkeypatch, {surface.TOML_SURFACE: [stable]}, {surface.TOML_SURFACE: [marked]}
    )

    refused = surface.regenerate(directory)

    assert len(refused) == 1 and "marked experimental" in refused[0]
    assert surface.read_rows(directory / surface.TOML_SURFACE) == [stable]


def test_a_form_the_loader_only_refuses_is_no_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A line of ``prerelease_forms.txt`` holds a key of the ledger, never a key that leaves now."""
    directory = _fake_surfaces(
        tmp_path,
        monkeypatch,
        {surface.TOML_SURFACE: ["data.project_crs\tstr\t'a'\tstable"]},
        {surface.TOML_SURFACE: []},
    )

    refused = surface.regenerate(directory)

    assert len(refused) == 1 and refused[0].startswith("data.project_crs: ")


_RETIRE_ROWS = (
    'schema = "hydromodpy.changes.v1"\n'
    '[[migration]]\ndocument = "config"\nold = "table.left"\n'
    'instead = "Write table.right."\nsince = "2.1.0"\n'
    '[[migration]]\ndocument = "config"\nold = "table.moved_by_a_rule"\n'
    'instead = "Write table.right."\nsince = "2.1.0"\nrule = "a_rule"\n'
    '[[migration]]\ndocument = "sidecar"\nold = "sidecar_key"\nnew = "sidecar_new"\n'
    'since = "2.1.0"\n'
)


@pytest.mark.parametrize(
    ("path", "covered"),
    [
        pytest.param("table.left", False, id="a key that left with nothing to write"),
        pytest.param("table.moved_by_a_rule", True, id="a key a rule writes elsewhere"),
        pytest.param("table.moved_by_a_rule.sub", True, id="a key under it"),
        pytest.param("sidecar_key", False, id="a row of another document"),
    ],
)
def test_only_a_row_that_rewrites_counts_as_a_migration(
    path: str, covered: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = changes.read(_RETIRE_ROWS)
    monkeypatch.setattr(
        surface, "migrations_of", lambda document: changes.migrations_of(document, fixture)
    )

    assert (surface.migration_for(path) is not None) is covered


@pytest.mark.parametrize(
    ("path", "row", "line"),
    [
        # A pre-release key is a line of the list, never a row of the register.
        ("data.project_crs", False, True),
        ("calibration.max_iter", False, True),
        ("calibration.phases.max_iter", False, True),
        ("calibration.parameters.transform", False, True),
        ("flow.active_bc", False, True),
        ("workspace.catalog_path", False, True),
        # A line holds what lies below it, as a row does.
        ("calibration.outputs.extent.weights", False, True),
        # Covered by the move of the whole [modflow6] table to [solver.modflow6].
        ("modflow6.process_specific.vka", True, False),
        ("modflow6.sgrid", True, False),
        # The row and the line both hold a table that a pre-release wrote under [modflow6].
        ("modflow6.sgrid.vertical.nlay", True, True),
        # Retired with a rule that writes the key elsewhere.
        ("geographic.catchment.dem_init_path", True, False),
        # Written by hmp init of 2.0.0, so a row of 2.0.0 and no line.
        ("simulation.process.type", True, False),
        # The parent of a moved table is not moved with it.
        ("flow", False, False),
        ("calibration.max_trials", False, False),
        # A line of one value covers no key: the key stays with its other values.
        ("simulation.if_exists", False, False),
        ("display.figures", False, False),
        ("geographic.catchment.buff_area", False, False),
        # A line of the tables under a key covers what lies below it, not the key.
        ("export.variables", False, False),
        ("export.variables.head", False, True),
    ],
)
def test_a_path_finds_the_row_or_the_line_that_covers_it(path: str, row: bool, line: bool) -> None:
    assert (surface.migration_for(path) is not None) is row
    assert (surface.prerelease_form_for(path) is not None) is line
    assert (surface.toml_entry_for(path) is not None) is (row or line)
