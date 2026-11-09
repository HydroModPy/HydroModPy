"""The mesh port: the members an engine owes and its declared capabilities.

Who reads the meshes of an engine is tested with the registry, in ``test_registry.py``.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from hydromodpy.mesh import port
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.quality import DECLARATION_KEYS
from hydromodpy.mesh.port import MeshEngine, MeshEngineCapabilities
from tests._helpers.fake_engines import fake_capabilities, lumped_capabilities

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
        ({"lumped": "no"}, "MeshEngineCapabilities.lumped must be a bool"),
    ],
    ids=[
        "volume_cell",
        "no_cell_type",
        "unknown_family_rule",
        "text_flag",
        "integer_flag",
        "text_lumped",
    ],
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


def test_an_engine_is_not_lumped_unless_it_says_so() -> None:
    """An engine written before ``lumped`` existed declares the same capabilities."""
    assert _CAPABILITIES.lumped is False
    assert lumped_capabilities().lumped is True


def test_lumped_is_not_one_of_the_declarations_the_qa_reports() -> None:
    lumped = lumped_capabilities()

    assert "lumped" not in lumped.declarations()
    assert set(lumped.declarations()) == DECLARATION_KEYS


class TestIgnoredFamilies:
    def test_defaults_to_no_ignored_family(self):
        capabilities = fake_capabilities()
        assert capabilities.ignored_families == frozenset()

    def test_is_not_one_of_the_declarations_the_qa_reports(self):
        capabilities = fake_capabilities(ignored_families=frozenset({"rivers"}))
        assert "ignored_families" not in capabilities.declarations()

    def test_names_of_a_non_frozenset_are_refused(self):
        with pytest.raises(ValueError, match="ignored_families must be a frozenset of str"):
            fake_capabilities(ignored_families=["rivers"])

    def test_a_name_outside_the_five_families_is_refused(self):
        with pytest.raises(ValueError, match="outside the families of"):
            fake_capabilities(ignored_families=frozenset({"stream"}))
