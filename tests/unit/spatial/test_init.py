"""The lazy doors of ``hydromodpy.spatial`` and ``hydromodpy.spatial.terrain``."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    ("package", "name", "module"),
    [
        ("hydromodpy.spatial", "RasterSupport", "hydromodpy.spatial.raster_support"),
        ("hydromodpy.spatial.terrain", "NumpyTerrainEngine", "hydromodpy.spatial.terrain.numpy_engine"),
    ],
)  # fmt: skip
def test_a_lazy_name_resolves_and_an_unknown_one_is_an_attribute_error(package, name, module):
    door = importlib.import_module(package)

    assert getattr(door, name) is getattr(importlib.import_module(module), name)
    with pytest.raises(AttributeError, match="no attribute 'NoSuchName'"):
        door.NoSuchName  # noqa: B018
