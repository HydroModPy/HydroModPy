"""Unit tests for ``hydromodpy.solver.base.registry``: ``solvers``, ``extractors`` and the backend hook."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import hydromodpy.core.plugin_registry as plugin_registry
from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.mesh.port import ANY_PLANAR_ENGINE
from hydromodpy.model.runtime_config import FlowRuntimeConfig
from hydromodpy.model.transport.transport_config import (
    TransportModflow6GwtConfig,
    TransportModflow6PrtConfig,
    TransportModpathConfig,
    TransportMt3dmsConfig,
)
from hydromodpy.solver.base import registry
from hydromodpy.solver.base.adapter_protocol import SolverAdapter
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
from hydromodpy.solver.modflow_nwt.nwt.nwt_config import ModflowConfig
from tests._helpers.fake_solvers import FakeAdapter, fake_adapter, fake_extractor

ROOT = Path(__file__).resolve().parents[4]

solvers = registry.solvers
extractors = registry.extractors


@pytest.fixture(autouse=True)
def _clean_registry(isolated_solvers):
    """Each test works on a copy of both registries, with the plugin groups marked scanned."""
    return isolated_solvers


class _StubEntryPoint:
    def __init__(self, name: str, target: type) -> None:
        self.name = name
        self.target = target

    def load(self) -> type:
        return self.target


def _install(monkeypatch: pytest.MonkeyPatch, group: str, *entry_points: _StubEntryPoint) -> list:
    """Publish *entry_points* in *group*, mark both groups unscanned, and return the scan log."""
    scans: list[str] = []

    def _fake_entry_points(*, group: str):
        scans.append(group)
        return list(entry_points) if group == wanted else []

    wanted = group
    monkeypatch.setattr(plugin_registry, "entry_points", _fake_entry_points)
    monkeypatch.setattr(solvers, "plugins_loaded", False)
    monkeypatch.setattr(extractors, "plugins_loaded", False)
    return scans


# ---------------------------------------------------------------------------
# What the build ships
# ---------------------------------------------------------------------------


def test_every_declared_backend_has_an_extractor() -> None:
    """A backend the config can select must still be readable after the solve.

    An adapter without an extractor solves, then loses the run at ingestion.
    """
    assert sorted(set(solvers.names()) - set(extractors.names())) == []


def test_no_entry_point_gives_a_backend_a_second_name() -> None:
    """In-tree backends are declared once, in the registry, never as plugins.

    ``flow_modflownwt`` used to mint ``flow/modflownwt`` beside
    ``flow/modflow_nwt``, a key with an adapter but no extractor.
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = pyproject["project"].get("entry-points", {}).get(registry.ENTRY_POINT_GROUP, {})
    for name in declared:
        assert name in extractors.names(), (
            f"entry-point {name!r} declares a key no extractor can read back"
        )


def test_builtin_process_types_exclude_workflow_stub_phases() -> None:
    assert solvers.names("postprocess") == ()
    assert solvers.names("display") == ()


DECLARED = {
    "flow_modflow6": {
        "accepted_meshes": frozenset({"regular", "triangle", "voronoi", ANY_PLANAR_ENGINE}),
        "geometry": "cells",
        "category": "distributed",
        "options": Modflow6Config,
        "requires": (),
        "reads": (),
        "surface_excess": False,
    },
    "flow_modflow_nwt": {
        "accepted_meshes": frozenset({"regular"}),
        "geometry": "raster",
        "category": "distributed",
        "options": ModflowConfig,
        "requires": (),
        "reads": (),
        "surface_excess": False,
    },
    "flow_boussinesq": {
        "accepted_meshes": frozenset({"triangle"}),
        "geometry": "cells",
        "category": "integrated",
        "options": FlowRuntimeConfig,
        "requires": (),
        "reads": (),
        "surface_excess": True,
    },
    "transport_modflow6": {
        "accepted_meshes": frozenset(),
        "geometry": "cells",
        "category": "distributed",
        "options": TransportModflow6GwtConfig,
        "requires": (("flow", "modflow6"),),
        "reads": ("face_flow",),
        "surface_excess": False,
    },
    "transport_modflow6_prt": {
        "accepted_meshes": frozenset(),
        "geometry": "cells",
        "category": "distributed",
        "options": TransportModflow6PrtConfig,
        "requires": (("flow", "modflow6"),),
        "reads": ("face_flow",),
        "surface_excess": False,
    },
    "transport_mt3dms": {
        "accepted_meshes": frozenset(),
        "geometry": "raster",
        "category": "distributed",
        "options": TransportMt3dmsConfig,
        "requires": (("flow", "modflow_nwt"),),
        "reads": ("face_flow",),
        "surface_excess": False,
    },
    "transport_modpath": {
        "accepted_meshes": frozenset(),
        "geometry": "raster",
        "category": "distributed",
        "options": TransportModpathConfig,
        "requires": (("flow", "modflow_nwt"),),
        "reads": ("face_flow",),
        "surface_excess": False,
    },
}
"""What each backend of the build declares. The extractor categories and the index
table held these values before the attributes moved to the adapter, and the
mesh, requires and surface-excess rows are what the configuration and the
planner read."""


