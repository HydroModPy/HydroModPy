"""The register of changes, ``changes.toml``, read once and checked.

The register lists each bug fix that changes a number, each default that moves with
an edition, each recipe that changes a computation or a rule, and each key that moves
or leaves in the TOML grammar or in a stored document. The label of a run reads its
bugs, the migration of a configuration reads its ``document = "config"`` rows, and
the ``Numbers`` block of the changelog is generated from it.

The file ships beside this module and is read at import into :data:`REGISTER`. Nothing
writes it during a run. A defect of the file raises :class:`ValueError` with one line
per fault, so a broken register stops the import, and every test with it.

The delay of an old form is written here once: :data:`DELAY_MINORS` minor versions,
the one that retired it included (:func:`removal_of`, :func:`outlived`). The
configuration, the old Python names and the old command forms all read it.
"""

from __future__ import annotations

import copy
import re
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Final, Literal

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

SCHEMA: Final[str] = "hydromodpy.changes.v1"
"""The value of the ``schema`` key of the register."""

REGISTER_FILENAME: Final[str] = "changes.toml"
"""The register, package data of this module."""

DELAY_MINORS: Final[int] = 2
"""How many minor versions an old form loads, the one that retired it included.

``since = "2.3.0"`` loads, with a warning, in 2.3 and in 2.4, and is refused in 2.5.
"""

FIRST_EDITION: Final[str] = "2.0"
"""The edition of a file that writes none: the defaults of 2.0."""

EFFECTS: Final[frozenset[str]] = frozenset({"numbers", "refusal", "label", "identity", "layout"})
"""What a recipe changes."""

_TABLES = ("bug", "default", "recipe", "migration")
_REQUIRED = {
    "bug": frozenset({"id", "since", "versions", "quantities", "text"}),
    "default": frozenset({"id", "since", "edition", "key", "old", "new", "quantities", "text"}),
    "recipe": frozenset({"id", "since", "effect", "quantities", "text"}),
    "migration": frozenset({"document", "since"}),
}
_OPTIONAL = {
    "bug": frozenset({"commit"}),
    "default": frozenset(),
    "recipe": frozenset(),
    "migration": frozenset({"rule", "sealed"}),
}
_SHAPES: dict[str, frozenset[str]] = {
    "move": frozenset({"old", "new"}),
    "retire": frozenset({"old", "instead"}),
    "value": frozenset({"key", "old_value", "new_value"}),
}
_SHAPE_FIELDS = frozenset().union(*_SHAPES.values())

_ID = re.compile(r"^[a-z0-9_]+$")
_SINCE = re.compile(r"^\d+\.\d+\.\d+$")
_EDITION = re.compile(r"^\d+\.\d+$")
_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
_DOCUMENT = re.compile(r"^(job\.)?[a-z_]+$")
_RULE = re.compile(r"^[a-z][a-z0-9_]*$")
_SEGMENT = r"(?:[A-Za-z0-9_-]+(?:\[\*\])?|\{\*\})"
_PATH = re.compile(rf"^{_SEGMENT}(?:\.{_SEGMENT})*$")


@dataclass(frozen=True)
class Bug:
    """A fix that changes a number. A run of one of ``versions`` is labelled exploratory."""

    id: str
    since: str
    versions: str
    quantities: tuple[str, ...]
    text: str
    commit: str | None = None

    def hits(self, version: str, quantities: Sequence[str]) -> bool:
        """Whether the bug touches a run of *version* that exposes *quantities*."""
        affected = SpecifierSet(self.versions, prereleases=True)
        return Version(version) in affected and bool(set(self.quantities) & set(quantities))


@dataclass(frozen=True)
class Default:
    """A default that moves with an edition. A file of an older edition keeps ``old``."""

    id: str
    since: str
    edition: str
    key: str
    old: Any
    new: Any
    quantities: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class Recipe:
    """A computation or a rule that changes without a bug."""

    id: str
    since: str
    effect: str
    quantities: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class Migration:
    """One key that moves or leaves, or one value renamed, in one document.

    A path is dotted, with ``[*]`` for each table of a list and ``{*}`` for the
    tables under free names. ``rule`` names a function of the table ``RULES`` of the
    reader of ``document`` when the row cannot say the whole change.
    """

    document: str
    since: str
    old: str | None = None
    new: str | None = None
    instead: str | None = None
    sealed: str | None = None
    key: str | None = None
    old_value: Any = None
    new_value: Any = None
    rule: str | None = None

    @property
    def shape(self) -> Literal["move", "retire", "value"]:
        """``move`` for a key at a new path, ``retire`` for a key that leaves, ``value``."""
        if self.key is not None:
            return "value"
        return "retire" if self.instead is not None else "move"


