"""Figure implementations.

Importing this package triggers registration of every figure class. Add a new
figure by dropping a file in this directory that imports
:func:`hydromodpy.display.register` and decorates a :class:`BaseFigure`
subclass — the module will be picked up automatically at package import
time via :func:`pkgutil.iter_modules`.
"""

from __future__ import annotations

import importlib
import pkgutil

for _module_info in pkgutil.iter_modules(__path__):
    if _module_info.name.startswith("_"):
        continue
    importlib.import_module(f"{__name__}.{_module_info.name}")

del _module_info, importlib, pkgutil

__all__: list[str] = []
