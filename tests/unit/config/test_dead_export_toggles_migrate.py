"""The first two shapes of ``[export]`` still load, as ``[[export]]`` requests.

``head``, ``concentration`` and ``derived`` used to be booleans under
``[export.variables]``; ``budget`` and ``pathlines`` gated nothing and were
already dead. ``export.times`` became ``export.time``. Then the whole table of
format toggles became an array of requests. ``extra="forbid"`` refuses a file
that still carries an old shape, so the migration is what carries those files
across, one shape after the other.
"""

from __future__ import annotations

import tomlkit

from hydromodpy.config.config_migration import migrate_config_doc


def _doc(text: str) -> tomlkit.TOMLDocument:
    return tomlkit.parse(text)


def _requests(doc: tomlkit.TOMLDocument) -> list[dict]:
    return [dict(block) for block in doc["export"].unwrap()]


def test_the_boolean_table_becomes_the_variables_of_each_request() -> None:
    doc = _doc(
        "[export]\ngeotiff = true\n[export.variables]\nhead = true\nbudget = false\n"
        "pathlines = false\nderived = true\n"
    )

    changes = migrate_config_doc(doc)

    (request,) = _requests(doc)
    assert set(request["variables"]) == {
        "head",
        "watertable_elevation",
        "watertable_depth",
        "seepage_mask",
    }
    assert any("boolean table" in line for line in changes)


def test_concentration_is_carried_over() -> None:
    doc = _doc("[export]\nnetcdf = true\n[export.variables]\nhead = false\nconcentration = true\n")

    migrate_config_doc(doc)

    assert _requests(doc)[0]["variables"] == ["concentration"]


def test_a_file_already_using_requests_is_left_alone() -> None:
    doc = _doc('[[export]]\nvariables = ["head", "watertable_depth"]\n')

    assert migrate_config_doc(doc) == []


def test_the_buried_export_table_is_migrated_too() -> None:
    """``[simulation.results.export]`` is promoted, so it carries the keys too."""
    doc = _doc(
        "[simulation.results.export]\nvtu = true\n"
        "[simulation.results.export.variables]\nhead = true\nbudget = false\n"
    )

    migrate_config_doc(doc)

    assert _requests(doc) == [{"variables": ["head"], "format": "vtu", "time": "last"}]


def test_export_times_is_renamed_to_time() -> None:
    doc = _doc("[export]\ngeotiff = true\ntimes = 33\n")

    changes = migrate_config_doc(doc)

    assert _requests(doc)[0]["time"] == 33
    assert any("export.times -> export.time" in line for line in changes)


def test_export_times_is_dropped_when_time_already_set() -> None:
    doc = _doc('[export]\ngeotiff = true\ntimes = 33\ntime = "last"\n')

    changes = migrate_config_doc(doc)

    assert _requests(doc)[0]["time"] == "last"
    assert any("already set" in line for line in changes)


def test_the_rewritten_file_writes_an_array_of_tables() -> None:
    doc = _doc('[export]\ngeotiff = true\ncsv_timeseries = true\n\n[display]\ncmap = "magma"\n')

    migrate_config_doc(doc)

    text = tomlkit.dumps(doc)
    assert text.count("[[export]]") == 2
    assert "[display]" in text