@dataclass(frozen=True)
class Register:
    """Every row of the register, by table, in the order of the file."""

    bugs: tuple[Bug, ...] = ()
    defaults: tuple[Default, ...] = ()
    recipes: tuple[Recipe, ...] = ()
    migrations: tuple[Migration, ...] = ()


def _version_errors(row: dict[str, Any], where: str) -> list[str]:
    since = row.get("since")
    if not (isinstance(since, str) and _SINCE.match(since)):
        return [f"{where}: since must be a full version such as '2.1.0', got {since!r}"]
    return []


def _path_errors(row: dict[str, Any], field: str, where: str) -> list[str]:
    value = row.get(field)
    if isinstance(value, str) and _PATH.match(value):
        return []
    return [f"{where}: {field} must be a dotted path, got {value!r}"]


def _quantity_errors(row: dict[str, Any], where: str, *, needed: bool) -> list[str]:
    tokens = row.get("quantities")
    if not (isinstance(tokens, list) and all(isinstance(t, str) and t for t in tokens)):
        return [f"{where}: quantities must be a list of strings, got {tokens!r}"]
    errors = []
    if needed and not tokens:
        errors.append(f"{where}: quantities is empty, but this row changes a number")
    if len(set(tokens)) != len(tokens):
        errors.append(f"{where}: quantities repeats a token")
    return errors


def _text_errors(row: dict[str, Any], where: str) -> list[str]:
    text = row.get("text")
    if isinstance(text, str) and text.strip():
        return []
    return [f"{where}: text must be a non-empty string"]


def _bug_errors(row: dict[str, Any], where: str) -> list[str]:
    errors = _quantity_errors(row, where, needed=True) + _text_errors(row, where)
    try:
        SpecifierSet(str(row.get("versions")), prereleases=True)
        if not str(row.get("versions", "")).strip():
            raise InvalidSpecifier("empty")
    except InvalidSpecifier:
        errors.append(f"{where}: versions must be a PEP 440 specifier set, got {row['versions']!r}")
    commit = row.get("commit")
    if commit is not None and not (isinstance(commit, str) and _COMMIT.match(commit)):
        errors.append(f"{where}: commit must be a hex sha of 7 to 40 characters, got {commit!r}")
    return errors


def _default_errors(row: dict[str, Any], where: str) -> list[str]:
    errors = _path_errors(row, "key", where)
    edition = row.get("edition")
    if not (isinstance(edition, str) and _EDITION.match(edition)):
        errors.append(f"{where}: edition must be a minor version such as '2.1', got {edition!r}")
    elif row.get("since") != f"{edition}.0":
        # A default joins an edition when it comes out. Later, it would change the
        # files already written with that edition.
        errors.append(f"{where}: a default of edition {edition!r} has since '{edition}.0'")
    if any(isinstance(row.get(field), dict) for field in ("old", "new")):
        errors.append(f"{where}: old and new must be TOML values, not tables")
    if row.get("old") == row.get("new"):
        errors.append(f"{where}: old and new are the same value")
    # A default lists the quantities it moves, none when it only changes what is written.
    return errors + _quantity_errors(row, where, needed=False) + _text_errors(row, where)


def _recipe_errors(row: dict[str, Any], where: str) -> list[str]:
    effect = row.get("effect")
    errors = [] if effect in EFFECTS else [f"{where}: effect must be one of {sorted(EFFECTS)}"]
    return errors + _quantity_errors(row, where, needed=effect == "numbers")


_ROW_ERRORS = {"bug": _bug_errors, "default": _default_errors, "recipe": _recipe_errors}


