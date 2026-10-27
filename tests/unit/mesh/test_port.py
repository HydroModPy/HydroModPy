"""The mesh port: the members an engine owes, its declared capabilities, and who reads its meshes."""

from __future__ import annotations

from typing import ClassVar

import pytest

from hydromodpy.spatial.mesh import port
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.mesh_qa import DECLARATION_KEYS
from hydromodpy.spatial.mesh.port import (
    ANY_PLANAR_ENGINE,
    PLANAR_CELL_TYPES,
    MeshEngine,
    MeshEngineCapabilities,
    engine_accepted,
)
from tests._helpers.fake_engines import fake_capabilities

pytestmark = pytest.mark.fast

_CAPABILITIES = fake_capabilities(exact_faces=True, cell_families="exact")


class _ConformingEngine:
    engine_id: ClassVar[str] = "test-conforming"
    engine_version: ClassVar[str] = "0.1.0"
    capabilities: ClassVar[MeshEngineCapabilities] = _CAPABILITIES

    def build(self, request: object) -> object:
        raise NotImplementedError


def test_a_conforming_class_satisfies_the_protocol() -> None:
    assert isinstance(_ConformingEngine(), MeshEngine)
    assert port.missing_engine_members(_ConformingEngine()) == ()
    assert port.missing_engine_members(object()) == port.engine_members()


@pytest.mark.parametrize(
    ("members", "message"),
    [
        ({"cell_types": (CellType.WEDGE,)}, "cell_types must be a non-empty subset"),
        ({"cell_types": ()}, "cell_types must be a non-empty subset"),
        ({"cell_families": "snapped"}, "cell_families must be one of"),
        ({"structured": "yes"}, "MeshEngineCapabilities.structured must be a bool"),
        ({"needs_cache": 1}, "MeshEngineCapabilities.needs_cache must be a bool"),
    ],
    ids=["volume_cell", "no_cell_type", "unknown_family_rule", "text_flag", "integer_flag"],
)
def test_capabilities_refuse_what_a_planar_engine_cannot_declare(
    members: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        fake_capabilities(**members)


def test_capabilities_take_a_cell_type_by_its_name() -> None:
    capabilities = fake_capabilities(cell_types=("triangle",))

    assert capabilities.cell_types == (CellType.TRIANGLE,)


def test_capabilities_give_the_declarations_the_qa_reports() -> None:
    declarations = _CAPABILITIES.declarations()

    assert set(declarations) == DECLARATION_KEYS
    assert declarations == {key: getattr(_CAPABILITIES, key) for key in DECLARATION_KEYS}


def test_a_reader_accepts_the_engines_it_names() -> None:
    assert engine_accepted({"regular"}, "regular", _CAPABILITIES)
    assert not engine_accepted({"regular"}, "voronoi", _CAPABILITIES)


@pytest.mark.parametrize("cell_type", sorted(PLANAR_CELL_TYPES, key=lambda t: t.value))
def test_the_planar_token_accepts_an_engine_of_planar_cells(cell_type: CellType) -> None:
    capabilities = fake_capabilities(cell_types=(cell_type,))

    assert engine_accepted({"regular", ANY_PLANAR_ENGINE}, "test-conforming", capabilities)
    assert not engine_accepted({"triangle"}, "test-conforming", capabilities)