@pytest.mark.parametrize("key", sorted(DECLARED))
def test_each_shipped_backend_declares_what_the_build_relies_on(key: str) -> None:
    adapter = solvers.get(key)
    expected = DECLARED[key]

    assert adapter.accepted_meshes == expected["accepted_meshes"]
    assert adapter.geometry == expected["geometry"]
    assert adapter.category == expected["category"]
    assert adapter.options is expected["options"]
    assert adapter.requires == expected["requires"]
    assert adapter.reads == expected["reads"]
    assert adapter.native_step is None
    assert adapter.mutable == frozenset()
    assert ("budget/surface_excess" in adapter.writes) is expected["surface_excess"]


def test_the_shipped_backends_are_the_declared_ones() -> None:
    assert solvers.names(shipped_only=True) == tuple(sorted(DECLARED))


def test_transport_capabilities_are_explicit() -> None:
    """Concentration for GWT and MT3DMS, particle tracks for PRT and MODPATH."""
    for name in ("modflow6", "mt3dms"):
        writes = solvers.get("transport", name).writes
        assert "concentration" in writes
        assert not any(item.startswith("particles/") for item in writes)
    for name in ("modflow6_prt", "modpath"):
        writes = solvers.get("transport", name).writes
        assert {"particles/x", "particles/y", "particles/z", "particles/time"} <= set(writes)
        assert "concentration" not in writes


def test_modflow6_prt_adapter_and_extractor_are_registered() -> None:
    adapter_cls = solvers.get("transport", "modflow6_prt")
    extractor_cls = extractors.get("transport", "modflow6_prt")

    assert adapter_cls.__name__ == "Modflow6PrtTransportAdapter"
    assert extractor_cls.__name__ == "Modflow6PrtOutputAdapter"


def test_every_registered_adapter_satisfies_the_contract() -> None:
    """Every key the registry serves, built-in or lazy, is a real adapter under its own key."""
    for key in solvers.names():
        adapter_cls = solvers.get(key)
        assert isinstance(adapter_cls, SolverAdapter), key
        assert f"{adapter_cls.process_type}_{adapter_cls.name}" == key, (
            f"{adapter_cls.__qualname__} is registered under a key it does not declare"
        )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_and_get_returns_cls() -> None:
    assert solvers.register(FakeAdapter) is FakeAdapter
    assert solvers.get("flow", "fake") is FakeAdapter
    assert solvers.get("flow_fake") is FakeAdapter


def test_register_duplicate_raises_without_replace() -> None:
    solvers.register(fake_adapter("dup"))
    with pytest.raises(ValueError, match="already registered for 'flow_dup'"):
        solvers.register(fake_adapter("dup"))


def test_register_duplicate_with_replace_overwrites() -> None:
    solvers.register(fake_adapter("dup2"))
    replacement = fake_adapter("dup2")
    solvers.register(replacement, replace=True)
    assert solvers.get("flow", "dup2") is replacement


def test_get_unknown_raises_a_solver_input_error() -> None:
    with pytest.raises(SolverInputError, match="No solver backend is registered for 'flow_nope'"):
        solvers.get("flow", "nope")


def test_names_are_sorted() -> None:
    solvers.builtin_paths.clear()
    solvers.classes.clear()
    for name, process_type in (("b", "flow"), ("a", "flow"), ("c", "transport")):
        solvers.register(fake_adapter(name, process_type))
    assert solvers.names() == ("flow_a", "flow_b", "transport_c")


def test_names_filter_by_process_type() -> None:
    solvers.builtin_paths.clear()
    solvers.classes.clear()
    solvers.register(fake_adapter("a", "flow"))
    solvers.register(fake_adapter("b", "transport"))
    assert solvers.names("flow") == ("a",)


def test_solver_config_accepts_registered_plugin_flow_solver() -> None:
    solvers.register(fake_adapter("pluginsolver"))

    cfg = SolverConfig.model_validate({"backend": " PluginSolver "})

    assert cfg.backend_name == "pluginsolver"


