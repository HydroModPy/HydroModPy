"""Registry of named figures.

Each figure class registers itself by decorating with :func:`register`. The
registry is consumed by ``hmp display`` and by the comparison helpers.
"""

from __future__ import annotations

from typing import Iterable

from hydromodpy.display.figure import BaseFigure, FigureSpec

_REGISTRY: dict[str, type[BaseFigure]] = {}


def register(cls: type[BaseFigure]) -> type[BaseFigure]:
    """Class decorator. Registers ``cls`` under ``cls.spec.name``."""
    name = cls.spec.name
    if name in _REGISTRY and _REGISTRY[name] is not cls:
        raise ValueError(f"figure '{name}' is already registered to {_REGISTRY[name]!r}")
    _REGISTRY[name] = cls
    return cls


def get(name: str) -> BaseFigure:
    """Return a fresh instance of the registered figure ``name``."""
    try:
        cls = _REGISTRY[name]
    except KeyError as exc:
        available = ", ".join(sorted(_REGISTRY)) or "<empty>"
        raise KeyError(f"unknown figure '{name}' (registered: {available})") from exc
    return cls()


def list_figures() -> list[FigureSpec]:
    """Return the list of all registered figure specs, sorted by name."""
    return [cls.spec for _, cls in sorted(_REGISTRY.items())]


def names() -> Iterable[str]:
    """Iterate over the names of registered figures."""
    return sorted(_REGISTRY)
