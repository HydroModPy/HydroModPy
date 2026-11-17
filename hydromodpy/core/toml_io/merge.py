"""TOML payload merge helpers.

Tables merge key by key. Any other value in an overlay replaces the base
value. This holds for lists too, lists of tables included: a list in the
overlay replaces the inherited list whole, whatever their lengths.

Three suffixes change that rule for one key:

- ``<key>__append = [...]`` adds the items after the inherited ones;
- ``<key>__delete = true`` removes the inherited key or table;
- ``<key>__merge = [...]`` merges a list of tables with the inherited list,
  table by table, each with the inherited table of the same identity. The
  identity is the first of ``id``, ``name`` and ``source`` that every table of
  both lists holds. A table the overlay does not name stays as it is. A list of
  one table merges with a list of one table, since there is one way to pair
  them. Anything else is refused: position says nothing once a parent inserts
  a table.

For example::

    [base]
    process = ["A", "B"]

    # overlay
    [base]
    process__append = ["C"]
    # result: process = ["A", "B", "C"]

    mesh_catchment__delete = true

The suffixes are stripped during merge and never appear in the validated
:class:`HydroModPyConfig` payload.

A file may inherit several files, ``base_config = ["model.toml", "site.toml"]``,
and each of them its own. :func:`merge_graph` merges such a graph, each file
once, by one rule that holds at any depth: for each key, the most derived file
that writes it wins. A file that another writer inherits, directly or not, is
overridden by it. Two writers of a key that do not inherit from each other must
agree, or the merge is refused with both names: the order of a list of bases
never decides a value. A table is merged key by key across its writers, and the
items each writer adds with ``__append`` are kept in the order of the files,
bases first. A chain of single bases is a graph where each file inherits the
one before, so it merges as it always did.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import replace as replaced
from typing import Any

from hydromodpy.core.exceptions import ConfigError

_APPEND_SUFFIX = "__append"
_DELETE_SUFFIX = "__delete"
_MERGE_SUFFIX = "__merge"
DIRECTIVE_SUFFIXES = (_APPEND_SUFFIX, _DELETE_SUFFIX, _MERGE_SUFFIX)

IDENTITY_KEYS = ("id", "name", "source")
"""The keys that tell one table of a list from another, in the order ``__merge`` tries them.

