"""A form that left is refused with a sentence that names the form that replaces it.

Three tables are read, never copied. The TOML keys that left are the rows of
``surface/removed_toml_keys.tsv``, the Python names are ``OLD_NAMES`` and the
commands of ``hmp`` are ``OLD_CLI_FORMS``. A test of each table checks that its
rows are the whole ledger, so a form that leaves without a row here fails.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

import pytest

import hydromodpy
from hydromodpy._lazy import OLD_NAMES
from hydromodpy.cli.conventions import OLD_CLI_FORMS
from hydromodpy.cli.main import _build_parser
from hydromodpy.config.check import check
from hydromodpy.config.config_migration import document_path
from hydromodpy.core.exceptions import OldNameError
from hydromodpy.schema.changes import Migration, migrations_of

SURFACE = Path(__file__).resolve().parents[1] / "unit" / "architecture" / "surface"


def _rows_of(name: str) -> list[list[str]]:
    lines = (SURFACE / name).read_text(encoding="utf-8").splitlines()
    return [line.split("\t") for line in lines if line.strip()]


REMOVED_KEYS = [key for key, _ in _rows_of("removed_toml_keys.tsv")]
TYPES = {row[0]: row[1] for row in _rows_of("toml_fields.tsv")}
VALUES = {"solver.backend.kind": "modflow6"}
"""The keys whose old value has to be a string for the refusal to read the document."""


def _document_of(key: str) -> dict[str, Any]:
    """Return a document that writes *key* as a live file would.

    A mapping of tables gets one table under a free name and a list of tables gets one
    item, as the types of the current surface say. A parent the surface no longer
    holds is a plain table.
    """
    parts = key.split(".")
    document: dict[str, Any] = {}
    node = document
    for depth, part in enumerate(parts[:-1]):
        kind = TYPES.get(".".join(parts[: depth + 1]), "table")
        child: dict[str, Any] = {}
        if kind.startswith("list["):
            node[part] = [child]
        elif kind.startswith("dict["):
            node[part] = {"x": child}
        else:
            node[part] = child
        node = child
    node[parts[-1]] = VALUES.get(key, 1)
    return document


def _row_of(key: str) -> Migration | None:
    """Return the row of ``changes.toml`` that moves or retires *key*, itself or by a parent."""
    for row in migrations_of("config"):
        old = document_path(row.key if row.shape == "value" else str(row.old))
        if key == old or key.startswith(f"{old}."):
            return row
    return None


def _names_the_form(row: Migration, text: str) -> bool:
    text = text.lower()
    if row.shape == "move":
        return document_path(str(row.new)).rsplit(".", 1)[-1].lower() in text
    if row.shape == "value":
        return str(row.new_value).lower() in text
    instead = str(row.instead).lower()
    named = re.findall(r"\[\[[\w.]+\]\]|\w+(?:\.\w+)+", instead)
    return instead[:24] in text or any(token in text for token in named)


@pytest.mark.parametrize("key", REMOVED_KEYS)
def test_a_key_that_left_is_refused_and_the_sentence_names_its_form(
    key: str, tmp_path: Path
) -> None:
    found = [
        item
        for item in check(_document_of(key), base=tmp_path, partial=True)
        if item.code in ("old_key", "retired_key")
    ]
    text = " ".join(item.detail for item in found)
    row = _row_of(key)

    assert found, key
    if row is None:
        # A form only a pre-release of 2.0 wrote: the sentence names the key and the
        # release whose doctor rewrites it.
        assert {item.code for item in found} == {"retired_key"}
        assert "pre-release of 2.0" in text and key.rsplit(".", 1)[-1] in text
    else:
        assert _names_the_form(row, text), (key, text)


def test_the_stage_of_a_lake_has_one_name_and_the_sentence_gives_it(tmp_path: Path) -> None:
    key = "flow.sinks_sources.lakes.stageinit"
    text = " ".join(item.detail for item in check(_document_of(key), base=tmp_path))

    assert "initial_stage" in text


def test_a_document_that_misses_its_field_section_is_refused_not_a_crash(tmp_path: Path) -> None:
    document = _document_of("flow.param.field_vertical_profile.mode")

    found = check(document, base=tmp_path, partial=True)

    assert any(item.code in ("refused_value", "retired_key") for item in found)
    assert any("requires section [flow.param.x.field]" in item.detail for item in found)


def test_the_table_of_keys_is_the_whole_ledger() -> None:
    assert REMOVED_KEYS
    assert len(set(REMOVED_KEYS)) == len(REMOVED_KEYS)
    assert {row[0] for row in _rows_of("removed_toml_keys.tsv")} == set(REMOVED_KEYS)


def _leading_path(new: str) -> str:
    """Return the dotted path a ``new`` field starts with, the call or the list after it dropped."""
    found = re.match(r"[\w.]+", new)
    assert found is not None, new
    return found.group(0)


def _resolves(path: str) -> bool:
    """Say whether *path* names a module or an attribute of ``hydromodpy``."""
    if path.startswith("hydromodpy."):
        try:
            importlib.import_module(path)
        except ModuleNotFoundError:
            module, _, attribute = path.rpartition(".")
            return hasattr(importlib.import_module(module), attribute)
        return True
    owner: Any = hydromodpy
    for part in path.split("."):
        if not hasattr(owner, part):
            return False
        owner = getattr(owner, part)
    return True


@pytest.mark.parametrize("old", sorted(OLD_NAMES))
def test_an_old_name_answers_with_the_path_that_replaces_it(old: str) -> None:
    entry = OLD_NAMES[old]

    if entry.refused:
        with pytest.raises(OldNameError, match=re.escape(entry.new)):
            getattr(hydromodpy, old)
        assert not hasattr(hydromodpy, old)
    else:
        with pytest.warns(FutureWarning, match=re.escape(entry.new)):
            getattr(hydromodpy, old)
    assert _resolves(_leading_path(entry.new)), entry.new


def test_a_call_that_replaces_an_old_name_starts_with_a_verb_of_the_facade() -> None:
    calls = {
        old: entry.new
        for old, entry in OLD_NAMES.items()
        if re.match(r"hydromodpy\.\w+\(", entry.new)
    }
    assert calls
    for old, new in calls.items():
        verb = _leading_path(new).removeprefix("hydromodpy.")
        assert verb in hydromodpy.__all__, (old, new)


def test_every_name_the_ledger_holds_has_its_row() -> None:
    ledger = [row[0] for row in _rows_of("removed_names.tsv")]
    names = [name for name in ledger if not name.startswith("hmp ")]
    commands = [name for name in ledger if name.startswith("hmp ")]
    olds = [form.old for form in OLD_CLI_FORMS]

    assert names and commands
    assert [name for name in names if name not in OLD_NAMES] == []
    # A flag of a command that left is covered by the form of the command.
    assert [
        name
        for name in commands
        if not any(name == old or name.startswith(f"{old} ") for old in olds)
    ] == []


def _argv_of(old: str) -> list[str]:
    return [*old.split()[1:], "x"]


@pytest.mark.parametrize("form", OLD_CLI_FORMS, ids=lambda form: form.old)
def test_an_old_command_exits_two_and_names_the_new_one(
    form: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    if not form.refused:
        with pytest.warns(FutureWarning, match=re.escape(form.new)):
            _build_parser().parse_args(_argv_of(form.old))
        return
    with pytest.raises(SystemExit) as refused:
        _build_parser().parse_args(_argv_of(form.old))

    assert refused.value.code == 2
    assert f"Write: {form.new}" in capsys.readouterr().err


def test_the_table_of_commands_has_no_form_twice() -> None:
    olds = [form.old for form in OLD_CLI_FORMS]
    assert olds and len(set(olds)) == len(olds)
