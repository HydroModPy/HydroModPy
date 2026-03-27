"""Compatibility wrapper for :mod:`hydromodpy.core.config`."""

from importlib import import_module as _import_module

_target = _import_module("hydromodpy.core.config")
__all__ = getattr(_target, "__all__", [])
__doc__ = _target.__doc__
__path__ = getattr(_target, "__path__", [])


def __getattr__(name: str):
    return getattr(_target, name)


def __dir__():
    return sorted(set(globals()) | set(dir(_target)))