The models that declare one of them are listed by a test, which walks the schema.
The merge itself runs on documents before validation, so it reads the keys only.
"""


def _split_directive_keys(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, list[Any]], set[str], dict[str, list[Any]]]:
    """Separate plain entries from merge directive keys."""
    replace: dict[str, Any] = {}
    append: dict[str, list[Any]] = {}
    delete: set[str] = set()
    merge: dict[str, list[Any]] = {}
    for key, value in payload.items():
        if key.endswith(_MERGE_SUFFIX):
            target = key[: -len(_MERGE_SUFFIX)]
            if not target:
                raise ValueError(f"empty target key for merge directive {key!r}")
            if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
                raise ValueError(f"merge directive {key!r} requires a list of tables")
            merge[target] = list(value)
        elif key.endswith(_APPEND_SUFFIX):
            target = key[: -len(_APPEND_SUFFIX)]
            if not target:
                raise ValueError(f"empty target key for append directive {key!r}")
            if not isinstance(value, list):
                raise ValueError(
                    f"merge directive {key!r} requires a list value, got {type(value).__name__}"
                )
            append[target] = list(value)
        elif key.endswith(_DELETE_SUFFIX):
            target = key[: -len(_DELETE_SUFFIX)]
            if not target:
                raise ValueError(f"empty target key for delete directive {key!r}")
            if value is not True:
                raise ValueError(f"merge directive {key!r} requires the literal boolean true")
            delete.add(target)
        else:
            replace[key] = value
    for target in merge:
        if target in replace:
            raise ValueError(
                f"{target!r} and {target + _MERGE_SUFFIX!r} are both set; write only one of them"
            )
    return replace, append, delete, merge


def _identity_key(tables: Sequence[Sequence[Mapping[str, Any]]]) -> str | None:
    """Return the identity key every table of the lists holds, or ``None``."""
    for key in IDENTITY_KEYS:
        if all(key in table for items in tables for table in items):
            return key
    return None


def _indexed_by(
    directive: str, identity: str, tables: Sequence[Mapping[str, Any]], whose: str
) -> dict[Any, Mapping[str, Any]]:
    """Return *tables* by their identity, refusing a value two of them share."""
    indexed: dict[Any, Mapping[str, Any]] = {}
    for table in tables:
        value = table[identity]
        if not isinstance(value, str | int) or value in indexed:
            raise ValueError(
                f"merge directive {directive!r}: {whose} tables cannot be told apart, "
                f"{identity} = {value!r} is not one value for one table. Give each table its "
                f"own {identity}, or replace the list with {directive.removesuffix(_MERGE_SUFFIX)!r}"
            )
        indexed[value] = table
    return indexed


def _merge_tables_by_identity(key: str, existing: Any, items: list[Any]) -> list[Any]:
    """Merge a list of tables with the inherited one, each table with its namesake."""
    directive = key + _MERGE_SUFFIX
    if existing is None:
        raise ValueError(f"merge directive {directive!r} has no inherited list to merge with")
    if not isinstance(existing, list) or not all(isinstance(item, Mapping) for item in existing):
        raise ValueError(
            f"merge directive {directive!r} needs an inherited list of tables "
            f"(found {type(existing).__name__})"
        )
    identity = _identity_key((existing, items))
    if identity is None:
        if len(existing) == len(items) == 1:
            return [_merge_two_payloads(existing[0], items[0])]
        keys = ", ".join(IDENTITY_KEYS[:-1]) + f" or {IDENTITY_KEYS[-1]}"
        raise ValueError(
            f"merge directive {directive!r} cannot pair these tables: every table on both "
            f"sides needs one of {keys}, and the {len(items)} table(s) written here and the "
            f"{len(existing)} inherited do not all hold one. Write that key in each table, "
            f"replace the list with {key!r}, or add tables with {key + _APPEND_SUFFIX!r}"
        )
    inherited = _indexed_by(directive, identity, existing, "the inherited")
    written = _indexed_by(directive, identity, items, "the written")
    unknown = [value for value in written if value not in inherited]
    if unknown:
        raise ValueError(
            f"merge directive {directive!r}: no inherited table has {identity} = "
            f"{unknown[0]!r} (the inherited ones are {list(inherited)!r}). Correct the "
            f"{identity}, or add the table with {key + _APPEND_SUFFIX!r}"
        )
    return [
        _merge_two_payloads(table, written[table[identity]])
        if table[identity] in written
        else table
        for table in existing
    ]


def _merge_two_payloads(
    base: Mapping[str, Any],
    override: Mapping[str, Any],
) -> dict[str, Any]:
    """Recursively merge one TOML override into one base payload."""
    replace, append, delete, merge = _split_directive_keys(override)
    merged: dict[str, Any] = dict(base)

    for key in delete:
        merged.pop(key, None)

    for key, value in replace.items():
        existing = merged.get(key)
        if isinstance(value, Mapping):
            # A table the base lacks still goes through the merge, so the
            # directives it carries are applied and stripped.
            base_table = existing if isinstance(existing, Mapping) else {}
            merged[key] = _merge_two_payloads(base_table, value)
        elif isinstance(value, list):
            # A list never merges with the inherited one, not even a list of
            # tables of the same length. ``__append`` and ``__merge`` do.
            merged[key] = list(value)
        else:
            merged[key] = value

    for key, items in merge.items():
        merged[key] = _merge_tables_by_identity(key, merged.get(key), items)

    for key, items in append.items():
        existing = merged.get(key)
        if existing is None:
            merged[key] = list(items)
        elif isinstance(existing, list):
            merged[key] = list(existing) + list(items)
        else:
            raise ValueError(
                f"cannot append to non-list value at key {key!r} (found {type(existing).__name__})"
            )
    return merged


def merge_toml_payloads(
    defaults: Mapping[str, Any],
    base_chain: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    overlays: Sequence[Mapping[str, Any]] | None = None,
    cli_overrides: Mapping[str, Any] | None = None,
    env_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge TOML payload layers in HydroModPy precedence order.

    Precedence is ``defaults < base_chain < overlays < CLI < env``, each
    layer applied by the one merge rule of this module. ``hmp run`` merges
    the file, its ``--overlay`` files, ``--set`` and ``HMP_SET_*``; the plan
    of a ``[sites]`` project merges the base of a recipe, the rendered table
    row, the site overlay and the recipe's own keys the same way. A mapping
    as ``base_chain`` is the two-argument form ``merge_toml_payloads(base,
    override)``.
    """
    merged: dict[str, Any] = dict(defaults)
    if isinstance(base_chain, Mapping):
        merged = _merge_two_payloads(merged, base_chain)
    elif base_chain is not None:
        for payload in base_chain:
            merged = _merge_two_payloads(merged, payload)
    for payload in overlays or ():
        merged = _merge_two_payloads(merged, payload)
    if cli_overrides:
        merged = _merge_two_payloads(merged, cli_overrides)
    if env_overrides:
        merged = _merge_two_payloads(merged, env_overrides)
    return merged


class BaseConfigConflict(ConfigError, ValueError):
    """Two files of a ``base_config`` graph that do not inherit each other disagree on a key.

    A ``ValueError`` too, as every other refusal of the merge is.
    """


