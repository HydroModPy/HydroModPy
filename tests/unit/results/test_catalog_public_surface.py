"""Guard on the assembled ``Catalog`` public surface.

The facade composes several concern mixins onto one runtime object. CLAUDE.md
caps a class at 50 methods; the mixin split keeps each file under that limit,
so the composition is pinned here as the v1 contract. New run-management verbs
must route through the ``Catalog`` handle without growing this ceiling: if this
fails, split into a composed namespace instead of adding another method.
"""

from __future__ import annotations

import inspect

from hydromodpy.results.catalog import Catalog

# Ceiling, not an exact count: the surface may shrink freely but a rising number
# means new methods were stapled onto the god-facade instead of namespaced.
MAX_PUBLIC_FUNCTIONS = 92


def test_catalog_public_function_surface_is_bounded() -> None:
    funcs = [
        name
        for name, _ in inspect.getmembers(Catalog, predicate=inspect.isfunction)
        if not name.startswith("_")
    ]
    assert len(funcs) <= MAX_PUBLIC_FUNCTIONS, (
        f"Catalog has {len(funcs)} public methods (cap {MAX_PUBLIC_FUNCTIONS}). "
        "Route new verbs through a composed namespace instead of extending the facade."
    )
