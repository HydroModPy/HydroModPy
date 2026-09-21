"""``[export.variables]`` moved from a boolean submodel to a flat list.

``head``, ``concentration`` and ``derived`` used to be booleans under
``[export.variables]``; ``budget`` and ``pathlines`` gated nothing and were
already dead. ``extra="forbid"`` refuses a file that still carries the old
table, so a project written before the flattening stops loading entirely. The
migration is what carries those files across.
"""

from __future__ import annotations

import tomlkit

from hydromodpy.config.config_migration import migrate_config_doc


def _doc(text: str) -> tomlkit.TOMLDocument:
    return tomlkit.parse(text)


def test_the_boolean_table_becomes_a_list() -> None:
    doc = _doc(
        "[export.variables]\nhead = true\nbudget = false\npathlines = false\nderived = true\n"
    )

    changes = migrate_config_doc(doc)

    assert set(doc["export"]["variables"]) == {
        "head",
        "watertable_elevation",
        "watertable_depth",
        "seepage_mask",
    }
    assert any("boolean table" in line for line in changes)


def test_concentration_is_carried_over() -> None:
    doc = _doc("[export.variables]\nhead = false\nconcentration = true\n")

    migrate_config_doc(doc)

    assert list(doc["export"]["variables"]) == ["concentration"]


def test_a_file_already_using_the_list_is_left_alone() -> None:
    doc = _doc('[export]\nvariables = ["head", "derived"]\n')

    assert migrate_config_doc(doc) == []


def test_the_buried_export_table_is_migrated_too() -> None:
    """``[simulation.results.export]`` is promoted, so it carries the keys too."""
    doc = _doc("[simulation.results.export.variables]\nhead = true\nbudget = false\n")

    migrate_config_doc(doc)

    assert list(doc["export"]["variables"]) == ["head"]


def test_export_times_is_renamed_to_time() -> None:
    doc = _doc("[export]\ntimes = 33\n")

    changes = migrate_config_doc(doc)

    assert doc["export"]["time"] == 33
    assert "times" not in doc["export"]
    assert any("export.times -> export.time" in line for line in changes)


def test_export_times_is_dropped_when_time_already_set() -> None:
    doc = _doc('[export]\ntimes = 33\ntime = "last"\n')

    changes = migrate_config_doc(doc)

    assert doc["export"]["time"] == "last"
    assert "times" not in doc["export"]
    assert any("already set" in line for line in changes)
