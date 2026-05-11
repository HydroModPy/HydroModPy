"""TOML payload merge helpers.

Lists in TOML overlays replace the base value by default. To append instead,
use the ``<key>__append`` suffix in the overlay::

    [base]
    process = ["A", "B"]

    # overlay
    [base]
    process__append = ["C"]
    # result: process = ["A", "B", "C"]

The suffix is stripped during merge and never appears in the validated
:class:`HydroModPyConfig` payload.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_APPEND_SUFFIX = "__append"


def _split_append_keys(payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """Separate plain-replace entries from ``<name>__append`` directives."""
    replace: dict[str, Any] = {}
    append: dict[str, list[Any]] = {}
    for key, value in payload.items():
        if key.endswith(_APPEND_SUFFIX):
            target = key[: -len(_APPEND_SUFFIX)]
            if not target:
                raise ValueError(f"empty target key for append directive {key!r}")
            if not isinstance(value, list):
                raise ValueError(
                    f"merge directive {key!r} requires a list value, got {type(value).__name__}"
                )
            append[target] = list(value)
        else:
            replace[key] = value
    return replace, append


def _merge_two_payloads(
    base: Mapping[str, Any],
    override: Mapping[str, Any],
) -> dict[str, Any]:
    """Recursively merge one TOML override into one base payload."""
    replace, append = _split_append_keys(override)
    merged: dict[str, Any] = dict(base)

    for key, value in replace.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _merge_two_payloads(existing, value)
        elif (
            isinstance(existing, list)
            and isinstance(value, list)
            and len(existing) == len(value)
            and all(isinstance(item, Mapping) for item in existing)
            and all(isinstance(item, Mapping) for item in value)
        ):
            merged[key] = [
                _merge_two_payloads(base_item, override_item)
                for base_item, override_item in zip(existing, value, strict=True)
            ]
        elif isinstance(value, list):
            merged[key] = list(value)
        else:
            merged[key] = value

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


__all__ = ["merge_toml_payloads"]
