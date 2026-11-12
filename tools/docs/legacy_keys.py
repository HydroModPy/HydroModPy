"""Which old TOML keys a file may still write, read from the register of changes.

The changes page lists every key a field replaces. Whether a file that writes the
old name loads is a fact about the loader, so it is read from the same rows the loader
applies and not written by hand:

- ``migrates``: a ``move`` row of ``document = "config"`` in
  ``hydromodpy/schema/changes.toml``, still inside its delay. A load reads the key under
  its new name with ``ConfigKeyRenamedWarning``, and ``hmp doctor --fix-config``
  rewrites the file. The dotted override of a calibration phase moves with it.
- refused as a pre-release form: a key listed in ``hydromodpy/config/prerelease_forms.txt``.
  Only a pre-release of 2.0 wrote it, so this version refuses it with a sentence that names the
  current name of the key (:func:`prerelease_paths`).

A rename in neither group is refused (``extra="forbid"``).
"""

from __future__ import annotations

from hydromodpy.config.config_migration import PRERELEASE_FORMS, document_path
from hydromodpy.core.version import __version__
from hydromodpy.schema.changes import REGISTER, Register, migrations_of, outlived

MIGRATES = "migrates"


def moved_tables(register: Register = REGISTER) -> dict[str, str]:
    """Old path -> new path, for each key or table a ``move`` row moves whole."""
    return {
        document_path(str(row.old)): document_path(str(row.new))
        for row in migrations_of("config", register)
        if row.shape == "move"
    }


def accepted_old_names(register: Register = REGISTER) -> dict[str, str]:
    """Old path -> ``migrates`` for each old key a live file may still write.

    A ``move`` row past its delay is refused with the new name, so it is left out. An
    old path that is absent from the result is refused by the loader.
    """
    return {
        document_path(str(row.old)): MIGRATES
        for row in migrations_of("config", register)
        if row.shape == "move" and not outlived(row.since, __version__)
    }


def prerelease_paths() -> frozenset[str]:
    """The keys only a pre-release of 2.0 wrote, which this version refuses, as the docs write a path.

    A form that refuses a value of a key that still exists is not a removed key, so it
    is left out.
    """
    return frozenset(document_path(form.path) for form in PRERELEASE_FORMS if not form.has_value)
