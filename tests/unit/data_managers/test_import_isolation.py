from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from contextlib import contextmanager


def _purge_modules(*prefixes: str) -> None:
    for name in list(sys.modules):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes):
            sys.modules.pop(name, None)


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


def test_hydromodpy_config_import_does_not_eagerly_load_sql_catalog() -> None:
    with _isolated_module_state(
        "hydromodpy.config.hydromodpy_config",
        "hydromodpy.data",
    ):
        importlib.import_module("hydromodpy.config.hydromodpy_config")

        assert "hydromodpy.data.registry.catalog" not in sys.modules