def _migration_errors(row: dict[str, Any], where: str) -> tuple[list[str], tuple[Any, ...] | None]:
    """Return the faults of one migration row and the identity it must not share."""
    document = row.get("document")
    if not (isinstance(document, str) and _DOCUMENT.match(document)):
        return [f"{where}: document must match {_DOCUMENT.pattern}, got {document!r}"], None
    present = frozenset(row) & _SHAPE_FIELDS
    shape = next((name for name, fields in _SHAPES.items() if fields == present), None)
    if shape is None:
        return [
            f"{where}: a migration row has exactly one shape, old+new, old+instead or "
            f"key+old_value+new_value, got {sorted(present)}"
        ], None
    errors: list[str] = []
    if "sealed" in row and (shape != "retire" or row["sealed"] != "drop"):
        errors.append(f"{where}: sealed only takes 'drop', and only on a key that leaves")
    rule = row.get("rule")
    if rule is not None and not (isinstance(rule, str) and _RULE.match(rule)):
        # A rule is a key of the table of its reader, never a module path.
        errors.append(f"{where}: rule must be a name in [a-z][a-z0-9_]*, got {rule!r}")
    if shape == "value":
        errors.extend(_path_errors(row, "key", where))
        for field in ("old_value", "new_value"):
            if not isinstance(row[field], str | int | float | bool):
                errors.append(f"{where}: {field} must be a string, a number or a boolean")
        if row["old_value"] == row["new_value"]:
            errors.append(f"{where}: old_value and new_value are the same value")
        return errors, (document, "key", row["key"], repr(row["old_value"]))
    errors.extend(_path_errors(row, "old", where))
    if shape == "move":
        errors.extend(_path_errors(row, "new", where))
        if row["old"] == row["new"]:
            errors.append(f"{where}: old and new are the same path")
    elif not (isinstance(row["instead"], str) and row["instead"].strip()):
        errors.append(f"{where}: instead must be a non-empty string")
    return errors, (document, "old", row["old"])


def _built(table: str, row: dict[str, Any]) -> Bug | Default | Recipe | Migration:
    fields = dict(row)
    if "quantities" in fields:
        fields["quantities"] = tuple(fields["quantities"])
    kind = {"bug": Bug, "default": Default, "recipe": Recipe, "migration": Migration}[table]
    return kind(**fields)


def read(text: str) -> Register:
    """Return the register written in *text*, or raise :class:`ValueError` on any fault."""
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{REGISTER_FILENAME} cannot be read: {exc}") from exc
    errors: list[str] = []
    if document.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA!r}, got {document.get('schema')!r}")
    errors.extend(
        f"unknown top-level key {key!r}" for key in sorted(set(document) - {"schema", *_TABLES})
    )
    ids: dict[str, str] = {}
    identities: dict[tuple[Any, ...], str] = {}
    rows: dict[str, list[Any]] = {table: [] for table in _TABLES}
    for table in _TABLES:
        entries = document.get(table, [])
        if not (isinstance(entries, list) and all(isinstance(e, dict) for e in entries)):
            errors.append(f"{table} must be an array of tables, [[{table}]]")
            continue
        for number, row in enumerate(entries, start=1):
            where = f"[[{table}]] #{number}"
            allowed = _REQUIRED[table] | _OPTIONAL[table]
            if table == "migration":
                allowed |= _SHAPE_FIELDS
            found = [f"{where}: missing field {f!r}" for f in sorted(_REQUIRED[table] - set(row))]
            found += [f"{where}: unknown field {f!r}" for f in sorted(set(row) - allowed)]
            found += _version_errors(row, where)
            if table == "migration":
                faults, identity = _migration_errors(row, where)
                found += faults
                if identity is not None and identity in identities:
                    found.append(f"{where}: same row as {identities[identity]}")
                elif identity is not None:
                    identities[identity] = where
            else:
                row_id = row.get("id")
                if not (isinstance(row_id, str) and _ID.match(row_id)):
                    found.append(f"{where}: id must match [a-z0-9_]+, got {row_id!r}")
                elif row_id in ids:
                    found.append(f"{where}: id {row_id!r} is already used by {ids[row_id]}")
                else:
                    ids[row_id] = where
                if not found:
                    found += _ROW_ERRORS[table](row, where)
            errors.extend(found)
            if not found:
                rows[table].append(_built(table, row))
    if errors:
        raise ValueError(f"{REGISTER_FILENAME} has {len(errors)} fault(s):\n" + "\n".join(errors))
    return Register(
        bugs=tuple(rows["bug"]),
        defaults=tuple(rows["default"]),
        recipes=tuple(rows["recipe"]),
        migrations=tuple(rows["migration"]),
    )


REGISTER: Final[Register] = read(
    files(__package__).joinpath(REGISTER_FILENAME).read_text(encoding="utf-8")
)
"""The register this build ships."""


def migrations_of(document: str, register: Register = REGISTER) -> tuple[Migration, ...]:
    """Return the migration rows of *document*, in the order of the file."""
    return tuple(row for row in register.migrations if row.document == document)


Rule = Callable[[dict[str, Any]], None]
"""A migration rule: a function that changes one document in memory."""


