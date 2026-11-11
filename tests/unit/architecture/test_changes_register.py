"""The register of changes is read, every row has its reader, and nothing moves without a row.

``hydromodpy/schema/changes.toml`` lists each bug fix, each default that moves with an
edition, each rule that moves a number and each key that moves. This gate holds what
the reader cannot see alone: a ``rule`` names a function of the reader of its
document, each document has a reader, no row is dated past the next minor version,
each default that differs from 2.0.0 has its row, and the ``Numbers`` block of
``CHANGELOG.md`` is the one the register writes. Each field new since 2.0.0 has a
reviewed default that keeps the numbers of 2.0, and no bug covers the version of this
tree. Run with ``-s`` to see the counts and each new field with its default.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import pytest
from packaging.version import Version

from hydromodpy.config.config_migration import RULES as CONFIG_RULES
from hydromodpy.core.version import __version__
from hydromodpy.results.record.forms import RULES as RUN_SEAL_RULES
from hydromodpy.schema.changes import REGISTER, REGISTER_FILENAME, migrations_of, read
from hydromodpy.schema.job.seal import JOB_SEAL_RULES

REPO = Path(__file__).resolve().parents[3]
SNAPSHOT_2_0_0 = REPO / "tools" / "docs" / "snapshots" / "fields-2.0.0.json"

# Each document a row may name, with the module that reads its rows and the
# functions a row of that document may name by ``rule``.
READERS: dict[str, tuple[str, dict[str, Callable[..., Any]]]] = {
    "config": ("hydromodpy.config.config_migration", CONFIG_RULES),
    "sidecar": ("hydromodpy.data.provenance.sidecars", {}),
    "fields": ("hydromodpy.results.zarr_store.zarr_reader", {}),
    "manifest": ("hydromodpy.results.record.forms", RUN_SEAL_RULES),
    "identity": ("hydromodpy.results.record.forms", {}),
    "job.manifest": ("hydromodpy.schema.job.seal", JOB_SEAL_RULES),
}


def test_the_register_reads_and_counts_its_rows() -> None:
    text = (REPO / "hydromodpy" / "schema" / REGISTER_FILENAME).read_text(encoding="utf-8")

    assert read(text) == REGISTER
    counts = {
        "bug": len(REGISTER.bugs),
        "default": len(REGISTER.defaults),
        "recipe": len(REGISTER.recipes),
        "migration": len(REGISTER.migrations),
    }
    print("\nrows of the register:", ", ".join(f"{k} {v}" for k, v in counts.items()))
    for document in sorted({row.document for row in REGISTER.migrations}):
        print(f"  migration of {document}: {len(migrations_of(document))}")
    assert sum(counts.values()) > 0


def test_each_document_has_a_reader() -> None:
    documents = {row.document for row in REGISTER.migrations}

    assert documents <= set(READERS), f"no reader for {sorted(documents - set(READERS))}"


def test_each_rule_is_a_function_of_the_reader_of_its_document() -> None:
    unknown = [
        f"{row.document}: {row.rule}"
        for row in REGISTER.migrations
        if row.rule is not None and row.rule not in READERS[row.document][1]
    ]

    assert unknown == []


def test_each_function_of_a_reader_is_named_by_a_row() -> None:
    named = {(row.document, row.rule) for row in REGISTER.migrations if row.rule}
    unnamed = [
        f"{document}: {rule}"
        for document, (_module, rules) in READERS.items()
        for rule in rules
        if (document, rule) not in named
    ]

    assert unnamed == []


def test_the_sidecar_reader_reads_its_rows() -> None:
    source = (REPO / "hydromodpy" / "data" / "provenance" / "sidecars.py").read_text()

    assert 'migrations_of("sidecar")' in source


def test_no_row_is_dated_past_the_next_minor_version() -> None:
    current = Version(__version__)
    ceiling = Version(f"{current.major}.{current.minor + 1}.0")
    rows = [*REGISTER.bugs, *REGISTER.defaults, *REGISTER.recipes, *REGISTER.migrations]
    late = [f"{row.since}: {row}" for row in rows if Version(row.since) > ceiling]

    assert late == []


def _value(rendered: str | None) -> Any:
    """Read a default as the registry of fields renders it."""
    if rendered is None:
        return None
    try:
        return json.loads(rendered)
    except json.JSONDecodeError:
        return rendered


def _registry_path(path: str) -> str:
    """Write a path of the register as the registry of fields writes it, ``*`` for a name."""
    return path.replace("[*]", "").replace("{*}", "*")


def _explained(path: str, old: Any, new: Any) -> bool:
    """Whether a row of the register says this default moved."""
    for row in REGISTER.defaults:
        if fnmatchcase(path, _registry_path(row.key)) and (row.old, row.new) == (old, new):
            return True
    return any(
        row.shape == "value"
        and fnmatchcase(path, _registry_path(str(row.key)))
        and (row.old_value, row.new_value) == (old, new)
        for row in migrations_of("config")
    )


@pytest.fixture(scope="module")
def fields_since_2_0_0() -> dict[str, Any]:
    from tools.docs.field_registry import build_payload
    from tools.docs.legacy_keys import moved_tables
    from tools.docs.toml_changelog import diff

    payload, _gates = build_payload("tree")
    released = json.loads(SNAPSHOT_2_0_0.read_text(encoding="utf-8"))
    return {"diff": diff(released, payload, moved_tables()), "nodes": payload["nodes"]}


def test_each_default_that_moved_since_2_0_0_has_its_row(fields_since_2_0_0: dict) -> None:
    moved = [
        (change["path"], *change["changes"]["default"])
        for change in fields_since_2_0_0["diff"]["changed"]
        if "default" in change["changes"]
    ]
    missing = [
        f"{path}: {old} -> {new}"
        for path, old, new in moved
        if not _explained(path, _value(old), _value(new))
    ]

    assert missing == [], (
        "A default moved without its row. Write a [[default]] row in "
        "hydromodpy/schema/changes.toml whose old value keeps the computation of 2.0.0."
    )


_UNSET = "not set"
_A_SOURCE_PIN = (
    "Unset, the source reads no remote file and pins nothing: a file of 2.0 never wrote it."
)
_A_RUN_BUDGET = "Unset, a trial runs with no wall-clock limit, as in 2.0."

# Each field new since 2.0.0, by the path the registry of fields writes, with the default
# it has and why that default keeps the computation of a file of edition 2.0. The replay
# of a sealed run reads a key its frozen config does not write at this default, so a new
# field that would move a number needs a [[default]] row instead of a line here.
NEW_FIELDS: dict[str, tuple[Any, str]] = {
    "data.*.sources.license": (_UNSET, "Written to the sidecar only, it reads no number."),
    "data.*.sources.sha256": (_UNSET, _A_SOURCE_PIN),
    "data.*.sources.url": (_UNSET, _A_SOURCE_PIN),
    "edition": ("2.0", "A file that writes none is read with the defaults of 2.0."),
    "export.deliver_to": (
        _UNSET,
        "Unset, a block delivers nothing, as a block of 2.0 did; the file it writes is the same.",
    ),
    "data.dem.sources.state": (
        "raw",
        "Raw, so HydroModPy conditions the DEM as a file of 2.0 did; a file of 2.0 wrote no state.",
    ),
    "solver.boussinesq.exchange_mesh": (
        _UNSET,
        "Unset, the Boussinesq solver reads the cell mesh of its model, as in 2.0.",
    ),
    "solver.boussinesq.wall_clock_limit_s": (_UNSET, _A_RUN_BUDGET),
    "solver.modflow_nwt.wall_clock_limit_s": (_UNSET, _A_RUN_BUDGET),
    "solver.linear_reservoir": (
        None,
        "The table of a new backend, read only when solver.backend names it.",
    ),
    "simulation.results.keep_face_flows": (
        False,
        "False, a run keeps no inter-cell flow, as a file of 2.0 did.",
    ),
    "simulation.time.window": ("all", "Absent, the run is one window, as in 2.0."),
    "simulation.time.window_length": (
        _UNSET,
        "Unset, the run is not cut into windows, as in 2.0.",
    ),
    "workspace.products_cap_mb": (
        5000,
        "A file of 2.0 wrote no store, and the cap is far above it: nothing is evicted, so a run reads the same mesh and soil bytes.",
    ),
}


def _reviewed(path: str) -> tuple[Any, str] | None:
    """Return the reviewed default of a new field, ``None`` when it has no line."""
    for pattern, line in NEW_FIELDS.items():
        if fnmatchcase(path, pattern):
            return line
    return None


def test_each_field_new_since_2_0_0_keeps_the_numbers_of_2_0_at_its_default(
    fields_since_2_0_0: dict,
) -> None:
    """A new field must keep the numbers of a file of edition 2.0 at its default.

    Each one has its line in ``NEW_FIELDS``, with its default and the reason. A default
    that changes a number needs a ``[[default]]`` row whose old value keeps the
    computation of edition 2.0. The gate prints each field for the review.
    """
    nodes = fields_since_2_0_0["nodes"]
    added = fields_since_2_0_0["diff"]["added"]
    print(f"\nfields new since 2.0.0: {len(added)}")
    faults = []
    for path in added:
        default = _value(nodes[path].get("default"))
        print(f"  {path} ({nodes[path].get('kind')}): {default!r}")
        reviewed = _reviewed(path)
        if reviewed is None:
            faults.append(f"{path}: no line in NEW_FIELDS")
        elif default != reviewed[0] and not (default is None and reviewed[0] == _UNSET):
            faults.append(f"{path}: default {default!r}, reviewed {reviewed[0]!r}")
    unused = [pattern for pattern in NEW_FIELDS if not any(fnmatchcase(p, pattern) for p in added)]

    assert faults == [], (
        "A field new since 2.0.0 has no reviewed default. Add its line to NEW_FIELDS with "
        "the reason its default keeps the numbers of 2.0, or write a [[default]] row in "
        "hydromodpy/schema/changes.toml."
    )
    assert unused == [], f"{unused} match no field new since 2.0.0: remove their lines."


def test_no_bug_touches_the_version_of_this_tree() -> None:
    """The tree that holds the fix of a bug must not seal its runs inside the bug's range.

    A run seals ``__version__`` for good. When a row's ``versions`` holds it, every run of
    this tree is labelled with a bug it does not have. Set the version of the tree past
    the range, to the next ``.dev0`` after a release.
    """
    hit = [bug.id for bug in REGISTER.bugs if bug.hits(__version__, bug.quantities)]

    assert hit == [], f"HydroModPy {__version__} falls inside the versions of {hit}."


def test_the_numbers_block_of_the_changelog_is_the_one_the_register_writes() -> None:
    from tools.changes_changelog import CHANGELOG, rewrite

    text = CHANGELOG.read_text(encoding="utf-8")

    assert rewrite(text) == text, "Run python -m tools.changes_changelog --write."
