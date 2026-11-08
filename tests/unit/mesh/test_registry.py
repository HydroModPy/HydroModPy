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
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.port import ANY_PLANAR_ENGINE, PLANAR_CELL_TYPES, MeshEngineCapabilities
from hydromodpy.mesh.registry import engine_accepted
from tests._helpers.fake_engines import fake_capabilities, lumped_capabilities

pytestmark = pytest.mark.fast

_PROBE = "test-conforming"


def _serve(monkeypatch: pytest.MonkeyPatch, capabilities: MeshEngineCapabilities) -> None:
    """Make the registry answer *capabilities* for the probe id, and refuse any other id."""

    def get(engine_id: str | None = None) -> SimpleNamespace:
        if engine_id != _PROBE:
            raise MeshRequestError(f"No mesh engine is registered for {engine_id!r}")
        return SimpleNamespace(capabilities=capabilities)

    monkeypatch.setattr(registry.mesh_engines, "get", get)


def test_the_build_serves_the_four_engines_by_their_dotted_paths() -> None:
    assert registry.mesh_engines.names(shipped_only=True) == (
        "catchment",
        "regular",
        "triangle",
        "voronoi",
    )
    assert registry.mesh_engines.get("catchment").capabilities.lumped is True


@pytest.mark.parametrize(
    ("accepted", "expected"),
    [
        ({"regular"}, True),
        ({"regular", ANY_PLANAR_ENGINE}, True),
        ({"triangle"}, False),
        (frozenset(), False),
    ],
    ids=["named", "named_beside_the_token", "another_name", "nothing"],
)
def test_a_reader_reads_an_engine_it_names_without_loading_it(
    monkeypatch: pytest.MonkeyPatch, accepted: set[str], expected: bool
) -> None:
    """The id alone decides when the token is absent or the id is named."""

    def get(engine_id: str | None = None) -> None:
        raise AssertionError(f"the class of {engine_id!r} was loaded")

    monkeypatch.setattr(registry.mesh_engines, "get", get)

    assert engine_accepted(accepted, "regular") is expected


@pytest.mark.parametrize("cell_type", sorted(PLANAR_CELL_TYPES, key=lambda t: t.value))
def test_the_planar_token_reads_an_engine_of_planar_cells(
    monkeypatch: pytest.MonkeyPatch, cell_type: CellType
) -> None:
    _serve(monkeypatch, fake_capabilities(cell_types=(cell_type,)))

    assert engine_accepted({"regular", ANY_PLANAR_ENGINE}, _PROBE)
    assert not engine_accepted({"triangle"}, _PROBE)


@pytest.mark.parametrize(
    ("accepted", "expected"),
    [
        ({"regular", ANY_PLANAR_ENGINE}, False),
        ({ANY_PLANAR_ENGINE, _PROBE}, True),
    ],
    ids=["by_the_token", "by_its_name"],
)
def test_a_lumped_engine_is_read_only_by_a_reader_that_names_it(
    monkeypatch: pytest.MonkeyPatch, accepted: set[str], expected: bool
) -> None:
    _serve(monkeypatch, lumped_capabilities())

    assert engine_accepted(accepted, _PROBE) is expected


def test_the_planar_token_does_not_read_the_catchment_engine() -> None:
    reader = {"regular", "triangle", "voronoi", ANY_PLANAR_ENGINE}

    assert not engine_accepted(reader, "catchment")
    assert engine_accepted(reader | {"catchment"}, "catchment")
    assert engine_accepted(reader, "voronoi")


def test_an_engine_nothing_serves_is_refused_when_its_capabilities_decide() -> None:
    with pytest.raises(MeshRequestError, match="quadtree"):
        engine_accepted({ANY_PLANAR_ENGINE}, "quadtree")
    assert not engine_accepted({"regular"}, "quadtree")
