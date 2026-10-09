"""TOML payload merge helpers.

Tables merge key by key. Any other value in an overlay replaces the base
value. This holds for lists too, lists of tables included: a list in the
overlay replaces the inherited list whole, whatever their lengths.

Three suffixes change that rule for one key:

- ``<key>__append = [...]`` adds the items after the inherited ones;
- ``<key>__delete = true`` removes the inherited key or table;
- ``<key>__merge = [...]`` merges a list of tables with the inherited list
  table by table, in order. Both lists must have the same length.

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


def _merge_tables_in_order(key: str, existing: Any, items: list[Any]) -> list[Any]:
    """Merge a list of tables with the inherited one, table by table."""
    directive = key + _MERGE_SUFFIX
    if existing is None:
        raise ValueError(f"merge directive {directive!r} has no inherited list to merge with")
    if not isinstance(existing, list) or not all(isinstance(item, Mapping) for item in existing):
        raise ValueError(
            f"merge directive {directive!r} needs an inherited list of tables "
            f"(found {type(existing).__name__})"
        )
    if len(existing) != len(items):
        raise ValueError(
            f"merge directive {directive!r} has {len(items)} table(s) and the inherited "
            f"list has {len(existing)}; write one table per inherited table, or replace "
            f"the list with {key!r}"
        )
    return [
        _merge_two_payloads(base_item, override_item)
        for base_item, override_item in zip(existing, items, strict=True)
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
        merged[key] = _merge_tables_in_order(key, merged.get(key), items)

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

    Precedence is ``defaults < base_chain < overlays < CLI < env``.
    Passing a mapping as ``base_chain`` keeps the legacy two-argument
    ``merge_toml_payloads(base, override)`` call shape.
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


__all__ = ["DIRECTIVE_SUFFIXES", "merge_toml_payloads"]
