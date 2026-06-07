"""Shared helpers for the data_managers package."""

from __future__ import annotations

from importlib import import_module
from importlib.util import find_spec

__all__ = ("administrative",)


def __getattr__(name: str):
    module_name = f"{__name__}.{name}"
    if find_spec(module_name) is not None:
        module = import_module(module_name)
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
