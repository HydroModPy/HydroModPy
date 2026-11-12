"""The mesh registry: the engines it serves, and the one rule of who reads their meshes.

A reader, a solver that lists the meshes it reads, names engine ids or the token
``*planar``. The token stands for every engine of planar cells that is not
lumped: an engine that meshes the catchment as one cell is read only by a solver
that names it. The engine class is loaded only when its capabilities decide.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.mesh import registry
from hydromodpy.mesh.port import ANY_PLANAR_ENGINE, MeshEngineCapabilities
from hydromodpy.mesh.registry import engine_accepted

pytestmark = pytest.mark.fast

_PROBE = "test-conforming"


def _serve(monkeypatch: pytest.MonkeyPatch, capabilities: MeshEngineCapabilities) -> None:
    """Make the registry answer *capabilities* for the probe id, and refuse any other id."""

    def get(engine_id: str | None = None) -> SimpleNamespace:
        if engine_id != _PROBE:
            raise MeshRequestError(f"No mesh engine is registered for {engine_id!r}")
        return SimpleNamespace(capabilities=capabilities)

    monkeypatch.setattr(registry.mesh_engines, "get", get)


def test_an_engine_nothing_serves_is_refused_when_its_capabilities_decide() -> None:
    with pytest.raises(MeshRequestError, match="quadtree"):
        engine_accepted({ANY_PLANAR_ENGINE}, "quadtree")
    assert not engine_accepted({"regular"}, "quadtree")
