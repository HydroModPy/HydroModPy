"""Unit parsing and formatting helpers.

Lazy facade. Lightweight imports such as ``hydromodpy.core.units.labels``
do not require loading the full Pint stack.
"""

from __future__ import annotations

from importlib import import_module

from hydromodpy.core.units._lazy import LAZY_IMPORTS

__all__ = list(LAZY_IMPORTS.keys())


def __getattr__(name: str):
    try:
        target = LAZY_IMPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    module_path, attr_name = target.split(":", 1)
    module = import_module(module_path)
    attr = getattr(module, attr_name)
    globals()[name] = attr
    return attr
