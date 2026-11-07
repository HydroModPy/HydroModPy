"""A fake mesh engine and the capabilities it declares, for the planner, the registry and the mesh step.

``fake_capabilities`` declares a third-party engine of graded polygons and takes
any member as an override. ``fake_engine`` makes a new engine class that builds
the regular grid of the request under its own identity and counts its builds;
``registered`` keeps one in the mesh registry for a ``with`` block.
``patch_builtin_engines`` makes ``registry.get`` answer the capabilities of the
three built-in engines without importing them, which is all the planner reads.
Not public API.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import ClassVar

import pytest

from hydromodpy.mesh import registry
from hydromodpy.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.planar_cell_mesh import MeshIdentity, PlanarCellMesh
from hydromodpy.mesh.port import MeshEngineCapabilities
from hydromodpy.mesh.request import MeshRequest

__all__ = [
    "FakeMeshEngine",
    "builtin_capabilities",
    "fake_capabilities",
    "fake_engine",
    "patch_builtin_engines",
    "registered",
]


def fake_capabilities(**overrides: object) -> MeshEngineCapabilities:
    """Return the capabilities of a third-party engine of graded polygons; *overrides* replace members.

    The defaults are polygon cells, unstructured, graded, faces not exact, cell
    families derived from faces, deterministic, no cache.
    """
    members: dict[str, object] = {
        "cell_types": (CellType.POLYGON,),
        "structured": False,
        "graded": True,
        "exact_faces": False,
        "cell_families": "derived_from_faces",
        "deterministic": True,
        "needs_cache": False,
    }
    members.update(overrides)
    return MeshEngineCapabilities(**members)


def builtin_capabilities(*, graded: bool) -> MeshEngineCapabilities:
    """Return what the planner reads of a built-in engine: a graded one, or the regular grid.

    A graded engine (triangle, voronoi) follows faces exactly and needs a cache;
    the regular grid is structured and deterministic.
    """
    return fake_capabilities(
        cell_types=(CellType.TRIANGLE,),
        structured=not graded,
        graded=graded,
        exact_faces=graded,
        deterministic=not graded,
        needs_cache=graded,
    )


class FakeMeshEngine:
    """A mesh engine that builds the regular grid of the request under its own identity.

    Make one with ``fake_engine``, which gives each class its own id,
    capabilities and build count.
    """

    engine_id: ClassVar[str] = "fake"
    engine_version: ClassVar[str] = "1.0.0"
    capabilities: ClassVar[MeshEngineCapabilities] = fake_capabilities()
    builds: ClassVar[int] = 0

    def build(self, request: MeshRequest) -> PlanarCellMesh:
        """Count the build and return the regular grid of *request*, named after this engine."""
        type(self).builds += 1
        built = RegularMeshEngine().build(request)
        identity = MeshIdentity(self.engine_id, self.engine_version, request.canonical_hash(), None)
        return dataclasses.replace(built, identity=identity)


def fake_engine(
    engine_id: str = "fake", *, engine_version: str = "1.0.0", **capabilities: object
) -> type[FakeMeshEngine]:
    """Return a new ``FakeMeshEngine`` class with no build yet.

    *capabilities* override the members of ``fake_capabilities``.
    """
    return type(
        f"FakeMeshEngine[{engine_id}]",
        (FakeMeshEngine,),
        {
            "engine_id": engine_id,
            "engine_version": engine_version,
            "capabilities": fake_capabilities(**capabilities),
            "builds": 0,
        },
    )


@contextmanager
def registered(engine: type) -> Iterator[type]:
    """Keep *engine* in the mesh registry for the ``with`` block, then unregister it."""
    registry.register(engine)
    try:
        yield engine
    finally:
        registry.unregister(engine.engine_id)


def patch_builtin_engines(monkeypatch: pytest.MonkeyPatch) -> dict[str, SimpleNamespace]:
    """Make ``registry.get`` answer the capabilities of the built-in engines, without importing them.

    Only ``capabilities`` is set on each stand-in, so a test that builds a mesh
    does not use this patch.
    """
    engines = {
        "regular": SimpleNamespace(capabilities=builtin_capabilities(graded=False)),
        "triangle": SimpleNamespace(capabilities=builtin_capabilities(graded=True)),
        "voronoi": SimpleNamespace(capabilities=builtin_capabilities(graded=True)),
    }
    monkeypatch.setattr(registry, "get", lambda engine_id=None: engines[engine_id])
    return engines
