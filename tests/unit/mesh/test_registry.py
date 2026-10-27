"""A mesh engine is resolved by name, including one this repository never names."""

from __future__ import annotations

from collections.abc import Iterator
from typing import ClassVar

import pytest

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.port import MeshEngineCapabilities
from tests._helpers.fake_engines import fake_capabilities

pytestmark = pytest.mark.fast

_CAPABILITIES = fake_capabilities(exact_faces=True, cell_families="exact")


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


class _EngineTakingAPositionalOnlyArgument(_ConformingEngine):
    engine_id: ClassVar[str] = "test-positional-only"

    def __init__(self, tolerance: float, /) -> None:
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


@pytest.fixture
def registry_warnings(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """The warnings of the registry logger, whatever the propagation of its parents."""
    registry.logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        registry.logger.removeHandler(caplog.handler)


class _FakeEntryPoint:
    def __init__(self, name: str, target: type) -> None:
        self.name = name
        self.target = target

    def load(self) -> type:
        return self.target


def _install_plugin(monkeypatch: pytest.MonkeyPatch, name: str, target: type) -> None:
    """Declare one entry point *name* for *target*, with the group not scanned yet."""
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))
    monkeypatch.setattr(registry, "_BUILTIN_PATHS", dict(registry._BUILTIN_PATHS))
    monkeypatch.setattr(registry, "_PLUGINS_LOADED", False)
    monkeypatch.setattr(registry, "entry_points", lambda group: [_FakeEntryPoint(name, target)])


# --------------------------------------------------------------------------- #
# Built-in engines and registration
# --------------------------------------------------------------------------- #


def test_listing_the_ids_imports_no_builtin(clean_registry) -> None:
    clean_registry._REGISTRY.clear()

    assert set(clean_registry.list_engine_ids()) >= set(clean_registry.builtin_engine_ids())
    assert clean_registry._REGISTRY == {}


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


def test_unregistering_an_engine_drops_its_builtin_declaration_too(clean_registry) -> None:
    clean_registry.get("regular")
    clean_registry.unregister("regular")

    assert not clean_registry.is_registered("regular")
    assert "regular" not in clean_registry.builtin_engine_ids()
    with pytest.raises(MeshRequestError, match="No mesh engine is registered for 'regular'"):
        clean_registry.get("regular")


def test_an_unknown_name_is_refused_and_the_message_names_what_is_served() -> None:
    with pytest.raises(MeshRequestError) as raised:
        registry.get("quadtree")

    message = str(raised.value)
    assert "quadtree" in message
    for engine_id in registry.list_engine_ids():
        assert engine_id in message
    assert registry.ENTRY_POINT_GROUP in message


def test_an_unknown_name_is_refused_once_the_plugin_group_is_scanned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_plugin(monkeypatch, "test-conforming", _ConformingEngine)

    with pytest.raises(MeshRequestError, match="test-conforming"):
        registry.get("quadtree")


def test_a_builtin_that_cannot_be_imported_says_so(clean_registry) -> None:
    clean_registry._BUILTIN_PATHS["broken"] = "hydromodpy.spatial.mesh.engines.nowhere:Engine"

    with pytest.raises(MeshRequestError, match="cannot be loaded"):
        clean_registry.get("broken")


def test_an_option_reaches_the_engine_that_names_it(clean_registry) -> None:
    clean_registry.register(_EngineTakingAnOption)

    built = clean_registry.create("test-with-option", tolerance=0.5, other=1)

    assert built.tolerance == 0.5


def test_an_engine_built_from_a_positional_only_argument_is_refused(clean_registry) -> None:
    clean_registry.register(_EngineTakingAPositionalOnlyArgument)

    with pytest.raises(MeshRequestError, match="tolerance positionally only"):
        clean_registry.create("test-positional-only", tolerance=0.5)


# --------------------------------------------------------------------------- #
# Plugins of the entry-point group
# --------------------------------------------------------------------------- #


def test_a_plugin_from_the_entry_point_group_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_plugin(monkeypatch, "test-conforming", _ConformingEngine)

    assert "test-conforming" in registry.list_engine_ids()
    assert registry.get("test-conforming") is _ConformingEngine


def test_a_plugin_resolves_by_name_before_any_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_plugin(monkeypatch, "test-conforming", _ConformingEngine)

    assert registry.get("test-conforming") is _ConformingEngine


def test_the_plugin_group_is_scanned_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_plugin(monkeypatch, "test-conforming", _ConformingEngine)

    assert registry.load_plugins() == 1
    assert registry.load_plugins() == 0
    assert registry.load_plugins(force=True) == 1


def test_a_plugin_named_after_an_engine_registered_by_hand_keeps_the_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Late(_ConformingEngine):
        pass

    _install_plugin(monkeypatch, "test-conforming", _Late)
    registry.register(_ConformingEngine)

    assert registry.load_plugins() == 0
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


def test_a_plugin_with_an_empty_name_is_ignored_with_a_warning(
    monkeypatch: pytest.MonkeyPatch, registry_warnings: pytest.LogCaptureFixture
) -> None:
    _install_plugin(monkeypatch, "  ", _ConformingEngine)

    assert registry.load_plugins() == 0
    assert any("entry-point name is empty" in r.getMessage() for r in registry_warnings.records)


def test_unreadable_distribution_metadata_registers_no_plugin_and_keeps_the_builtins(
    monkeypatch: pytest.MonkeyPatch, registry_warnings: pytest.LogCaptureFixture
) -> None:
    def unreadable(group: str) -> list[object]:
        raise ValueError(f"a METADATA file lists {group} twice")

    _install_plugin(monkeypatch, "test-conforming", _ConformingEngine)
    monkeypatch.setattr(registry, "entry_points", unreadable)

    assert registry.load_plugins() == 0
    assert set(registry.list_engine_ids()) >= set(registry.builtin_engine_ids())
    assert any(registry.ENTRY_POINT_GROUP in r.getMessage() for r in registry_warnings.records)
