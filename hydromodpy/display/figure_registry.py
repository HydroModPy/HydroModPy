"""Registry of named figures.

Each figure class registers itself by decorating with :func:`register`. The
registry is consumed by ``hmp viz`` and by the comparison helpers.
"""

from __future__ import annotations

import importlib
import warnings
from collections.abc import Iterable

from hydromodpy.display.figure import BaseFigure, FigureSpec

_REGISTRY: dict[str, type[BaseFigure]] = {}
_FORMER_NAMES: dict[str, str] = {}
_FIGURES_REGISTERED = False


def _ensure_figures_registered() -> None:
    global _FIGURES_REGISTERED
    if _FIGURES_REGISTERED:
        return
    importlib.import_module("hydromodpy.display.figures")
    _FIGURES_REGISTERED = True


def register(cls: type[BaseFigure]) -> type[BaseFigure]:
    """Class decorator. Registers ``cls`` under ``cls.spec.name``."""
    name = cls.spec.name
    if name in _REGISTRY and _REGISTRY[name] is not cls:
        raise ValueError(f"figure '{name}' is already registered to {_REGISTRY[name]!r}")
    _REGISTRY[name] = cls
    for former in cls.spec.former_names:
        held = _FORMER_NAMES.get(former)
        if held is not None and held != name:
            raise ValueError(f"figure '{former}' is already the former name of '{held}'")
        _FORMER_NAMES[former] = name
    return cls


def resolve(name: str) -> str:
    """Return the current name of a registered figure.

    A name a figure used to carry still resolves, and warns with both spellings
    so a reader learns what to write. An unknown name is refused as before.
    """
    _ensure_figures_registered()
    if name in _REGISTRY:
        return name
    current = _FORMER_NAMES.get(name)
    if current is not None:
        warnings.warn(
            f"figure '{name}' is now called '{current}'; the old name still resolves "
            "and will stop being read in a later version.",
            DeprecationWarning,
            stacklevel=2,
        )
        return current
    available = ", ".join(sorted(_REGISTRY)) or "<empty>"
    raise KeyError(f"unknown figure '{name}' (registered: {available})")


def get(name: str) -> BaseFigure:
    """Return a fresh instance of the registered figure ``name``."""
    return _REGISTRY[resolve(name)]()


def list_figures() -> list[FigureSpec]:
    """Return the list of all registered figure specs, sorted by name."""
    _ensure_figures_registered()
    return [cls.spec for _, cls in sorted(_REGISTRY.items())]


def names() -> Iterable[str]:
    """Iterate over the names of registered figures."""
    _ensure_figures_registered()
    return sorted(_REGISTRY)
