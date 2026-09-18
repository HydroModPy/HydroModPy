"""The ``data-fetch`` capability: its declaration, its body, its artefacts.

Kept apart from ``data/source/``, which a third-party source imports and which
a gate holds to importing nothing heavier than ``core`` and the record types.
This package is the caller of that port: it carries the Pydantic request model,
it names the four sources this build **describes**, and it writes job artefacts.
The registry serves more than four -- hydrography's three live there too -- and
the difference is D146: a description is package data, so it names what the
wheel was built with and never what is installed beside it.
"""

from __future__ import annotations

__all__: list[str] = []
