"""A terrain engine is resolved by name, including one this repository never names.

This is the canonical test of G1 written down: "replace WhiteboxTools without
touching the callers". Before the registry it could not be written at all, because
three production sites imported ``WhiteboxTerrainEngine`` and constructed it.

The tests of the third party are the ones that matter. They install an engine
through the entry-point group, from a class defined right here and named nowhere
in ``hydromodpy/``, and resolve it by name.
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
    """Conforming but for ``delineate``, which the chain always calls.

    Declared and bound to ``None`` rather than absent, because that is the case
    ``hasattr`` lets through: the port says so about its own presence check, and
    a registry that only asked it would build this class and die on the first
    delineation.
    """

    engine_id: ClassVar[str] = "test-incomplete"
    delineate = None  # type: ignore[assignment]


class _EngineWithoutAnId:
    engine_version: ClassVar[str] = "0.1.0"


@pytest.fixture
def clean_registry(monkeypatch: pytest.MonkeyPatch):
    """Isolate the module-level registry state for one test."""
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))
    monkeypatch.setattr(registry, "_BUILTIN_PATHS", dict(registry._BUILTIN_PATHS))
    monkeypatch.setattr(registry, "_PLUGINS_LOADED", True)
    return registry


# ---------------------------------------------------------------------------
# What this build declares
# ---------------------------------------------------------------------------


def test_the_build_declares_the_two_engines_it_ships_under_their_own_ids() -> None:
    """A second name for one engine is how a request and a seal disagree.

    The default is the engine every committed number came from, and a caller
    that names no engine gets it.
    """
    from hydromodpy.spatial.terrain.numpy_engine import NumpyTerrainEngine
    from hydromodpy.spatial.terrain.whitebox_engine import WhiteboxTerrainEngine

    assert registry.builtin_engine_ids() == ("numpy_d8", "whitebox_workflows")
    assert registry.DEFAULT_ENGINE_ID == "whitebox_workflows"
    assert registry.get(None) is WhiteboxTerrainEngine
    assert registry.get("numpy_d8") is NumpyTerrainEngine
    for engine_id in registry.builtin_engine_ids():
        assert registry.get(engine_id).engine_id == engine_id


# ---------------------------------------------------------------------------
# What it refuses
# ---------------------------------------------------------------------------


def test_an_unknown_name_is_refused_and_the_message_names_what_is_served() -> None:
    with pytest.raises(TerrainRequestError) as raised:
        registry.get("pysheds")

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


# ---------------------------------------------------------------------------
# Building one
# ---------------------------------------------------------------------------


def test_an_option_reaches_the_engine_that_names_it(clean_registry) -> None:
    clean_registry.register(_EngineTakingABackend)
    sentinel = object()

    built = clean_registry.create("test-with-backend", backend=sentinel)

    assert built.backend is sentinel


def test_an_option_never_reaches_the_engine_that_does_not_name_it(clean_registry) -> None:
    """The whole reason a caller can pass ``backend`` without knowing the engine."""
    clean_registry.register(_ConformingEngine)

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


def test_building_an_unknown_name_raises_the_same_refusal_as_resolving_it() -> None:
    with pytest.raises(TerrainRequestError):
        registry.create("pysheds")


# ---------------------------------------------------------------------------
# The third party, end to end
# ---------------------------------------------------------------------------


def _install_plugin(monkeypatch: pytest.MonkeyPatch, name: str, target: object) -> None:
    """Publish *target* under *name* in the entry-point group, for one test.

    A *target* that is an exception is what loading the entry point raises.
    """

    class _FakeEntryPoint:
        def __init__(self) -> None:
            self.name = name

        def load(self) -> object:
            if isinstance(target, Exception):
                raise target
            return target

    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))
    monkeypatch.setattr(registry, "_BUILTIN_PATHS", dict(registry._BUILTIN_PATHS))
    monkeypatch.setattr(registry, "_PLUGINS_LOADED", False)
    monkeypatch.setattr(
        registry,
        "entry_points",
        lambda group: (_FakeEntryPoint(),) if group == registry.ENTRY_POINT_GROUP else (),
    )


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

    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))
    monkeypatch.setattr(registry, "_PLUGINS_LOADED", False)
    monkeypatch.setattr(registry, "entry_points", _explode)

    with caplog.at_level(logging.WARNING):
        assert registry.load_plugins() == 0
    assert "could not be scanned" in caplog.text
    assert registry.get("numpy_d8") is not None


def test_a_built_in_this_installation_cannot_load_is_refused_with_the_reason(
    clean_registry,
) -> None:
    clean_registry._REGISTRY.pop("numpy_d8", None)
    clean_registry._BUILTIN_PATHS["numpy_d8"] = "hydromodpy.no_such_module:Engine"

    with pytest.raises(TerrainRequestError, match="cannot be loaded here: ModuleNotFoundError"):
        clean_registry.get("numpy_d8")


def test_an_unregistered_engine_no_longer_resolves(clean_registry) -> None:
    """The built-in declaration goes too, or the next lookup loads it straight back."""
    clean_registry.register(_ConformingEngine)
    clean_registry.unregister("test-conforming")
    clean_registry.unregister("numpy_d8")

    assert not clean_registry.is_registered("test-conforming")
    with pytest.raises(TerrainRequestError):
        clean_registry.get("numpy_d8")
