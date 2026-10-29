"""A terrain engine is resolved by name, including one this repository never names (G1).

The third-party tests install an engine through the entry-point group, from a
class defined here and named nowhere in ``hydromodpy/``.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import ClassVar

import pytest

from hydromodpy.core.exceptions import TerrainRequestError
from hydromodpy.spatial.terrain import registry

pytestmark = pytest.mark.fast


def _not_run(*args: object, **kwargs: object) -> None:
    raise NotImplementedError


class _ConformingEngine:
    """An engine that satisfies the port and takes no constructor option."""

    engine_id: ClassVar[str] = "test-conforming"
    engine_version: ClassVar[str] = "0.1.0"

    def engine_digest(self) -> str:
        return hashlib.sha256(self.engine_id.encode("utf-8")).hexdigest()

    condition_dem = drainage_directions = flow_accumulation = _not_run
    stream_network = delineate = _not_run


class _EngineTakingABackend(_ConformingEngine):
    """An engine that names ``backend``, the way the Whitebox one does."""

    engine_id: ClassVar[str] = "test-with-backend"

    def __init__(self, backend: object = None) -> None:
        self.backend = backend


class _EngineMissingAMember(_ConformingEngine):
    """Conforming but for ``delineate``, bound to ``None``: the case ``hasattr`` lets through."""

    engine_id: ClassVar[str] = "test-incomplete"
    delineate = None  # type: ignore[assignment]


class _EngineWithoutAnId:
    engine_version: ClassVar[str] = "0.1.0"


def _isolate(monkeypatch: pytest.MonkeyPatch, *, loaded: bool, entry_points=None) -> None:
    """Copy the module-level registry state for one test, with *entry_points* if given."""
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))
    monkeypatch.setattr(registry, "_BUILTIN_PATHS", dict(registry._BUILTIN_PATHS))
    monkeypatch.setattr(registry, "_PLUGINS_LOADED", loaded)
    if entry_points is not None:
        monkeypatch.setattr(registry, "entry_points", entry_points)


@pytest.fixture
def clean_registry(monkeypatch: pytest.MonkeyPatch):
    _isolate(monkeypatch, loaded=True)
    return registry


def test_the_build_declares_the_two_engines_it_ships_under_their_own_ids() -> None:
    """A second name for one engine is how a request and a seal disagree."""
    from hydromodpy.spatial.terrain.numpy_engine import NumpyTerrainEngine
    from hydromodpy.spatial.terrain.whitebox_engine import WhiteboxTerrainEngine

    assert registry.builtin_engine_ids() == ("numpy_d8", "whitebox_workflows")
    assert registry.DEFAULT_ENGINE_ID == "whitebox_workflows"
    assert registry.get(None) is WhiteboxTerrainEngine
    assert registry.get("numpy_d8") is NumpyTerrainEngine
    for engine_id in registry.builtin_engine_ids():
        assert registry.get(engine_id).engine_id == engine_id


def test_an_unknown_name_is_refused_and_the_message_names_what_is_served() -> None:
    with pytest.raises(TerrainRequestError) as raised:
        registry.get("pysheds")
    with pytest.raises(TerrainRequestError):
        registry.create("pysheds")
    message = str(raised.value)
    assert "pysheds" in message
    assert "whitebox_workflows" in message
    assert registry.ENTRY_POINT_GROUP in message


@pytest.mark.parametrize(
    ("engine_cls", "match"),
    [(_EngineMissingAMember, "delineate"), (_EngineWithoutAnId, "engine_id")],
)
def test_a_class_that_does_not_satisfy_the_port_is_refused_by_name(
    clean_registry, engine_cls, match
) -> None:
    with pytest.raises(TypeError, match=match):
        clean_registry.register(engine_cls)


def test_a_second_registration_of_one_id_is_refused_unless_replaced(clean_registry) -> None:
    clean_registry.register(_ConformingEngine)
    with pytest.raises(ValueError):
        clean_registry.register(_ConformingEngine)
    assert clean_registry.register(_ConformingEngine, replace=True) is _ConformingEngine


def test_an_option_reaches_only_the_engine_that_names_it(clean_registry) -> None:
    """The whole reason a caller can pass ``backend`` without knowing the engine."""
    clean_registry.register(_EngineTakingABackend)
    clean_registry.register(_ConformingEngine)
    sentinel = object()
    assert clean_registry.create("test-with-backend", backend=sentinel).backend is sentinel
    built = clean_registry.create("test-conforming", backend=object())
    assert isinstance(built, _ConformingEngine)


def test_an_engine_built_from_a_positional_only_argument_is_refused(clean_registry) -> None:
    class _PositionalOnly(_ConformingEngine):
        engine_id: ClassVar[str] = "test-positional"

        def __init__(self, backend: object, /) -> None:
            self.backend = backend

    clean_registry.register(_PositionalOnly)

    with pytest.raises(TerrainRequestError, match="backend positionally only"):
        clean_registry.create("test-positional", backend=object())


def _install_plugin(monkeypatch: pytest.MonkeyPatch, name: str, target: object) -> None:
    """Publish *target* under *name*; an exception target is what loading it raises."""

    class _FakeEntryPoint:
        def __init__(self) -> None:
            self.name = name

        def load(self) -> object:
            if isinstance(target, Exception):
                raise target
            return target

    _isolate(
        monkeypatch,
        loaded=False,
        entry_points=lambda group: (_FakeEntryPoint(),) if group == registry.ENTRY_POINT_GROUP else (),
    )  # fmt: skip


def test_an_engine_installed_beside_this_build_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_plugin(monkeypatch, "test-conforming", _ConformingEngine)
    assert registry.get("test-conforming") is _ConformingEngine
    assert "test-conforming" in registry.list_engine_ids()
    assert registry.load_plugins() == 0  # the group is read once
    monkeypatch.setattr(registry, "_PLUGINS_LOADED", False)
    assert registry.load_plugins() == 0  # and an engine it holds is not registered twice
    assert registry.load_plugins(force=True) == 1


@pytest.mark.parametrize(
    ("name", "target", "warning"),
    [
        # A published, byte-gated description names ``whitebox_workflows``.
        ("whitebox_workflows", _ConformingEngine, "an engine this build ships"),
        ("another-name", _ConformingEngine, "the entry-point name is 'another-name'"),
        ("test-incomplete", _EngineMissingAMember, "missing or unusable delineate"),
        ("  ", _ConformingEngine, "its entry-point name is empty"),
        ("test-broken", ImportError("no module"), "failed to load"),
    ],
    ids=["builtin_name", "name_is_not_engine_id", "not_the_port", "empty_name", "load_fails"],
)
def test_a_plugin_that_cannot_serve_its_name_is_ignored_with_a_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, name, target, warning
) -> None:
    from hydromodpy.spatial.terrain.whitebox_engine import WhiteboxTerrainEngine

    _install_plugin(monkeypatch, name, target)
    with caplog.at_level(logging.WARNING):
        if name == "whitebox_workflows":
            assert registry.load_plugins() == 0
            assert registry.get(name) is WhiteboxTerrainEngine
        else:
            with pytest.raises(TerrainRequestError):
                registry.get(name)
    assert warning in caplog.text
    assert registry.list_engine_ids() == registry.builtin_engine_ids()


def test_a_broken_entry_point_group_does_not_take_down_a_built_in(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _explode(group: str) -> tuple[object, ...]:
        raise RuntimeError("unreadable distribution metadata")

    _isolate(monkeypatch, loaded=False, entry_points=_explode)

    with caplog.at_level(logging.WARNING):
        assert registry.load_plugins() == 0
    assert "could not be scanned" in caplog.text
    assert registry.get("numpy_d8") is not None


def test_a_built_in_that_cannot_load_or_was_unregistered_no_longer_resolves(clean_registry) -> None:
    """Unregistering drops the built-in declaration too, or the next lookup loads it back."""
    clean_registry.register(_ConformingEngine)
    clean_registry.unregister("test-conforming")
    clean_registry.unregister("numpy_d8")
    assert not clean_registry.is_registered("test-conforming")
    with pytest.raises(TerrainRequestError):
        clean_registry.get("numpy_d8")
    clean_registry._BUILTIN_PATHS["numpy_d8"] = "hydromodpy.no_such_module:Engine"
    with pytest.raises(TerrainRequestError, match="cannot be loaded here: ModuleNotFoundError"):
        clean_registry.get("numpy_d8")
