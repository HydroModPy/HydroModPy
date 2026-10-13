"""A mesh engine is resolved by name, including one this repository never names."""

from __future__ import annotations

from typing import ClassVar

import pytest

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh import port, registry
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.port import (
    ANY_PLANAR_ENGINE,
    MeshEngine,
    MeshEngineCapabilities,
    engine_accepted,
)

pytestmark = pytest.mark.fast

_CAPABILITIES = MeshEngineCapabilities(
    cell_types=(CellType.POLYGON,),
    structured=False,
    graded=True,
    exact_faces=True,
    cell_families="exact",
    deterministic=True,
    needs_cache=False,
)


class _ConformingEngine:
    engine_id: ClassVar[str] = "test-conforming"
    engine_version: ClassVar[str] = "0.1.0"
    capabilities: ClassVar[MeshEngineCapabilities] = _CAPABILITIES

    def build(self, request: object) -> object:
        raise NotImplementedError


class _EngineTakingAnOption(_ConformingEngine):
    engine_id: ClassVar[str] = "test-with-option"

    def __init__(self, tolerance: float = 1.0) -> None:
        self.tolerance = tolerance


class _EngineWithoutBuild(_ConformingEngine):
    engine_id: ClassVar[str] = "test-no-build"
    build = None  # type: ignore[assignment]


class _EngineWithoutCapabilities:
    engine_id: ClassVar[str] = "test-no-capabilities"
    engine_version: ClassVar[str] = "0.1.0"

    def build(self, request: object) -> object:
        raise NotImplementedError


class _EngineWithLooseCapabilities(_ConformingEngine):
    engine_id: ClassVar[str] = "test-dict-capabilities"
    capabilities = {"cell_types": ("polygon",)}  # type: ignore[assignment]


class _EngineWithoutVersion(_ConformingEngine):
    engine_id: ClassVar[str] = "test-no-version"
    engine_version: ClassVar[str] = " "


class _EngineWithoutAnId:
    engine_version: ClassVar[str] = "0.1.0"
    capabilities: ClassVar[MeshEngineCapabilities] = _CAPABILITIES

    def build(self, request: object) -> object:
        raise NotImplementedError


@pytest.fixture
def clean_registry(monkeypatch: pytest.MonkeyPatch):
    """Isolate the module-level registry state for one test."""
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))
    monkeypatch.setattr(registry, "_BUILTIN_PATHS", dict(registry._BUILTIN_PATHS))
    monkeypatch.setattr(registry, "_PLUGINS_LOADED", True)
    return registry


def test_the_build_declares_the_three_engines_it_ships() -> None:
    assert registry.builtin_engine_ids() == ("regular", "triangle", "voronoi")


def test_each_builtin_lives_in_its_own_engine_package() -> None:
    for engine_id, path in registry._BUILTIN_PATHS.items():
        module, _, _ = path.partition(":")
        assert module == f"hydromodpy.spatial.mesh.engines.{engine_id}.engine"


def test_the_default_is_the_regular_engine() -> None:
    assert registry.DEFAULT_ENGINE_ID == "regular"


def test_the_group_is_the_mesh_engine_group() -> None:
    assert registry.ENTRY_POINT_GROUP == "hydromodpy.mesh.engine"


def test_listing_the_ids_imports_no_builtin(clean_registry) -> None:
    clean_registry._REGISTRY.clear()

    assert set(clean_registry.list_engine_ids()) >= {"regular", "triangle", "voronoi"}
    assert clean_registry._REGISTRY == {}


def test_the_port_names_its_four_members() -> None:
    assert port.engine_members() == ("build", "capabilities", "engine_id", "engine_version")


def test_a_conforming_class_satisfies_the_protocol() -> None:
    assert isinstance(_ConformingEngine(), MeshEngine)
    assert port.missing_engine_members(_ConformingEngine()) == ()
    assert port.missing_engine_members(object()) == port.engine_members()


def test_a_conforming_class_registers_and_resolves(clean_registry) -> None:
    clean_registry.register(_ConformingEngine)

    assert clean_registry.get("test-conforming") is _ConformingEngine
    assert clean_registry.is_registered("test-conforming")
    assert "test-conforming" in clean_registry.list_engine_ids()


def test_a_taken_id_is_refused_unless_replaced(clean_registry) -> None:
    clean_registry.register(_ConformingEngine)
    with pytest.raises(ValueError, match="already registered"):
        clean_registry.register(_ConformingEngine)

    assert clean_registry.register(_ConformingEngine, replace=True) is _ConformingEngine