GraphNode = tuple[Hashable, Mapping[str, Any], tuple[Hashable, ...]]
"""One file of a graph: its name, the document it writes without ``base_config``, its bases."""


def ancestors_of(bases: Mapping[Hashable, Sequence[Hashable]]) -> dict[Hashable, frozenset]:
    """Return, for each file, every file it inherits, directly or not.

    *bases* maps each file to the files it names in ``base_config``. The graph
    has no cycle: the reader of the files refuses one.
    """
    found: dict[Hashable, frozenset] = {}

    def visit(node: Hashable) -> frozenset:
        if node not in found:
            above: set[Hashable] = set()
            for base in bases.get(node, ()):
                above.add(base)
                above |= visit(base)
            found[node] = frozenset(above)
        return found[node]

    for node in bases:
        visit(node)
    return found


def merge_graph(
    nodes: Sequence[GraphNode], *, label: Callable[[Hashable], str] = str
) -> tuple[dict[str, Any], dict[str, tuple[Hashable, ...]]]:
    """Merge the files of a ``base_config`` graph, and say which file wrote each value.

    *nodes* lists each file once, every file after the files it inherits. The
    first return is the merged document. The second maps the dotted path of each
    value that is not a table to the files it comes from: the file that wrote it,
    then the files that added items with ``__append``. *label* names a file in a
    refusal.

    Raises
    ------
    BaseConfigConflict
        When two files that do not inherit from each other write one key with
        two values.
    ValueError
        On a directive the merge cannot apply, as :func:`merge_toml_payloads` does.
    """
    graph = _Graph(nodes, label)
    document = graph.table((), [(name, own) for name, own, _ in nodes])
    return copy.deepcopy(document), graph.origins


_ABSENT = object()
"""A key no remaining claim leaves in the document."""


@dataclass(frozen=True, slots=True)
class _Claim:
    """What one file says of one key, its ``__append`` folded in when it also sets the key.

    ``kind`` is ``table`` (merged key by key), ``fresh`` (a table written after
    ``__delete``, which drops what the file inherits there), ``value``,
    ``delete`` or ``merge`` (``__merge``, read against what the file inherits).
    """

    writer: Hashable
    kind: str
    value: Any = None
    cleared: bool = False
    then: tuple[Any, ...] = ()


def _claims_of(writer: Hashable, table: Mapping[str, Any]) -> tuple[dict, dict, list, list]:
    """Return the claims one file makes on the keys of one table, and its bare appends.

    The last two returns are the keys it removes, then the keys it writes, in the
    order :func:`_merge_two_payloads` places them, so a merged table keeps the
    order of keys a chain of files always gave it.
    """
    replace, append, delete, merge = _split_directive_keys(table)
    claims: dict[str, _Claim] = {key: _Claim(writer, "delete") for key in delete}
    for key, value in replace.items():
        if isinstance(value, Mapping):
            claims[key] = _Claim(writer, "fresh" if key in delete else "table", value)
        else:
            claims[key] = _Claim(writer, "value", list(value) if isinstance(value, list) else value)
    for key, items in merge.items():
        claims[key] = _Claim(writer, "merge", items, cleared=key in delete)
    appends: dict[str, list[Any]] = {}
    for key, items in append.items():
        claim = claims.get(key)
        if claim is None:
            appends[key] = list(items)
        elif claim.kind == "delete":
            claims[key] = _Claim(writer, "value", list(items))
        elif claim.kind == "merge":
            claims[key] = replaced(claim, then=tuple(items))
        elif claim.kind == "value" and isinstance(claim.value, list):
            claims[key] = _Claim(writer, "value", claim.value + list(items))
        else:
            found = "dict" if claim.kind in ("table", "fresh") else type(claim.value).__name__
            raise ValueError(f"cannot append to non-list value at key {key!r} (found {found})")
    return claims, appends, sorted(delete), [*replace, *merge, *append]


def _said(claim: _Claim) -> str:
    """What a claim says, short enough for a refusal."""
    if claim.kind in ("table", "fresh"):
        return "a table"
    if claim.kind == "delete":
        return "removed"
    if claim.kind == "merge":
        return "a list merged with __merge"
    text = repr(claim.value)
    return text if len(text) <= 60 else text[:57] + "..."


