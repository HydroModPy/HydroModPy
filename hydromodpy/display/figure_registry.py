"""Registry of named figures.

The figure registry resolves a figure name to its implementation class.
Built-in figures are listed in the generated :mod:`hydromodpy.display.figure_table`
and loaded on first lookup via :class:`~hydromodpy.core.plugin_registry.PluginRegistry`.
"""

from __future__ import annotations

import warnings
from typing import Any

from hydromodpy.core.plugin_registry import PluginRegistry
from hydromodpy.display.figure import (
    BaseFigure,
    FigureSpec,
    option_names_of,
    option_types_of,
    options_of,
)
from hydromodpy.display.figure_table import (
    FIGURES,
    FORMER_NAMES,
    OPTIONS,
    PYTHON_ONLY_OPTIONS,
)


def _figure_members() -> tuple[str, ...]:
    return ("name", "spec", "render", "plot")


figures = PluginRegistry(
    kind="figure",
    id_attributes=("name",),
    group=None,
    builtin_paths=dict(FIGURES),
    members=_figure_members,
    error=KeyError,
)
"""The figure registry: ``figures.get``, ``names`` and ``register``."""


def resolve(name: str) -> str:
    """Return the current name of a registered figure.

    A name a figure used to carry still resolves, and warns with both spellings
    so a reader learns what to write. An unknown name is refused as before.
    """
    if name in FORMER_NAMES:
        current = FORMER_NAMES[name]
        warnings.warn(
            f"figure '{name}' is now called '{current}'; the old name still resolves "
            "and will stop being read in a later version.",
            DeprecationWarning,
            stacklevel=2,
        )
        return current
    if name in FIGURES or name in figures.classes:
        return name
    available = ", ".join(sorted(set(FIGURES) | set(figures.classes))) or "<empty>"
    raise KeyError(f"unknown figure '{name}' (registered: {available})")


def get(name: str) -> BaseFigure:
    """Return a fresh instance of the registered figure ``name``."""
    return figures.get(resolve(name))()


def list_figures() -> list[FigureSpec]:
    """Return the list of all registered figure specs, sorted by name."""
    return [figures.get(name).spec for name in figures.names()]


def names() -> tuple[str, ...]:
    """Iterate over the names of registered figures."""
    return figures.names()


def figure_option_names(name: str) -> frozenset[str]:
    """Return the keys ``[display.overrides.<name>]`` accepts.

    They are the named parameters of the figure's ``plot`` and ``render``,
    read along the MRO while a ``**`` parameter forwards them.
    """
    target = resolve(name)
    if target in OPTIONS:
        return frozenset(OPTIONS[target])
    return option_names_of(figures.get(target))


def figure_option_types(name: str) -> dict[str, Any]:
    """Return the declared type of every option of the figure ``name``.

    See :func:`hydromodpy.display.figure.option_types_of`.
    """
    return option_types_of(figures.get(resolve(name)))


def figure_python_only_options(name: str) -> frozenset[str]:
    """Return the options of ``name`` that take a Python object, such as another run."""
    target = resolve(name)
    if target in PYTHON_ONLY_OPTIONS:
        return frozenset(PYTHON_ONLY_OPTIONS[target])
    if target in FIGURES:
        return frozenset()
    cls = figures.get(target)
    return frozenset(option.name for option in options_of(cls) if option.python_only)
