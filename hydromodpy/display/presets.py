"""Shipped presets: named figure requests whose panels list the holes a user fills.

A user writes more in ``[display.presets.<name>]`` with the same fields. A special
figure is a preset whose request carries ``draw``, so a TOML file names it without
naming code.
"""

from __future__ import annotations

from hydromodpy.display.request import FigureRequest

PRESETS: dict[str, FigureRequest] = {}
