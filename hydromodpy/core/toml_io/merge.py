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
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

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


__all__ = ["DIRECTIVE_SUFFIXES", "IDENTITY_KEYS", "merge_toml_payloads"]
