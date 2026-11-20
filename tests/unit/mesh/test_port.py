"""The mesh port: the members an engine owes and its declared capabilities.

Who reads the meshes of an engine is tested with the registry, in ``test_registry.py``.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from hydromodpy.mesh import port
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.port import MeshEngine, MeshEngineCapabilities
from tests._helpers.fake_engines import fake_capabilities

pytestmark = pytest.mark.fast

_CAPABILITIES = fake_capabilities(exact_faces=True, cell_families="exact")


class _ConformingEngine:
    engine_id: ClassVar[str] = "test-conforming"
    engine_version: ClassVar[str] = "0.1.0"
    capabilities: ClassVar[MeshEngineCapabilities] = _CAPABILITIES

    def build(self, request: object) -> object:
        raise NotImplementedError


def test_conforming_class():
    assert isinstance(_ConformingEngine(), MeshEngine)
    assert port.missing_engine_members(_ConformingEngine()) == ()
    assert port.missing_engine_members(object()) == port.engine_members()


CAPABILITY_REFUSALS = [
    pytest.param(
        {"cell_types": (CellType.WEDGE,)}, "cell_types must be a non-empty subset", id="volume cell"
    ),
    pytest.param({"cell_types": ()}, "cell_types must be a non-empty subset", id="no cell type"),
    pytest.param(
        {"cell_families": "snapped"}, "cell_families must be one of", id="unknown family rule"
    ),
    pytest.param(
        {"structured": "yes"}, "MeshEngineCapabilities.structured must be a bool", id="text flag"
    ),
    pytest.param(
        {"needs_cache": 1}, "MeshEngineCapabilities.needs_cache must be a bool", id="integer flag"
    ),
    pytest.param(
        {"lumped": "no"}, "MeshEngineCapabilities.lumped must be a bool", id="text lumped"
    ),
    pytest.param(
        {"ignored_families": ["rivers"]},
        "ignored_families must be a frozenset of str",
        id="ignored families not a frozenset",
    ),
    pytest.param(
        {"ignored_families": frozenset({"stream"})},
        "outside the families of",
        id="ignored family outside the five",
    ),
]


@pytest.mark.parametrize(("members", "message"), CAPABILITY_REFUSALS)
def test_refusals(members, message):
    with pytest.raises(ValueError, match=message):
        fake_capabilities(**members)