def test_solver_config_rejects_unknown_flow_solver() -> None:
    with pytest.raises(ValueError, match="solver.backend names 'missing', and this installation"):
        SolverConfig.model_validate({"backend": "missing"})


def test_unregister_removes_entry() -> None:
    solvers.register(fake_adapter("tmp"))
    solvers.unregister("flow", "tmp")
    assert "tmp" not in solvers.names("flow")


def test_the_fake_adapter_satisfies_the_protocol() -> None:
    assert isinstance(FakeAdapter(), SolverAdapter)


def test_the_protocol_answers_for_a_class_as_well_as_an_instance() -> None:
    """``register`` is given classes, so the check has to hold on a class."""
    assert isinstance(FakeAdapter, SolverAdapter)
    assert solvers.register(fake_adapter("as_class")) is solvers.get("flow", "as_class")


def test_a_plain_object_is_not_an_adapter() -> None:
    class NotAnAdapter:
        process_type = "flow"
        name = "plain"

    assert not isinstance(NotAnAdapter(), SolverAdapter)
    with pytest.raises(TypeError, match="does not satisfy the solver backend port"):
        solvers.register(NotAnAdapter)


def test_register_refuses_a_class_that_is_not_an_adapter() -> None:
    half = fake_adapter("half", execute=None, cleanup=None, extract_observables=None)

    with pytest.raises(
        TypeError, match="missing or unusable execute, cleanup, extract_observables"
    ):
        solvers.register(half)
    assert "half" not in solvers.names("flow")


def test_register_refuses_a_member_that_is_present_but_not_callable() -> None:
    """``hasattr`` alone would accept this and let it fail on the first solve."""
    with pytest.raises(TypeError, match="missing or unusable execute"):
        solvers.register(fake_adapter("nonexec", execute=None))


def test_register_refuses_a_class_whose_metaclass_answers_everything() -> None:
    class _AnswersAnything(type):
        def __getattr__(cls, name):
            return lambda *args, **kwargs: None

    class Hollow(metaclass=_AnswersAnything):
        process_type = "flow"
        name = "hollow"

    with pytest.raises(TypeError, match="missing or unusable"):
        solvers.register(Hollow)


def test_register_names_the_key_it_refused() -> None:
    class NotAnAdapter:
        process_type = "flow"
        name = "nothing"

    with pytest.raises(TypeError, match="cannot serve 'flow_nothing'"):
        solvers.register(NotAnAdapter)


def test_an_adapter_that_declares_no_accepted_meshes_is_refused_by_name() -> None:
    """There is no fallback to the regular grid: a plugin that says nothing is refused."""
    with pytest.raises(TypeError, match="missing or unusable accepted_meshes"):
        solvers.register(fake_adapter("meshless", accepted_meshes=None))


class _NotPydantic:
    pass


@pytest.mark.parametrize(
    ("members", "named"),
    [
        ({"geometry": "voxels"}, "geometry is 'voxels', one of cells, raster"),
        ({"category": "global"}, "category is 'global', one of distributed, integrated, lumped"),
        ({"supports": frozenset({"lakes"})}, "supports names lakes, outside the traits"),
        ({"supports": {"lake"}}, "supports is {'lake'}, a frozenset of str"),
        ({"accepted_meshes": ("regular",)}, "accepted_meshes is ('regular',), a frozenset"),
        ({"writes": ["head"]}, "writes is ['head'], a tuple of str"),
        ({"reads": ("face_flow", 1)}, "reads is ('face_flow', 1), a tuple of str"),
        ({"mutable": frozenset({1})}, "mutable is frozenset({1}), a frozenset of str"),
        ({"requires": (("flow",),)}, "requires is (('flow',),), a tuple of (process_type, name)"),
        ({"options": _NotPydantic}, "_NotPydantic'>, a Pydantic model class or None"),
        ({"native_step": "fortnightly"}, "native_step is 'fortnightly', a pandas frequency"),
    ],
    ids=[
        "geometry",
        "category",
        "supports_vocabulary",
        "supports_type",
        "accepted_meshes",
        "writes",
        "reads",
        "mutable",
        "requires",
        "options",
        "native_step",
    ],
)
def test_a_backend_declared_wrongly_is_refused_naming_the_attribute(
    members: dict[str, object], named: str
) -> None:
    with pytest.raises(TypeError, match=re.escape(named)):
        solvers.register(fake_adapter("wrong", **members))
    assert "wrong" not in solvers.names("flow")


