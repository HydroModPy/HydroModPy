"""One-shot TOML config migration for the simulation-management refactor.

Rewrites legacy ``[simulation]`` keys in place, preserving comments and layout:

- ``on_collision`` -> ``if_exists``
- ``run_id`` -> ``name`` (when ``name`` is not already set)
- ``[simulation.results.export]`` -> top-level ``[export]``

This is a migration tool, not a backward-compat shim: it changes a file on disk
once. The runtime itself never accepts the old keys (``extra="forbid"``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tomlkit


def fix_config_file(path: str | Path) -> list[str]:
    """Rewrite legacy ``[simulation]`` keys in ``path`` in place.

    Returns the list of human-readable changes applied (empty when the file is
    already up to date). Raises :class:`FileNotFoundError` when the path is
    missing and :class:`tomlkit.exceptions.ParseError` on malformed TOML.
    """
    path = Path(path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"No TOML file at {path}")

    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    simulation = doc.get("simulation")
    if simulation is None:
        return []

    changes: list[str] = []

    if "on_collision" in simulation:
        value = simulation["on_collision"]
        if "if_exists" not in simulation:
            simulation["if_exists"] = value
        del simulation["on_collision"]
        changes.append(f"simulation.on_collision -> if_exists ({value!r})")

    if "run_id" in simulation:
        value = simulation["run_id"]
        if not simulation.get("name"):
            simulation["name"] = value
            changes.append(f"simulation.run_id -> name ({value!r})")
        else:
            changes.append("simulation.run_id dropped (name already set)")
        del simulation["run_id"]

    changes.extend(_promote_export(doc, simulation))

    if changes:
        path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return changes


def _promote_export(doc: Any, simulation: Any) -> list[str]:
    """Move ``[simulation.results.export]`` to the top-level ``[export]`` table."""
    results = simulation.get("results")
    if results is None or "export" not in results:
        return []
    if "export" in doc:
        # A top-level [export] already exists: drop the buried duplicate.
        del results["export"]
        return ["simulation.results.export dropped (top-level [export] already set)"]
    payload = results["export"].unwrap()
    table = tomlkit.item(payload)
    doc["export"] = table
    del results["export"]
    return ["simulation.results.export -> [export]"]


__all__ = ["fix_config_file"]
