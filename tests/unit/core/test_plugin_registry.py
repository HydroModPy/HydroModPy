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
        ("regular", "triangle", "voronoi"),
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


# --------------------------------------------------------------------------- #
# Built-in engines and registration
# --------------------------------------------------------------------------- #


def test_the_build_declares_the_engines_it_ships_under_their_own_ids(spec: _Spec) -> None:
    registry = spec.registry
    assert registry.names(shipped_only=True) == spec.builtin_ids
    assert spec.module.DEFAULT_ENGINE_ID == spec.default_id
    assert registry.get(None).engine_id == spec.default_id
    assert registry.get().engine_id == spec.default_id
    for engine_id in spec.builtin_ids:
        assert registry.get(engine_id).engine_id == engine_id


def test_listing_the_ids_imports_no_builtin(clean, spec: _Spec) -> None:
    clean.classes.clear()

    assert set(clean.names()) >= set(spec.builtin_ids)
    assert clean.classes == {}


def test_a_conforming_class_registers_and_resolves(clean, spec: _Spec) -> None:
    clean.register(spec.base)

    assert clean.get("test-conforming") is spec.base
    assert "test-conforming" in clean.names()


def test_a_taken_id_is_refused_unless_replaced(clean, spec: _Spec) -> None:
    clean.register(spec.base)
    with pytest.raises(ValueError, match="already registered"):
        clean.register(spec.base)

    assert clean.register(spec.base, replace=True) is spec.base


def test_a_class_claiming_a_builtin_id_is_refused_unless_replaced(clean, spec: _Spec) -> None:
    """The declaration counts as taken before the first lookup imports it."""
    impostor = _variant(spec, spec.default_id)

    with pytest.raises(ValueError, match="already registered"):
        clean.register(impostor)


def test_a_class_that_does_not_satisfy_the_port_is_refused_by_name(clean, spec: _Spec) -> None:
    unusable = _variant(spec, "test-incomplete", **{spec.member: None})
    without_id = type("_NoId", (), {k: v for k, v in vars(spec.base).items() if k != "engine_id"})

    with pytest.raises(TypeError, match=spec.member):
        clean.register(unusable)
    with pytest.raises(TypeError, match="engine_id"):
        clean.register(without_id)


def test_unregistering_an_engine_drops_its_builtin_declaration_too(clean, spec: _Spec) -> None:
    """Otherwise the next lookup loads the built-in straight back."""
    builtin = spec.builtin_ids[0]
    clean.register(spec.base)
    clean.unregister("test-conforming")
    clean.get(builtin)
    clean.unregister(builtin)

    assert "test-conforming" not in clean.names()
    assert builtin not in clean.names(shipped_only=True)
    with pytest.raises(spec.error, match=f"{spec.message_fragment} '{builtin}'"):
        clean.get(builtin)


def test_an_unknown_name_is_refused_and_the_message_names_what_is_served(spec: _Spec) -> None:
    registry = spec.registry
    with pytest.raises(spec.error) as raised:
        registry.get("quadtree")
    with pytest.raises(spec.error):
        registry.create("quadtree")

    message = str(raised.value)
    assert "quadtree" in message
    for engine_id in registry.names():
        assert engine_id in message
    assert spec.module.ENTRY_POINT_GROUP in message


def test_an_unknown_name_is_refused_once_the_plugin_group_is_scanned(
    monkeypatch: pytest.MonkeyPatch, spec: _Spec
) -> None:
    _install_plugin(monkeypatch, spec, "test-conforming", spec.base)

    with pytest.raises(spec.error, match="test-conforming"):
        spec.registry.get("quadtree")


def test_a_builtin_that_cannot_be_imported_says_so(clean, spec: _Spec) -> None:
    builtin = spec.builtin_ids[0]
    clean.builtin_paths[builtin] = "hydromodpy.no_such_module:Engine"
    clean.classes.pop(builtin, None)

    with pytest.raises(spec.error, match="cannot be loaded here: ModuleNotFoundError"):
        clean.get(builtin)


def test_an_option_reaches_only_the_engine_that_names_it(clean, spec: _Spec) -> None:
    """A caller can pass ``option`` without knowing which engine wants it."""

    def init(self: object, option: object = None) -> None:
        self.option = option  # type: ignore[attr-defined]

    clean.register(_variant(spec, "test-with-option", __init__=init))
    clean.register(spec.base)
    sentinel = object()

    assert clean.create("test-with-option", option=sentinel, other=1).option is sentinel
    assert isinstance(clean.create("test-conforming", option=object()), spec.base)


