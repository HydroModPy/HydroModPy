"""Verify that entry points in pyproject.toml only name hydromodpy_annex modules.

The wheel carries no entry point to internal code, so that components are declared
once in their registries. The only entry points declared in pyproject.toml are for
the out-of-tree annex, which joins through plugin groups.
"""

from __future__ import annotations

import importlib
import pathlib
import sys
import tomllib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _entry_point_tables() -> dict[str, dict[str, str]]:
    pyproject_path = REPO_ROOT / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    return data.get("project", {}).get("entry-points", {})


def test_entry_points_only_target_annex() -> None:
    """Ensure every entry point declared in pyproject.toml targets hydromodpy_annex."""
    tables = _entry_point_tables()
    assert tables, "pyproject.toml should declare [project.entry-points]"

    for group, entries in tables.items():
        assert entries, f"Entry-point group {group!r} is empty"
        for name, target in entries.items():
            module_name, _, attr_name = target.partition(":")
            assert module_name.startswith("hydromodpy_annex."), (
                f"Entry point {name!r} in group {group!r} targets {target!r}, "
                "which is not under hydromodpy_annex."
            )
            assert attr_name, (
                f"Entry point {name!r} in group {group!r} lacks an attribute: {target!r}"
            )


def test_annex_entry_points_import_with_repo_on_sys_path() -> None:
    """Ensure every annex entry point can be imported when the repository root is on sys.path."""
    tables = _entry_point_tables()
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    for _group, entries in tables.items():
        for name, target in entries.items():
            module_name, _, attr_name = target.partition(":")
            mod = importlib.import_module(module_name)
            cls = getattr(mod, attr_name)
            assert isinstance(cls, type), f"{target!r} should resolve to a class"
            assert getattr(cls, "name", None) == name, (
                f"Class {cls} declares name {getattr(cls, 'name', None)!r}, expected {name!r}"
            )
