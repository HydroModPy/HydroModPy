"""A key removed from the schema has to leave the files that still carry it.

``export.variables.budget`` and ``export.variables.pathlines`` gated nothing and
were removed. ``extra="forbid"`` turns their removal into a hard refusal, so a
project written before the removal stops loading entirely on two toggles that
never did anything. The migration is what carries those files across.
"""

from __future__ import annotations

import tomlkit

from hydromodpy.config.config_migration import migrate_config_doc


def _doc(text: str) -> tomlkit.TOMLDocument:
    return tomlkit.parse(text)


def test_the_dead_toggles_are_dropped() -> None:
    doc = _doc(
        "[export.variables]\nhead = true\nbudget = false\npathlines = false\nderived = true\n"
    )

    changes = migrate_config_doc(doc)

    assert set(doc["export"]["variables"]) == {"head", "derived"}
    assert any("budget" in line for line in changes)
    assert any("pathlines" in line for line in changes)


def test_a_file_without_them_is_left_alone() -> None:
    doc = _doc("[export.variables]\nhead = true\nderived = true\n")

    assert migrate_config_doc(doc) == []


def test_the_buried_export_table_is_migrated_too() -> None:
    """``[simulation.results.export]`` is promoted, so it carries the keys too."""
    doc = _doc("[simulation.results.export.variables]\nhead = true\nbudget = false\n")

    migrate_config_doc(doc)

    assert set(doc["export"]["variables"]) == {"head"}
