"""Figure implementations.

Importing this package triggers registration of every figure class. Add a new
figure by dropping a file in this directory that imports
:func:`hydromodpy.display.register` and decorates a :class:`BaseFigure`
subclass.
"""

from __future__ import annotations

from hydromodpy.display.figures import piezometric_map  # noqa: F401

__all__: list[str] = []