def test_an_engine_built_from_a_positional_only_argument_is_refused(clean, spec: _Spec) -> None:
    def init(self: object, option: object, /) -> None:
        self.option = option  # type: ignore[attr-defined]

    clean.register(_variant(spec, "test-positional", __init__=init))

    with pytest.raises(spec.error, match="option positionally only"):
        clean.create("test-positional", option=object())


# --------------------------------------------------------------------------- #
# Plugins of the entry-point group
# --------------------------------------------------------------------------- #


def test_a_plugin_resolves_by_name_before_any_listing(
    monkeypatch: pytest.MonkeyPatch, spec: _Spec
) -> None:
    _install_plugin(monkeypatch, spec, "test-conforming", spec.base)

    assert spec.registry.get("test-conforming") is spec.base
    assert "test-conforming" in spec.registry.names()


def test_the_plugin_group_is_scanned_once(monkeypatch: pytest.MonkeyPatch, spec: _Spec) -> None:
    _install_plugin(monkeypatch, spec, "test-conforming", spec.base)
    registry = spec.registry

    assert registry.get("test-conforming") is spec.base
    assert registry.load_plugins() == 0
    monkeypatch.setattr(registry, "plugins_loaded", False)
    assert registry.load_plugins() == 0  # an engine it holds is not registered twice
    assert registry.load_plugins(force=True) == 1


