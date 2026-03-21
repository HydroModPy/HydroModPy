from __future__ import annotations

import importlib
import sys


def _purge_modules(*prefixes: str) -> None:
    for name in list(sys.modules):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes):
            sys.modules.pop(name, None)


def test_hydromodpy_config_import_does_not_eagerly_load_sql_catalog() -> None:
    _purge_modules(
        "hydromodpy.config.hydromodpy_config",
        "hydromodpy.data_managers",
    )

    importlib.import_module("hydromodpy.config.hydromodpy_config")

    assert "hydromodpy.data_managers.registry.catalog" not in sys.modules