@pytest.mark.parametrize("attribute", ["options", "native_step"])
def test_a_nullable_attribute_may_be_none_but_not_absent(attribute: str) -> None:
    solvers.register(fake_adapter("nullable", **{attribute: None}))

    bare = type(
        "Bare",
        (),
        {
            name: value
            for name, value in vars(FakeAdapter).items()
            if name != attribute and not name.startswith("__")
        },
    )
    with pytest.raises(TypeError, match=f"{attribute} is not declared"):
        solvers.register(bare)


def test_a_native_step_pandas_reads_is_accepted() -> None:
    assert solvers.register(fake_adapter("daily", native_step="1D")).native_step == "1D"


# ---------------------------------------------------------------------------
# Instances
# ---------------------------------------------------------------------------


def test_create_returns_a_fresh_instance() -> None:
    solvers.register(fake_adapter("fresh"))
    a = solvers.create("flow", "fresh")
    b = solvers.create("flow", "fresh")
    assert isinstance(a, solvers.get("flow", "fresh"))
    assert a is not b  # one instance per call


def test_create_unknown_raises_a_solver_input_error() -> None:
    with pytest.raises(SolverInputError):
        solvers.create("flow", "missing")


# ---------------------------------------------------------------------------
# Plugin discovery via importlib.metadata entry points
# ---------------------------------------------------------------------------


def test_load_plugins_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(solvers, "plugins_loaded", False)
    solvers.load_plugins()
    assert solvers.load_plugins() == 0


def test_load_plugins_registers_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubEntryPoint("flow_pluginsolver", fake_adapter("pluginsolver"))
    _install(monkeypatch, registry.ENTRY_POINT_GROUP, stub)

    assert solvers.load_plugins(force=True) == 1
    assert "pluginsolver" in solvers.names("flow")


def test_load_plugins_skips_malformed_entry_point_name(monkeypatch: pytest.MonkeyPatch) -> None:
    before = set(solvers.names())
    _install(
        monkeypatch, registry.ENTRY_POINT_GROUP, _StubEntryPoint("no-underscore-here", FakeAdapter)
    )

    assert solvers.load_plugins(force=True) == 0
    assert set(solvers.names()) == before


def test_load_plugins_refuses_a_name_that_contradicts_the_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``flow_modflownwt`` used to mint a second key for ``flow/modflow_nwt``.

    The name was split at its first underscore. It is now compared with the
    join of what the class declares, so a name that drops an underscore names
    nothing.
    """
    published = fake_adapter("modflow_nwt2")
    _install(
        monkeypatch, registry.ENTRY_POINT_GROUP, _StubEntryPoint("flow_modflownwt2", published)
    )

    assert solvers.load_plugins(force=True) == 0
    assert "modflownwt2" not in solvers.names("flow")
    assert "modflow_nwt2" not in solvers.names("flow")


def test_load_plugins_refuses_a_key_it_cannot_read_on_the_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A key computed per instance is not readable on the class, and is refused."""

    class _PerInstanceKey(FakeAdapter):
        @property
        def process_type(self):
            return "flow"

        @property
        def name(self):
            return "perinstance"

    _install(
        monkeypatch,
        registry.ENTRY_POINT_GROUP,
        _StubEntryPoint("flow_perinstance", _PerInstanceKey),
    )

    assert solvers.load_plugins(force=True) == 0
    assert "perinstance" not in solvers.names("flow")


def test_load_plugins_refuses_a_class_that_is_not_an_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NotAnAdapter:
        process_type = "flow"
        name = "broken"

    _install(monkeypatch, registry.ENTRY_POINT_GROUP, _StubEntryPoint("flow_broken", _NotAnAdapter))

    assert solvers.load_plugins(force=True) == 0
    assert "broken" not in solvers.names("flow")


def test_get_extractor_loads_plugin_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = fake_extractor("pluginflow")
    _install(
        monkeypatch,
        registry.EXTRACTOR_ENTRY_POINT_GROUP,
        _StubEntryPoint("flow_pluginflow", extractor),
    )

    assert extractors.get("flow", "pluginflow") is extractor


def test_get_loads_plugin_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    """An out-of-tree adapter resolves on first lookup, with no eager scan."""
    lazy_adapter = fake_adapter("lazyplugin")
    scans = _install(
        monkeypatch,
        registry.ENTRY_POINT_GROUP,
        _StubEntryPoint("flow_lazyplugin", lazy_adapter),
    )

    # A built-in key is served from the dotted-path table without any scan.
    assert solvers.get("flow", "modflow6") is not None
    assert scans == []

    assert solvers.get("flow", "lazyplugin") is lazy_adapter
    assert scans == [registry.ENTRY_POINT_GROUP]
