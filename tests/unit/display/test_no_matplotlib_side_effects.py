"""Importing :mod:`hydromodpy.display` must not touch matplotlib rcParams.

Figures may call :func:`apply_theme` *when requested* but the package
import itself must stay inert so that a user's interactive session does
not get its styling silently rewritten.
"""

from __future__ import annotations

import importlib
import sys


def test_display_import_does_not_mutate_rcparams() -> None:
    import matplotlib

    before = dict(matplotlib.rcParams)
    display_modules = {
        name: module
        for name, module in sys.modules.items()
        if name.startswith("hydromodpy.display")
    }

    try:
        # Force a fresh import to exercise the module-level code paths.
        for mod in list(sys.modules):
            if mod.startswith("hydromodpy.display"):
                del sys.modules[mod]
        importlib.import_module("hydromodpy.display")
    finally:
        for mod in list(sys.modules):
            if mod.startswith("hydromodpy.display"):
                del sys.modules[mod]
        sys.modules.update(display_modules)

    after = dict(matplotlib.rcParams)
    changed = {k: (before.get(k), after.get(k)) for k in after if before.get(k) != after.get(k)}
    assert not changed, (
        f"importing hydromodpy.display mutated rcParams: {changed}. "
        "Figures must opt-in via apply_theme; imports must be inert."
    )
