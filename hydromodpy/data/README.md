# `hydromodpy/data`

Everything a run reads from outside: provider APIs, user files, their cache
and the typed records handed to the layers above.

The map of the package is [`structure.md`](structure.md): what each
subpackage answers, the import rules, the template of a variable, how data
flows during a run and from an external request, and where to add what.

The import rules are enforced by `tests/unit/architecture/test_data_layout.py`
against `tests/unit/architecture/data_layout.yaml`.