def test_a_plugin_named_after_an_engine_registered_by_hand_keeps_the_first(
    monkeypatch: pytest.MonkeyPatch, spec: _Spec
) -> None:
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
def test_a_plugin_that_cannot_serve_its_name_is_ignored_with_a_warning(
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


def test_unreadable_distribution_metadata_registers_no_plugin_and_keeps_the_builtins(
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


# --------------------------------------------------------------------------- #
# What only a mesh engine declares
# --------------------------------------------------------------------------- #


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
def test_a_mesh_engine_without_a_version_or_capabilities_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch, engine_cls: type, named: str
) -> None:
    _isolate(monkeypatch, _SPECS["mesh"], loaded=True, entry_points=None)

    with pytest.raises(TypeError, match=named):
        mesh_registry.mesh_engines.register(engine_cls)


# --------------------------------------------------------------------------- #
# A key of two attributes
# --------------------------------------------------------------------------- #

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


def test_a_key_of_two_attributes_is_their_join_and_get_takes_the_parts_or_the_join(
    pairs: PluginRegistry,
) -> None:
    backend = pairs.register(_backend("flow", "modflow_nwt"))

    assert pairs.get("flow", "modflow_nwt") is backend
    assert pairs.get("flow_modflow_nwt") is backend
    assert pairs.names() == ("flow_modflow_nwt",)
    assert isinstance(pairs.create("flow", "modflow_nwt"), backend)


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ((), ("flow_a", "flow_b_c", "flowx_d", "transport_e")),
        (("flow",), ("a", "b_c")),
        (("flow", "b"), ("c",)),
        (("flow", "a"), ("",)),
        (("flowx",), ("d",)),
        (("solute",), ()),
    ],
    ids=["no_prefix", "process", "part_of_a_name", "full_key", "longer_word", "unknown"],
)
def test_names_keeps_the_ids_under_the_joined_prefix_and_strips_it(
    pairs: PluginRegistry, prefix: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    for process_type, name in (("flow", "a"), ("flow", "b_c"), ("flowx", "d"), ("transport", "e")):
        pairs.register(_backend(process_type, name))

    assert pairs.names(*prefix) == expected


def test_the_shipped_names_neither_scan_the_group_nor_list_a_registered_class(
    monkeypatch: pytest.MonkeyPatch, pairs: PluginRegistry
) -> None:
    scans: list[str] = []
    monkeypatch.setattr(plugin_registry, "entry_points", lambda group: scans.append(group) or [])
    pairs.builtin_paths["flow_shipped"] = "hydromodpy.nowhere:Backend"
    pairs.register(_backend("flow", "added"))

    assert pairs.names("flow", shipped_only=True) == ("shipped",)
    assert scans == []
    assert pairs.names("flow") == ("added", "shipped")
    assert scans == [PAIR_GROUP]


def test_a_registry_without_a_default_refuses_a_lookup_without_a_name(
    pairs: PluginRegistry,
) -> None:
    pairs.register(_backend("flow", "a"))

    for lookup in (pairs.get, pairs.create):
        with pytest.raises(SolverInputError, match="has no default here, so it is named"):
            lookup()
    with pytest.raises(SolverInputError, match="flow_a"):
        pairs.get(None)


@pytest.mark.parametrize(
    ("candidate", "named"),
    [
        (_backend("flow", "a", run=None), "missing or unusable run"),
        (type("_NoName", (), {"process_type": "flow", "run": _not_run}), "name = 'flow', None"),
        (_backend("flow", " "), "process_type, name = 'flow', ' '"),
    ],
    ids=["member_is_none", "no_name", "blank_name"],
)
def test_a_class_without_a_usable_part_or_member_is_refused_by_name(
    pairs: PluginRegistry, candidate: type, named: str
) -> None:
    with pytest.raises(TypeError, match=named):
        pairs.register(candidate)


def test_a_member_only_a_metaclass_answers_is_refused(pairs: PluginRegistry) -> None:
    """``getattr`` would find it, and the first call would fail after the setup."""

    class _AnswersAnything(type):
        def __getattr__(cls, name: str) -> object:
            return lambda *args, **kwargs: None

    hollow = _AnswersAnything("_Hollow", (), {"process_type": "flow", "name": "hollow"})

    with pytest.raises(TypeError, match="missing or unusable run"):
        pairs.register(hollow)


def test_unregistering_takes_the_parts_of_the_key(pairs: PluginRegistry) -> None:
    pairs.register(_backend("flow", "a"))
    pairs.unregister("flow", "a")

    assert pairs.names() == ()
    with pytest.raises(SolverInputError, match="No test backend is registered for 'flow_a'"):
        pairs.get("flow", "a")


def test_a_builtin_whose_class_declares_another_key_is_refused(pairs: PluginRegistry) -> None:
    pairs.builtin_paths["flow_regular"] = "hydromodpy.mesh.engines.regular.engine:RegularMeshEngine"

    with pytest.raises(SolverInputError, match="declares process_type, name = None, None"):
        pairs.get("flow", "regular")


@pytest.mark.parametrize(
    ("entry_name", "registered", "warning"),
    [
        ("flow_modflow_nwt2", ("modflow_nwt2",), ""),
        ("flow_modflownwt2", (), "declares process_type, name = 'flow', 'modflow_nwt2'"),
        ("flow", (), "the entry-point name is 'flow'"),
    ],
    ids=["name_is_the_join", "name_drops_an_underscore", "name_is_one_part"],
)
def test_an_entry_point_name_is_compared_with_the_join_and_never_split(
    monkeypatch: pytest.MonkeyPatch,
    warnings: pytest.LogCaptureFixture,
    pairs: PluginRegistry,
    entry_name: str,
    registered: tuple[str, ...],
    warning: str,
) -> None:
    """``flow_modflownwt`` once minted a second key for ``flow/modflow_nwt``."""
    published = _backend("flow", "modflow_nwt2")
    monkeypatch.setattr(
        plugin_registry,
        "entry_points",
        lambda group: [_FakeEntryPoint(entry_name, published)] if group == PAIR_GROUP else [],
    )

    assert pairs.load_plugins() == len(registered)
    assert pairs.names("flow") == registered
    assert warning in warnings.text


# The refusal of a name nothing serves -----------------------------------------

_NAMES = ("modflow_nwt", "boussinesq", "modflow6")

CHECK_CASES = (
    ("a served name", "modflow6", _NAMES, None, None),
    (
        "an absent name, the names sorted",
        "nope",
        _NAMES,
        None,
        "solver.backend names 'nope', and this installation serves boussinesq, modflow6, "
        "modflow_nwt.",
    ),
    (
        "nothing served",
        "nope",
        (),
        None,
        "solver.backend names 'nope', and this installation serves none.",
    ),
    (
        "the group sentence",
        "nope",
        _NAMES,
        "hydromodpy.solver",
        "this installation serves boussinesq, modflow6, modflow_nwt. A third-party one joins "
        "that list through the 'hydromodpy.solver' entry-point group, without a patch to "
        "HydroModPy.",
    ),
)


@pytest.mark.parametrize(
    ("case", "value", "names", "group", "refusal"),
    CHECK_CASES,
    ids=[case[0] for case in CHECK_CASES],
)
def test_a_name_is_kept_when_served_and_refused_with_the_names_served(
    case: str, value: str, names: tuple[str, ...], group: str | None, refusal: str | None
) -> None:
    del case
    if refusal is None:
        assert (
            plugin_registry.check_registered_name(value, names, key="solver.backend", group=group)
            == value
        )
        return
    with pytest.raises(ValueError) as caught:
        plugin_registry.check_registered_name(value, names, key="solver.backend", group=group)
    assert refusal in str(caught.value)
    if group is None:
        assert "third-party" not in str(caught.value)
