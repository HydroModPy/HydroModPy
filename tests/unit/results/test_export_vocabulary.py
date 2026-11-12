"""One namespace for every name a user can export, each with its kind."""

from __future__ import annotations

from hydromodpy.results import field_registry
from hydromodpy.results.exporters.export_spec import ExportKind
from hydromodpy.results.exporters.vocabulary import static_export_names


def test_every_registered_field_is_exportable() -> None:
    names = static_export_names()
    assert all(names[name] is ExportKind.field for name in field_registry.all_names())
