"""Generate the figure-catalog inventory shown in the user guide.

The figure catalog is a thin wrapper over ``hydromodpy.display.list_figures``:
this module introspects the registry and writes a partial RST file consumed
by ``docs/source/user_guide/figures.rst`` via ``.. include::``.

The Sphinx ``conf.py`` calls :func:`generate` on the ``builder-inited`` event,
so the catalog is always in sync with the registered figures.
"""

from __future__ import annotations

from tools.doc_figures.generate import generate

__all__ = ["generate"]
