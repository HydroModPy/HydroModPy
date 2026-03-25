"""Hydrological model utilities and conceptual forcing builders."""

from importlib import import_module

from . import synthetic


def __getattr__(name):
    if name == "pyhelp":
        module = import_module("hydromodpy.process.hydrology.pyhelp")
        globals()["pyhelp"] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["synthetic", "pyhelp"]
