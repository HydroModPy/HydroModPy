"""The changes page shows a key or a table the loader moves as a move, not as a removal and an addition.

The moves are declared once, as the ``move`` rows of ``document = "config"`` in
``hydromodpy/schema/changes.toml``. The migration makes them and the docs list them, so the
page cannot name a path the loader does not move. A path that the register of a release moved
ends where the last row leads.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.config import config_migration
from hydromodpy.schema.changes import REGISTER, Migration, migrations_of
from tools.docs import field_registry, legacy_keys, toml_changelog

ROOT = Path(__file__).resolve().parents[3]
EXT = ROOT / "docs" / "source" / "_ext"
LAST_RELEASE = ROOT / "tools" / "docs" / "snapshots" / "fields-2.0.0.json"

LAYERING_MOVES = {
    "modflow6.sgrid.vertical": "domain.layers",
    "modflownwt.sgrid.vertical": "domain.layers",
}
"""A move of two tables to one, the case the diff has to carry the keys across."""

MOVES = legacy_keys.moved_tables()
"""Old path -> new path, as the register moves them."""

PLAIN_MOVES = [
    row
    for row in migrations_of("config")
    if row.shape == "move" and row.rule is None and "[*]" not in str(row.old)
]
"""The rows the generic move makes: no list to walk and no rule that moves them instead."""


@pytest.fixture(scope="module")
def ext_path():
    """The Sphinx extensions are modules of docs/source/_ext, not of a package."""
    sys.path.insert(0, str(EXT))
    yield
    sys.path.remove(str(EXT))


def _nested(path: str, leaf: Any) -> dict[str, Any]:
    """The document that holds *leaf* at the dotted *path*."""
    out = leaf
    for part in reversed(path.split(".")):
        out = {part: out}
    return out


def _node(kind: str, **attributes: Any) -> dict[str, Any]:
    return {"kind": kind, **attributes}


def _layering_registry(
    *, tables: tuple[str, ...], nlay_default: str, extra: bool, solver_keeps_sgrid: bool = True
) -> dict:
    """A registry payload that holds the layering under each of *tables*.

    With ``solver_keeps_sgrid`` each solver section keeps another key under ``sgrid``,
    as the real tree does, so the moved table is not the whole of its section.
    """
    nodes: dict[str, dict] = {"": {}, "domain": _node("table")}
    if solver_keeps_sgrid:
        for section in ("modflow6", "modflownwt"):
            nodes[section] = _node("table")
            nodes[f"{section}.sgrid"] = _node("table")
            nodes[f"{section}.sgrid.top_sampling"] = _node("leaf", default="auto")
    for table in tables:
        parts = table.split(".")
        for depth in range(1, len(parts) + 1):
            nodes.setdefault(".".join(parts[:depth]), _node("table"))
        nodes[f"{table}.nlay"] = _node("leaf", default=nlay_default)
        nodes[f"{table}.nodata"] = _node("leaf", default="-9999.0")
        if extra:
            nodes[f"{table}.pinch_out"] = _node("leaf", default="true")
    return {"meta": {"label": "x"}, "nodes": nodes}


# ---------------------------------------------------------------- one source


def test_the_page_reads_the_moves_the_register_declares() -> None:
    assert MOVES == {
        config_migration.document_path(str(row.old)): config_migration.document_path(str(row.new))
        for row in REGISTER.migrations
        if row.document == "config" and row.shape == "move"
    }
    assert MOVES["modflow6"] == "solver.modflow6"
    assert MOVES["modflownwt"] == "solver.modflow_nwt"
    assert MOVES["flow.runtime"] == "solver.boussinesq"


@pytest.mark.parametrize("move", PLAIN_MOVES, ids=lambda row: str(row.old))
def test_the_migration_moves_the_table_and_the_dotted_override_the_row_declares(
    move: Migration,
) -> None:
    """A declared move that the migration did not make would put a false line on the page."""
    old, new = str(move.old), str(move.new)
    doc = {
        **_nested(old, {"nlay": 4}),
        "calibration": {"phases": [{"name": "p", "overrides": {f"{old}.nlay": 6}}]},
    }

    config_migration.migrate_config_doc(doc)

    # The rows run in order, so a table that a later row moves again ends where it leads.
    destination = config_migration.rewrite_dotted_path(new)
    assert _descend(doc, destination) == {"nlay": 4}
    assert _descend(doc, old) is None
    assert doc["calibration"]["phases"][0]["overrides"] == {f"{destination}.nlay": 6}


def _descend(doc: dict, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(doc, dict) or part not in doc:
            return None
        doc = doc[part]
    return doc


def test_a_moved_key_inside_its_delay_is_a_key_the_loader_still_reads() -> None:
    accepted = legacy_keys.accepted_old_names()

    for row in PLAIN_MOVES:
        assert accepted[str(row.old)] == legacy_keys.MIGRATES


# ---------------------------------------------------------------- the diff


def test_without_the_declaration_a_move_reads_as_a_removal_and_an_addition() -> None:
    old = _layering_registry(tables=tuple(LAYERING_MOVES), nlay_default="1", extra=False)
    new = _layering_registry(tables=("domain.layers",), nlay_default="1", extra=False)

    out = toml_changelog.diff(old, new)

    assert out["removed"] == ["modflow6.sgrid.vertical", "modflownwt.sgrid.vertical"]
    assert out["added"] == ["domain.layers"]
    assert out["renamed"] == []


def test_a_declared_move_is_listed_once_with_its_old_and_new_path() -> None:
    old = _layering_registry(tables=tuple(LAYERING_MOVES), nlay_default="1", extra=False)
    new = _layering_registry(tables=("domain.layers",), nlay_default="3", extra=True)

    out = toml_changelog.diff(old, new, LAYERING_MOVES)

    assert out["renamed"] == [
        {"from": "modflow6.sgrid.vertical", "to": "domain.layers"},
        {"from": "modflownwt.sgrid.vertical", "to": "domain.layers"},
    ]
    assert out["removed"] == []
    # The table is not added, and the keys it carried are not added. A key it did not hold is.
    assert out["added"] == ["domain.layers.pinch_out"]
    # A key that kept its name is compared across the move, so a new default is not lost.
    assert out["changed"] == [{"path": "domain.layers.nlay", "changes": {"default": ["1", "3"]}}]


def test_a_moved_table_is_listed_even_when_its_whole_section_is_gone() -> None:
    old = _layering_registry(
        tables=tuple(LAYERING_MOVES), nlay_default="1", extra=False, solver_keeps_sgrid=False
    )
    new = _layering_registry(
        tables=("domain.layers",), nlay_default="1", extra=False, solver_keeps_sgrid=False
    )

    out = toml_changelog.diff(old, new, LAYERING_MOVES)

    assert [r["from"] for r in out["renamed"]] == list(LAYERING_MOVES)
    assert out["removed"] == ["modflow6", "modflownwt"]


def test_a_move_the_pair_does_not_hold_changes_nothing() -> None:
    new = _layering_registry(tables=("domain.layers",), nlay_default="1", extra=False)
    out = toml_changelog.diff(new, new, LAYERING_MOVES)
    assert out == toml_changelog.diff(new, new)

    old = _layering_registry(tables=tuple(LAYERING_MOVES), nlay_default="1", extra=False)
    gone = toml_changelog.diff(old, new, {"modflow6.sgrid.vertical": "a.table.nobody.has"})
    assert gone["removed"] == ["modflow6.sgrid.vertical", "modflownwt.sgrid.vertical"]
    assert gone["renamed"] == []


def test_the_history_passes_the_moves_to_every_pair() -> None:
    old = _layering_registry(tables=tuple(LAYERING_MOVES), nlay_default="1", extra=False)
    new = _layering_registry(tables=("domain.layers",), nlay_default="1", extra=False)

    out = toml_changelog.history([old, new], LAYERING_MOVES)

    assert [r["from"] for r in out["pairs"][0]["renamed"]] == list(LAYERING_MOVES)


def test_the_solver_tables_of_this_tree_are_a_move_against_the_last_release() -> None:
    payload, _gates = field_registry.build_payload("current")
    release = json.loads(LAST_RELEASE.read_text())
    assert release["meta"]["label"] == "2.0.0"
    assert {"modflow6", "modflownwt"} <= set(release["nodes"])

    out = toml_changelog.diff(release, toml_changelog.snapshot(payload), MOVES)

    assert {"from": "modflow6", "to": "solver.modflow6"} in out["renamed"]
    assert {"from": "modflownwt", "to": "solver.modflow_nwt"} in out["renamed"]
    assert "modflow6" not in out["removed"]
    assert "solver.modflow6" not in out["added"]


# ---------------------------------------------------------------- the page


def _page(hmp_params, monkeypatch: pytest.MonkeyPatch, pair: dict, nodes: dict) -> str:
    """Render the changes page for one pair of versions and return its HTML."""

    class Page(hmp_params.ChangelogDirective):
        env = SimpleNamespace(docname="changes")

    history = {"versions": [pair["from"], pair["to"]], "pairs": [pair]}
    monkeypatch.setattr(hmp_params, "current_builder", lambda: SimpleNamespace())
    monkeypatch.setattr(hmp_params, "version_history", lambda: history)
    monkeypatch.setitem(hmp_params.S, "nodes", nodes)
    monkeypatch.setitem(hmp_params.S, "home", {})
    return Page.__new__(Page).run()[0].astext()


def _moves_pair(to: str) -> dict:
    return {
        "from": "1.0.0",
        "to": to,
        "renamed": [{"from": old, "to": new} for old, new in MOVES.items()],
        "removed": [],
        "added": [],
        "changed": [],
    }


def _nodes_below_the_new_paths() -> dict:
    """A registry that holds a key under each destination, as a moved table has."""
    return {f"{new}.nlay": {"kind": "leaf"} for old, new in MOVES.items() if "." in new}


def test_the_page_lists_the_move_under_renamed_with_the_dotted_override(
    monkeypatch: pytest.MonkeyPatch, ext_path: None
) -> None:
    import hmp_params

    html = _page(
        hmp_params, monkeypatch, _moves_pair(hmp_params.CURRENT), _nodes_below_the_new_paths()
    )

    for old in MOVES:
        assert f"<code>{old}</code> is now" in html
    assert "&quot;modflow6.&lt;key&gt;&quot;" in html
    assert "&quot;solver.modflow6.&lt;key&gt;&quot;" in html
    assert "still loads; ConfigKeyRenamedWarning names the new key" in html
    assert "A file that writes an old name still loads, as each line says." in html
    assert "tc-req" not in html
    assert "Removed" not in html
    assert "Added" not in html


def test_a_moved_key_that_holds_no_table_names_the_override_by_its_path_alone(
    monkeypatch: pytest.MonkeyPatch, ext_path: None
) -> None:
    import hmp_params

    html = _page(hmp_params, monkeypatch, _moves_pair(hmp_params.CURRENT), {})

    assert "&quot;modflow6&quot;" in html
    assert "&lt;key&gt;" not in html


def test_a_pair_between_two_releases_does_not_promise_what_the_loader_does_now(
    monkeypatch: pytest.MonkeyPatch, ext_path: None
) -> None:
    import hmp_params

    html = _page(hmp_params, monkeypatch, _moves_pair("2.0.0"), _nodes_below_the_new_paths())

    assert "<code>modflow6</code> is now" in html
    assert "still loads" not in html
    assert "&lt;key&gt;" not in html
