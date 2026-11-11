"""Guard on the assembled ``Catalog`` public surface.

The reader composes three concern mixins onto one object. The ceiling keeps
the facade from growing back into a god-object: a new verb that moves or
writes something belongs to a module of its own, never to the reader.
"""

from __future__ import annotations

import inspect

from hydromodpy.results.catalog.facade import Catalog

# Ceiling, not an exact count: the surface may shrink freely but a rising number
# means new methods were stapled onto the reader instead of living elsewhere.
MAX_PUBLIC_FUNCTIONS = 50

WRITER_VERBS = ("register_simulation", "finalize", "trash", "restore", "delete", "add_tag")
"""Verbs a reader cannot have: the run writes its store, the verbs move directories."""


def _public_functions() -> list[str]:
    return [
        name
        for name, _ in inspect.getmembers(Catalog, predicate=inspect.isfunction)
        if not name.startswith("_")
    ]


def test_catalog_public_function_surface_is_bounded() -> None:
    funcs = _public_functions()
    assert len(funcs) <= MAX_PUBLIC_FUNCTIONS, (
        f"Catalog has {len(funcs)} public methods (cap {MAX_PUBLIC_FUNCTIONS}). "
        "A verb that writes belongs to its own module, not to the reader."
    )


def test_the_reader_carries_no_writer_verb() -> None:
    assert not set(WRITER_VERBS) & set(_public_functions())
    assert not any(name.startswith("write_") for name in _public_functions())
