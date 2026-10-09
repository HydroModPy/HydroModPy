"""Which renamed TOML keys the loader still reads, from the code of the loader.

The changes page lists every key a field replaces (``renamed_from``). Whether a
file that writes the old name is refused is a fact about the loader, so it is
read there and not written by hand:

- ``warns``: the model lists the old spelling in ``model_legacy_keys``. The key
  is renamed on load and ``ConfigKeyRenamedWarning`` names the new one.
- ``migrates``: the old ``[export]`` tables, which ``config_migration`` rewrites
  into ``[[export]]`` blocks in memory on load.

A rename in neither group is refused (``extra="forbid"``).
"""

from __future__ import annotations

from typing import Any

WARNS = "warns"
MIGRATES = "migrates"


def _parent(path: str) -> str:
    return path.rsplit(".", 1)[0] if "." in path else ""


def _leaf(path: str) -> str:
    return path.rsplit(".", 1)[-1]


def _models_named(name: str) -> list[type]:
    """Every config model class with this name, found from the base class."""
    from hydromodpy.core.config_kit.base import HydroModelBase

    found, todo = [], [HydroModelBase]
    while todo:
        cls = todo.pop()
        if cls.__name__ == name:
            found.append(cls)
        todo.extend(cls.__subclasses__())
    return found


def accepted_old_names(nodes: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Old path -> ``warns`` or ``migrates`` for each renamed key the loader still reads.

    ``nodes`` is the ``nodes`` mapping of the field registry. An old path that is
    absent from the result is refused by the loader.
    """
    from hydromodpy.config import config_migration

    accepted: dict[str, str] = {}
    for path, node in nodes.items():
        for old in node.get("renamed_from") or []:
            if _parent(old) == _parent(path):
                for model in _models_named(node.get("model", "")):
                    if model.model_legacy_keys.get(_leaf(old)) == _leaf(path):
                        accepted[old] = WARNS
            elif path == "export" and old.startswith("export."):
                if _leaf(old) in config_migration._EXPORT_TABLE_KEYS:
                    accepted[old] = MIGRATES
    return accepted