@pytest.mark.parametrize(
    ("engine_cls", "named"),
    [
        (_EngineWithoutBuild, "build"),
        (_EngineWithoutCapabilities, "capabilities"),
        (_EngineWithLooseCapabilities, "capabilities"),
        (_EngineWithoutVersion, "engine_version"),
        (_EngineWithoutAnId, "engine_id"),
    ],
)
def test_an_incomplete_class_is_refused_by_name(
    clean_registry, engine_cls: type, named: str
) -> None:
    with pytest.raises(TypeError, match=named):
        clean_registry.register(engine_cls)


def test_an_unknown_name_is_refused_and_the_message_names_what_is_served() -> None:
    with pytest.raises(MeshRequestError) as raised:
        registry.get("quadtree")

    message = str(raised.value)
    assert "quadtree" in message
    assert "regular" in message
    assert registry.ENTRY_POINT_GROUP in message


def test_a_builtin_that_cannot_be_imported_says_so(clean_registry) -> None:
    clean_registry._BUILTIN_PATHS["broken"] = "hydromodpy.spatial.mesh.engines.nowhere:Engine"

    with pytest.raises(MeshRequestError, match="cannot be loaded"):
        clean_registry.get("broken")


def test_an_option_reaches_the_engine_that_names_it(clean_registry) -> None:
    clean_registry.register(_EngineTakingAnOption)

    built = clean_registry.create("test-with-option", tolerance=0.5, other=1)

    assert built.tolerance == 0.5


def _install_plugin(monkeypatch: pytest.MonkeyPatch, name: str, target: type) -> None:
    class _FakeEntryPoint:
        def __init__(self) -> None:
            self.name = name

        def load(self) -> type:
            return target

    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))
    monkeypatch.setattr(registry, "_BUILTIN_PATHS", dict(registry._BUILTIN_PATHS))
    monkeypatch.setattr(registry, "_PLUGINS_LOADED", False)
    monkeypatch.setattr(registry, "entry_points", lambda group: [_FakeEntryPoint()])


def test_a_plugin_from_the_entry_point_group_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_plugin(monkeypatch, "test-conforming", _ConformingEngine)

    assert "test-conforming" in registry.list_engine_ids()
    assert registry.get("test-conforming") is _ConformingEngine


def test_a_plugin_named_after_a_builtin_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Impostor(_ConformingEngine):
        engine_id: ClassVar[str] = "regular"

    _install_plugin(monkeypatch, "regular", _Impostor)

    assert registry.load_plugins() == 0
    assert registry._REGISTRY.get("regular") is not _Impostor


def test_a_plugin_whose_name_is_not_its_engine_id_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_plugin(monkeypatch, "another-name", _ConformingEngine)

    assert registry.load_plugins() == 0
    assert not registry.is_registered("another-name")


def test_an_incomplete_plugin_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_plugin(monkeypatch, "test-no-build", _EngineWithoutBuild)

    assert registry.load_plugins() == 0


def test_capabilities_refuse_a_cell_type_outside_the_plane() -> None:
    with pytest.raises(ValueError):
        MeshEngineCapabilities(
            cell_types=(CellType.WEDGE,),
            structured=False,
            graded=False,
            exact_faces=False,
            cell_families="exact",
            deterministic=True,
            needs_cache=False,
        )
    with pytest.raises(ValueError):
        MeshEngineCapabilities(
            cell_types=(CellType.TRIANGLE,),
            structured=False,
            graded=False,
            exact_faces=False,
            cell_families="snapped",  # type: ignore[arg-type]
            deterministic=True,
            needs_cache=False,
        )


def test_capabilities_give_the_four_declarations_the_qa_reports() -> None:
    assert _CAPABILITIES.declarations() == {
        "graded": True,
        "exact_faces": True,
        "deterministic": True,
        "needs_cache": False,
    }


def test_a_reader_accepts_the_engines_it_names() -> None:
    assert engine_accepted({"regular"}, "regular", _CAPABILITIES)
    assert not engine_accepted({"regular"}, "voronoi", _CAPABILITIES)


def test_the_planar_token_accepts_an_engine_of_planar_cells() -> None:
    assert engine_accepted({"regular", ANY_PLANAR_ENGINE}, "test-conforming", _CAPABILITIES)
    assert not engine_accepted({"triangle"}, "test-conforming", _CAPABILITIES)