def apply_rows(
    document: str,
    payload: Mapping[str, Any],
    *,
    register: Register = REGISTER,
    rules: Mapping[str, Rule] | None = None,
) -> dict[str, Any]:
    """Return *payload* with the migration rows of *document* applied, in file order.

    Nothing is written: a sealed file stays as it was written, and the reader
    converts its copy in memory. A row whose old path is absent changes
    nothing, so a document read twice reads the same. A row that names a
    ``rule`` is followed by that rule of the reader's table, after the paths
    it moves or retires; a rule the reader does not supply is refused.
    """
    result = copy.deepcopy(dict(payload))
    for row in migrations_of(document, register):
        if row.shape == "move":
            _move(result, row.old, row.new)
        elif row.shape == "retire":
            _retire(result, row.old)
        else:
            _renamed_value(result, row.key, row.old_value, row.new_value)
        if row.rule is not None:
            if rules is None or row.rule not in rules:
                raise ValueError(f"{document}: no rule named {row.rule!r} to apply a migration row")
            rules[row.rule](result)
    return result


def _move(document: dict[str, Any], old: str, new: str) -> None:
    """Move each value at *old* to *new*, keeping the order of the matched tables."""
    sources = [slot for slot in _slots(document, old) if slot[1] in slot[0]]
    if not sources:
        return
    targets = _slots(document, new)
    if len(sources) != len(targets):
        raise ValueError(
            f"migration {old!r} to {new!r} matches {len(sources)} source(s) "
            f"and {len(targets)} target(s)"
        )
    for (source, key), (target, new_key) in zip(sources, targets, strict=True):
        target[new_key] = source.pop(key)


def _retire(document: dict[str, Any], old: str) -> None:
    """Remove every value at *old* from the copy in memory."""
    for container, key in _slots(document, old):
        container.pop(key, None)


def _renamed_value(document: dict[str, Any], path: str, old_value: Any, new_value: Any) -> None:
    """Rename *old_value* to *new_value* at *path*; any other value stays."""
    for container, key in _slots(document, path):
        if container.get(key) == old_value:
            container[key] = new_value


def _slots(document: dict[str, Any], path: str) -> list[tuple[dict[str, Any], str]]:
    """Return each (object, key) a dotted path names, present or not."""
    segments = path.split(".")
    return [
        (container, segments[-1])
        for container in _containers(document, segments[:-1])
        if isinstance(container, dict)
    ]


def _containers(node: Any, segments: list[str]) -> list[Any]:
    """Return the nodes reached by walking *segments* from *node*."""
    nodes = [node]
    for segment in segments:
        reached: list[Any] = []
        for current in nodes:
            reached.extend(_children(current, segment))
        nodes = reached
    return nodes


def _children(node: Any, segment: str) -> list[Any]:
    """Return what one path segment selects inside *node*."""
    if segment == "{*}":
        return list(node.values()) if isinstance(node, dict) else []
    name, star = (segment[:-3], True) if segment.endswith("[*]") else (segment, False)
    if not isinstance(node, dict) or name not in node:
        return []
    value = node[name]
    if star:
        return list(value) if isinstance(value, list) else []
    return [value]


def editions(register: Register = REGISTER) -> tuple[str, ...]:
    """Return every edition a file may write, the first one first."""
    later = {row.edition for row in register.defaults} - {FIRST_EDITION}
    return (FIRST_EDITION, *sorted(later, key=Version))


def removal_of(since: str) -> str:
    """Return the first version that no longer loads a form retired in *since*."""
    major, minor = Version(since).release[:2]
    return f"{major}.{minor + DELAY_MINORS}.0"


def outlived(since: str, version: str) -> bool:
    """Whether *version*, a pre-release included, is past the delay of a form of *since*."""
    try:
        reached = Version(version).release[:2]
    except InvalidVersion as exc:
        raise ValueError(f"{version!r} is not a version") from exc
    return reached >= Version(removal_of(since)).release[:2]


def prerelease_refusal(where: str, names: Sequence[str], *, rewritable: bool = True) -> str:
    """Return the one sentence that refuses what only a pre-release of 2.0 wrote.

    *where* is the file, or what holds the keys. *rewritable* is false for a source
    with no file to rewrite, such as ``--set``.
    """
    held = ", ".join(names)
    told = (
        f"{where} holds {held}, written by a pre-release of 2.0. HydroModPy 2.1 no longer reads it."
    )
    if not rewritable:
        return f"{told} Write today's name instead."
    return (
        f'{told} Run `pip install "hydromodpy~=2.0.0"` then `hmp doctor --fix-config <file>`, '
        "which rewrites it, and come back to this version."
    )


__all__ = [
    "DELAY_MINORS",
    "EFFECTS",
    "FIRST_EDITION",
    "REGISTER",
    "REGISTER_FILENAME",
    "SCHEMA",
    "Bug",
    "Default",
    "Migration",
    "Recipe",
    "Register",
    "Rule",
    "apply_rows",
    "editions",
    "migrations_of",
    "outlived",
    "prerelease_refusal",
    "read",
    "removal_of",
]
