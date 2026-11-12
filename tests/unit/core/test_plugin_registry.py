"""The registry engine resolves a class by name, a third-party one included.

The terrain and mesh engine registries are instances of
``core.plugin_registry.PluginRegistry``, so one parameterized suite runs on each.
The third-party tests install an engine through the entry-point group, from a
class defined here and named nowhere in ``hydromodpy/``. The last section runs an
instance built here, keyed on two attributes, for what only such a key shows:
the join, the prefix of ``names`` and a name that is never split.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import ClassVar

import pytest

import hydromodpy.core.plugin_registry as plugin_registry
from hydromodpy.catchment.terrain import registry as terrain_registry
from hydromodpy.core.exceptions import MeshRequestError, SolverInputError, TerrainRequestError
from hydromodpy.core.plugin_registry import PluginRegistry
from hydromodpy.mesh import registry as mesh_registry
from hydromodpy.mesh.port import MeshEngineCapabilities
from tests._helpers.fake_engines import fake_capabilities

pytestmark = pytest.mark.fast

_CAPABILITIES = fake_capabilities(exact_faces=True, cell_families="exact")


def _not_run(*args: object, **kwargs: object) -> None:
    raise NotImplementedError


class _MeshEngine:
    engine_id: ClassVar[str] = "test-conforming"
    engine_version: ClassVar[str] = "0.1.0"
    capabilities: ClassVar[MeshEngineCapabilities] = _CAPABILITIES

    def build(self, request: object) -> object:
        raise NotImplementedError


class _TerrainEngine:
    engine_id: ClassVar[str] = "test-conforming"
    engine_version: ClassVar[str] = "0.1.0"

    def engine_digest(self) -> str:
        return hashlib.sha256(self.engine_id.encode("utf-8")).hexdigest()

    condition_dem = drainage_directions = flow_accumulation = _not_run
    stream_network = delineate = _not_run


@dataclass(frozen=True)
class _Spec:
    """What differs between the two registries."""

    registry: PluginRegistry
    module: object
    error: type[Exception]
    base: type
    member: str
    builtin_ids: tuple[str, ...]
    default_id: str
    message_fragment: str


_SPECS = {
    "mesh": _Spec(
        mesh_registry.mesh_engines,
        mesh_registry,
        MeshRequestError,
        _MeshEngine,
        "build",
        ("catchment", "regular", "triangle", "voronoi"),
        "regular",
        "No mesh engine is registered for",
    ),
    "terrain": _Spec(
        terrain_registry.terrain_engines,
        terrain_registry,
        TerrainRequestError,
        _TerrainEngine,
        "delineate",
        ("numpy_d8", "whitebox_workflows"),
        "whitebox_workflows",
        "No terrain engine is registered for",
    ),
}


@pytest.fixture(params=sorted(_SPECS))
def spec(request: pytest.FixtureRequest) -> _Spec:
    return _SPECS[request.param]


def _variant(spec: _Spec, engine_id: str, **members: object) -> type:
    return type(f"_{engine_id}", (spec.base,), {"engine_id": engine_id, **members})


def _isolate(
    monkeypatch: pytest.MonkeyPatch, spec: _Spec, *, loaded: bool, entry_points: Callable | None
) -> None:
    registry = spec.registry
    monkeypatch.setattr(registry, "classes", dict(registry.classes))
    monkeypatch.setattr(registry, "builtin_paths", dict(registry.builtin_paths))
    monkeypatch.setattr(registry, "plugins_loaded", loaded)
    if entry_points is not None:
        monkeypatch.setattr(plugin_registry, "entry_points", entry_points)


@pytest.fixture
def clean(monkeypatch: pytest.MonkeyPatch, spec: _Spec):
    """The registry with its state copied for one test and its plugin group marked scanned."""
    _isolate(monkeypatch, spec, loaded=True, entry_points=None)
    return spec.registry


@pytest.fixture
def warnings(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """The warnings of the registry logger, whatever the propagation of its parents."""
    plugin_registry.logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING):
            yield caplog
    finally:
        plugin_registry.logger.removeHandler(caplog.handler)


class _FakeEntryPoint:
    def __init__(self, name: str, target: object) -> None:
        self.name = name
        self.target = target

    def load(self) -> object:
        if isinstance(self.target, Exception):
            raise self.target
        return self.target


def _install_plugin(
    monkeypatch: pytest.MonkeyPatch, spec: _Spec, name: str, target: object
) -> None:
    """Declare one entry point *name* for *target*, with the group not scanned yet."""
    wanted = spec.module.ENTRY_POINT_GROUP
    _isolate(
        monkeypatch,
        spec,
        loaded=False,
        entry_points=lambda group: [_FakeEntryPoint(name, target)] if group == wanted else [],
    )


def test_positional_only_option_refused(clean, spec: _Spec) -> None:
    def init(self: object, option: object, /) -> None:
        self.option = option  # type: ignore[attr-defined]

    clean.register(_variant(spec, "test-positional", __init__=init))

    with pytest.raises(spec.error, match="option positionally only"):
        clean.create("test-positional", option=object())


def test_plugin_resolves_by_name(monkeypatch: pytest.MonkeyPatch, spec: _Spec) -> None:
    _install_plugin(monkeypatch, spec, "test-conforming", spec.base)

    assert spec.registry.get("test-conforming") is spec.base
    assert "test-conforming" in spec.registry.names()


def test_plugin_group_scanned_once(monkeypatch: pytest.MonkeyPatch, spec: _Spec) -> None:
    _install_plugin(monkeypatch, spec, "test-conforming", spec.base)
    registry = spec.registry

    assert registry.get("test-conforming") is spec.base
    assert registry.load_plugins() == 0
    monkeypatch.setattr(registry, "plugins_loaded", False)
    assert registry.load_plugins() == 0  # an engine it holds is not registered twice
    assert registry.load_plugins(force=True) == 1


def test_first_registration_wins(monkeypatch: pytest.MonkeyPatch, spec: _Spec) -> None:
    late = _variant(spec, "test-conforming")
    _install_plugin(monkeypatch, spec, "test-conforming", late)
    spec.registry.register(spec.base)

    assert spec.registry.load_plugins() == 0
    assert spec.registry.get("test-conforming") is spec.base


@pytest.mark.parametrize(
    ("name", "target", "warning"),
    [
        ("builtin", None, "this build ships"),
        ("another-name", None, "the entry-point name is 'another-name'"),
        ("test-incomplete", "incomplete", "missing or unusable"),
        ("  ", None, "its entry-point name is empty"),
        ("test-broken", ImportError("no module"), "failed to load"),
    ],
    ids=["builtin_name", "name_is_not_engine_id", "not_the_port", "empty_name", "load_fails"],
)
def test_unusable_plugin_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
    warnings: pytest.LogCaptureFixture,
    spec: _Spec,
    name: str,
    target: object,
    warning: str,
) -> None:
    registry = spec.registry
    if name == "builtin":
        name = spec.default_id
        target = _variant(spec, spec.default_id)
    elif target == "incomplete":
        target = _variant(spec, name, **{spec.member: None})
    elif target is None:
        target = spec.base
    _install_plugin(monkeypatch, spec, name, target)

    assert registry.load_plugins() == 0
    assert warning in warnings.text
    assert registry.get(spec.default_id) is not target
    assert registry.names() == registry.names(shipped_only=True)


def test_unreadable_metadata_keeps_builtins(
    monkeypatch: pytest.MonkeyPatch, warnings: pytest.LogCaptureFixture, spec: _Spec
) -> None:
    def unreadable(group: str) -> list[object]:
        raise ValueError(f"a METADATA file lists {group} twice")

    _install_plugin(monkeypatch, spec, "test-conforming", spec.base)
    monkeypatch.setattr(plugin_registry, "entry_points", unreadable)

    assert spec.registry.load_plugins() == 0
    assert "could not be scanned" in warnings.text
    assert spec.module.ENTRY_POINT_GROUP in warnings.text
    assert set(spec.registry.names()) >= set(spec.builtin_ids)
    assert spec.registry.get(spec.builtin_ids[0]) is not None


class _WithoutCapabilities(_MeshEngine):
    engine_id: ClassVar[str] = "test-no-capabilities"
    capabilities = None  # type: ignore[assignment]


class _WithLooseCapabilities(_MeshEngine):
    engine_id: ClassVar[str] = "test-dict-capabilities"
    capabilities = {"cell_types": ("polygon",)}  # type: ignore[assignment]


class _WithoutVersion(_MeshEngine):
    engine_id: ClassVar[str] = "test-no-version"
    engine_version: ClassVar[str] = " "


@pytest.mark.parametrize(
    ("engine_cls", "named"),
    [
        (_WithoutCapabilities, "capabilities"),
        (_WithLooseCapabilities, "capabilities"),
        (_WithoutVersion, "engine_version"),
    ],
)
def test_mesh_engine_refusals(
    monkeypatch: pytest.MonkeyPatch, engine_cls: type, named: str
) -> None:
    _isolate(monkeypatch, _SPECS["mesh"], loaded=True, entry_points=None)

    with pytest.raises(TypeError, match=named):
        mesh_registry.mesh_engines.register(engine_cls)


# A key of two attributes

PAIR_GROUP = "hydromodpy.test.pair"


class _Backend:
    process_type: ClassVar[str] = "flow"
    name: ClassVar[str] = "probe"

    def run(self) -> None:
        raise NotImplementedError


def _backend(process_type: str, name: str, **members: object) -> type:
    return type(
        f"_Backend[{process_type}_{name}]",
        (_Backend,),
        {"process_type": process_type, "name": name, **members},
    )


@pytest.fixture
def pairs(monkeypatch: pytest.MonkeyPatch) -> PluginRegistry:
    """A registry keyed on ``process_type`` and ``name``, with no default and no plugin."""
    monkeypatch.setattr(plugin_registry, "entry_points", lambda group: [])
    return PluginRegistry(
        kind="test backend",
        id_attributes=("process_type", "name"),
        group=PAIR_GROUP,
        builtin_paths={},
        members=lambda: ("run",),
        error=SolverInputError,
    )


def test_lookup_needs_a_name(
    pairs: PluginRegistry,
) -> None:
    pairs.register(_backend("flow", "a"))

    for lookup in (pairs.get, pairs.create):
        with pytest.raises(SolverInputError, match="has no default here, so it is named"):
            lookup()
    with pytest.raises(SolverInputError, match="flow_a"):
        pairs.get(None)


def test_builtin_with_other_key_refused(pairs: PluginRegistry) -> None:
    pairs.builtin_paths["flow_regular"] = "hydromodpy.mesh.engines.regular.engine:RegularMeshEngine"

    with pytest.raises(SolverInputError, match="declares process_type, name = None, None"):
        pairs.get("flow", "regular")


def _figure_named(name: str) -> type:
    return type(f"_{name}", (), {"name": name, "render": lambda self: None})


class _StubEntryPoint:
    """An entry point as ``importlib.metadata`` hands one over, or a broken one."""

    def __init__(
        self,
        name: str,
        target: str,
        cls: type | None = None,
        load_error: Exception | None = None,
    ) -> None:
        self.name = name
        self.value = target
        self._cls = cls
        self._load_error = load_error

    def load(self) -> type:
        if self._load_error is not None:
            raise self._load_error
        assert self._cls is not None
        return self._cls


def _figures_registry() -> PluginRegistry:
    return PluginRegistry(
        kind="figure",
        id_attributes=("name",),
        group="hydromodpy.test.figures",
        builtin_paths={"cross_section": "hydromodpy.nowhere:Figure"},
        members=lambda: ("name", "render"),
        error=ValueError,
    )


def _declare(monkeypatch: pytest.MonkeyPatch, *entries: _StubEntryPoint) -> PluginRegistry:
    registry = _figures_registry()
    monkeypatch.setattr(
        plugin_registry,
        "entry_points",
        lambda group: list(entries) if group == registry.group else [],
    )
    return registry


def test_registry_without_group(monkeypatch) -> None:
    # A closed surface takes no plugin, and its refusal does not offer one.
    scans: list[str] = []
    monkeypatch.setattr(plugin_registry, "entry_points", lambda group: scans.append(group) or [])
    plain = PluginRegistry(
        kind="figure",
        id_attributes=("name",),
        group=None,
        builtin_paths={"cross_section": "hydromodpy.nowhere:Figure"},
        members=lambda: ("name", "render"),
        error=ValueError,
    )

    assert plain.names() == ("cross_section",)
    assert plain.load_plugins() == 0
    assert plain.plugins_loaded
    assert scans == []
    with pytest.raises(ValueError) as raised:
        plain.get("hydrograph")
    assert "cross_section" in str(raised.value)
    assert "entry-point" not in str(raised.value)


def test_unimportable_entry_point(
    monkeypatch: pytest.MonkeyPatch,
    warnings: pytest.LogCaptureFixture,
) -> None:
    broken = _StubEntryPoint(
        "hydrograph_amazon",
        "hydromodpy_figures.rivers:AmazonFigure",
        load_error=ModuleNotFoundError("No module named 'hydromodpy_figures'"),
    )
    registry = _declare(monkeypatch, broken)

    assert "hydrograph_amazon" not in registry.names()
    assert "failed to load" not in warnings.text
    with pytest.raises(ValueError) as raised:
        registry.get("hydrograph_amazon")
    message = str(raised.value)
    assert "'hydrograph_amazon' is declared by the entry point hydrograph_amazon = " in message
    assert "hydromodpy_figures.rivers:AmazonFigure" in message
    assert "No module named 'hydromodpy_figures'" in message
    assert "Put the package that provides it on sys.path." in message


def test_duplicate_target_is_one_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cls = _figure_named("hydrograph_amazon")
    twice = _StubEntryPoint("hydrograph_amazon", "hydromodpy_figures.rivers:AmazonFigure", cls)
    registry = _declare(monkeypatch, twice, twice)

    assert registry.load_plugins() == 1
    assert registry.names() == ("cross_section", "hydrograph_amazon")
    assert registry.get("hydrograph_amazon") is cls


def test_disagreeing_entry_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _StubEntryPoint(
        "hydrograph_amazon", "figures.a:Amazon", _figure_named("hydrograph_amazon")
    )
    second = _StubEntryPoint(
        "hydrograph_amazon", "figures.b:Amazon", _figure_named("hydrograph_amazon")
    )
    registry = _declare(monkeypatch, first, second)

    assert "hydrograph_amazon" not in registry.names()
    assert registry.load_plugins() == 0
    with pytest.raises(ValueError) as raised:
        registry.get("hydrograph_amazon")
    message = str(raised.value)
    assert "declared by two entry points that do not agree" in message
    assert "figures.a:Amazon" in message and "figures.b:Amazon" in message
    assert "serves neither" in message
