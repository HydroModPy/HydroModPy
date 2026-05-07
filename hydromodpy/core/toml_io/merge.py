"""TOML payload merge helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _merge_two_payloads(
    base: Mapping[str, Any],
    override: Mapping[str, Any],
) -> dict[str, Any]:
    """Recursively merge one TOML override into one base payload."""
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
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
