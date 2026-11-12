"""What a config import may not drag in, and how the isolation is undone.

The restore half of this file is load-bearing for tests that never read it.
Purging ``sys.modules`` and putting the snapshot back is not enough: a
submodule re-imported inside the block rebinds itself onto its **parent
package** as an attribute, and ``from a.b import c`` reads that attribute, not
``sys.modules["a.b.c"]``. Leaving the parent pointing at the throwaway module
made every later ``monkeypatch.setattr("a.b.c.d", ...)`` patch one object while
the code under test imported another -- silently, and only when this file ran
first. Two tests in ``tests/unit/data/variables/hydrography/test_hydrography_resolver.py`` failed
exactly that way whenever the suite was invoked with the families tests ahead of
``data``.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager


def _purge_modules(*prefixes: str) -> None:
    for name in list(sys.modules):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes):
            sys.modules.pop(name, None)


def _rebind_on_parents(snapshot: Mapping[str, object]) -> None:
    """Put each restored module back on its parent package as an attribute."""
    for name, module in snapshot.items():
        parent_name, _, child = name.rpartition(".")
        if not child:
            continue
        parent = sys.modules.get(parent_name)
        if parent is not None:
            setattr(parent, child, module)


@contextmanager
def _isolated_module_state(*prefixes: str) -> Iterator[None]:
    """Temporarily purge module prefixes and restore the original state afterwards."""
    snapshot = {
        name: module
        for name, module in sys.modules.items()
        if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)
    }
    _purge_modules(*prefixes)
    try:
        yield
    finally:
        _purge_modules(*prefixes)
        sys.modules.update(snapshot)
        _rebind_on_parents(snapshot)


def test_a_variable_config_loads_no_variable_module() -> None:
    """Validating a [data] section must not load a single ``variable`` module."""
    with _isolated_module_state("hydromodpy.config.hydromodpy_config", "hydromodpy.data"):
        importlib.import_module("hydromodpy.config.hydromodpy_config")
        loaded = sorted(name for name in sys.modules if name.endswith(".variable"))

    assert [name for name in loaded if name.startswith("hydromodpy.data.")] == []
