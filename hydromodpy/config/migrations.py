"""Payload-level migrations between TOML schema versions.

The current TOML payload format is implicitly versioned: the public
contract is the ``HydroModPyConfig`` Pydantic model whose JSON Schema
companion (``config.json``) is fingerprinted via ``schema_sha256``.

This module declares the API used by the loader to upgrade older
payloads in-place before model validation. Today only the identity
migration is registered (v1 -> v1). A breaking schema change will
register a real ``v_from -> v_to`` step here without touching the
loader call-sites.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

PayloadMigration = Callable[[dict[str, Any]], dict[str, Any]]


def _identity(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload)


CURRENT_SCHEMA_VERSION: int = 1

_MIGRATIONS: dict[tuple[int, int], PayloadMigration] = {
    (1, 1): _identity,
}


def migrate_payload(payload: dict[str, Any], v_from: int, v_to: int) -> dict[str, Any]:
    """Apply the chain of payload migrations from *v_from* to *v_to*.

    Parameters
    ----------
    payload
        Raw TOML payload (after ``load_toml_with_base_config``) to
        upgrade.
    v_from
        Declared payload schema version.
    v_to
        Target schema version (usually ``CURRENT_SCHEMA_VERSION``).

    Returns
    -------
    dict[str, Any]
        Upgraded payload. The input is not modified.
    """
    if v_from == v_to:
        return _identity(payload)
    if v_from > v_to:
        raise ValueError(
            f"Downgrade not supported (schema {v_from} -> {v_to}). "
            "Regenerate the payload from a newer source."
        )
    current = dict(payload)
    step_from = v_from
    while step_from < v_to:
        step_to = step_from + 1
        try:
            migration = _MIGRATIONS[(step_from, step_to)]
        except KeyError as exc:
            raise ValueError(
                f"No payload migration registered for schema {step_from} -> {step_to}"
            ) from exc
        current = migration(current)
        step_from = step_to
    return current


__all__ = ["CURRENT_SCHEMA_VERSION", "PayloadMigration", "migrate_payload"]