class _Graph:
    """The files of a graph, what each inherits, and the claims merged so far."""

    def __init__(self, nodes: Sequence[GraphNode], label: Callable[[Hashable], str]) -> None:
        self.nodes = list(nodes)
        self.label = label
        self.ancestors = ancestors_of({name: bases for name, _, bases in nodes})
        self.origins: dict[str, tuple[Hashable, ...]] = {}

    def _above(self, upper: Hashable, lower: Hashable) -> bool:
        """Whether *lower* inherits *upper*, directly or not."""
        return upper in self.ancestors.get(lower, ())

    def _dominates(self, other: _Claim, claim: _Claim) -> bool:
        """Whether *other* overrides *claim*: its file inherits the file of *claim*.

        A table merges with the tables it inherits, so it overrides them only when
        it was written fresh.
        """
        if not self._above(claim.writer, other.writer):
            return False
        return not (claim.kind in ("table", "fresh") and other.kind == "table")

    def table(self, path: tuple[str, ...], contributions: Sequence[tuple]) -> dict[str, Any]:
        """Merge the tables the files write at *path*, in the order of the files."""
        keys: dict[str, None] = {}
        claims: dict[str, list[_Claim]] = {}
        appends: dict[str, list[tuple[Hashable, list[Any]]]] = {}
        for writer, written in contributions:
            own, added, removed, placed = _claims_of(writer, written)
            for key, claim in own.items():
                claims.setdefault(key, []).append(claim)
            for key, items in added.items():
                appends.setdefault(key, []).append((writer, items))
            for key in removed:
                keys.pop(key, None)
            keys.update(dict.fromkeys(key for key in placed if key not in keys))
        # A key removed by one file and written by an earlier one of another branch.
        keys.update(dict.fromkeys(key for key in [*claims, *appends] if key not in keys))
        merged: dict[str, Any] = {}
        for key in keys:
            value = self._key((*path, key), claims.get(key, []), appends.get(key, []))
            if value is not _ABSENT:
                merged[key] = value
        return merged

    def _key(self, path: tuple[str, ...], claims: list[_Claim], appends: list[tuple]) -> Any:
        """The value of one key: the claims no other claim overrides, then the appends."""
        kept = [c for c in claims if not any(self._dominates(o, c) for o in claims if o is not c)]
        kinds = {claim.kind for claim in kept}
        if not kept or kinds == {"delete"}:
            base: Any = _ABSENT
        elif kinds <= {"table", "fresh"}:
            base = self.table(path, [(claim.writer, claim.value) for claim in kept])
        elif kinds & {"table", "fresh", "delete"}:
            raise self._conflict(path, kept)
        else:
            values = [self._value(path, claim) for claim in kept]
            if any(value != values[0] for value in values[1:]):
                raise self._conflict(path, kept)
            base = values[0]
        replacing = [claim.writer for claim in kept if claim.kind != "table"]
        added = [
            (writer, items)
            for writer, items in appends
            if not any(self._above(writer, other) for other in replacing)
        ]
        if added:
            if base is not _ABSENT and not isinstance(base, list):
                found = type(base).__name__
                raise ValueError(
                    f"cannot append to non-list value at key {path[-1]!r} (found {found})"
                )
            base = (list(base) if base is not _ABSENT else []) + [
                item for _, items in added for item in items
            ]
        if base is not _ABSENT and not isinstance(base, dict):
            writers = [claim.writer for claim in kept] + [writer for writer, _ in added]
            self.origins[".".join(path)] = tuple(dict.fromkeys(writers))
        return base

    def _value(self, path: tuple[str, ...], claim: _Claim) -> Any:
        """The value of a claim that is not a table: as written, or merged by ``__merge``."""
        if claim.kind != "merge":
            return claim.value
        inherited = None if claim.cleared else self._inherited(path, claim.writer)
        merged = _merge_tables_by_identity(path[-1], inherited, list(claim.value))
        return merged + list(claim.then)

    def _inherited(self, path: tuple[str, ...], writer: Hashable) -> Any:
        """The value *writer* inherits at *path*: the graph of its ancestors, merged."""
        above = self.ancestors.get(writer, frozenset())
        nodes = [node for node in self.nodes if node[0] in above]
        value: Any = _Graph(nodes, self.label).table((), [(name, own) for name, own, _ in nodes])
        for key in path:
            if not isinstance(value, Mapping) or key not in value:
                return None
            value = value[key]
        return value

    def _conflict(self, path: tuple[str, ...], kept: list[_Claim]) -> BaseConfigConflict:
        """The refusal of a key two files that do not inherit each other disagree on."""
        said = " and by ".join(f"{self.label(claim.writer)} ({_said(claim)})" for claim in kept)
        return BaseConfigConflict(
            f"{'.'.join(path)} is written by {said}, and neither file inherits from the "
            "other. Write the key in a file that inherits from both, or in one of them only."
        )


__all__ = [
    "DIRECTIVE_SUFFIXES",
    "IDENTITY_KEYS",
    "BaseConfigConflict",
    "GraphNode",
    "ancestors_of",
    "merge_graph",
    "merge_toml_payloads",
]
