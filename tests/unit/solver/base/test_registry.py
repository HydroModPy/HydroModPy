"""``solver.base.registry``: the ``solvers`` and ``extractors`` registries and the plugin hook.

A backend is registered once by the class that serves it. Its declared
attributes are checked when it registers, and a plugin is found through the
entry points of the package and refused when it is not an adapter.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import hydromodpy.core.plugin_registry as plugin_registry
from hydromodpy.solver.base import registry
from hydromodpy.solver.base.adapter_protocol import SolverAdapter
from hydromodpy.solver.base.solver_config import SolverConfig
from tests._helpers.fake_solvers import FakeAdapter, fake_adapter

ROOT = Path(__file__).resolve().parents[4]

solvers = registry.solvers
extractors = registry.extractors


@pytest.fixture(autouse=True)
def clean_registry(isolated_solvers):
    """Each test works on a copy of both registries, with the plugin groups marked scanned."""
    return isolated_solvers


class StubEntryPoint:
    def __init__(self, name: str, target: type) -> None:
        self.name = name
        self.target = target

    def load(self) -> type:
        return self.target


def install(monkeypatch: pytest.MonkeyPatch, group: str, *entry_points: StubEntryPoint) -> None:
    """Publish *entry_points* in *group* and mark both registries as not yet scanned."""

    def fake_entry_points(*, group: str):
        return list(entry_points) if group == wanted else []

    wanted = group
    monkeypatch.setattr(plugin_registry, "entry_points", fake_entry_points)
    monkeypatch.setattr(solvers, "plugins_loaded", False)
    monkeypatch.setattr(extractors, "plugins_loaded", False)


class NotPydantic:
    pass


def test_no_second_name_by_plugin() -> None:
    # In-tree backends are declared once, in the registry, never as plugins.
    # ``flow_modflownwt`` used to mint ``flow/modflownwt`` beside
    # ``flow/modflow_nwt``, a key with an adapter but no extractor.
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = pyproject["project"].get("entry-points", {}).get(registry.ENTRY_POINT_GROUP, {})
    for name in declared:
        assert name in extractors.names(), (
            f"entry-point {name!r} declares a key no extractor can read back"
        )


def test_duplicate_needs_replace() -> None:
    solvers.register(fake_adapter("dup"))
    with pytest.raises(ValueError, match="already registered for 'flow_dup'"):
        solvers.register(fake_adapter("dup"))


def test_config_accepts_plugin_solver() -> None:
    solvers.register(fake_adapter("pluginsolver"))

    cfg = SolverConfig.model_validate({"backend": " PluginSolver "})

    assert cfg.backend_name == "pluginsolver"


def test_fake_adapter_fits_protocol() -> None:
    assert isinstance(FakeAdapter(), SolverAdapter)


WRONG_MEMBERS = [
    pytest.param(
        {"geometry": "voxels"}, "geometry is 'voxels', one of cells, raster", id="geometry"
    ),
    pytest.param(
        {"category": "global"},
        "category is 'global', one of distributed, integrated, lumped",
        id="category",
    ),
    pytest.param(
        {"supports": frozenset({"lakes"})},
        "supports names lakes, outside the traits",
        id="supports vocabulary",
    ),
    pytest.param(
        {"supports": {"lake"}}, "supports is {'lake'}, a frozenset of str", id="supports type"
    ),
    pytest.param(
        {"accepted_meshes": ("regular",)},
        "accepted_meshes is ('regular',), a frozenset",
        id="accepted meshes",
    ),
    pytest.param({"writes": ["head"]}, "writes is ['head'], a tuple of str", id="writes"),
    pytest.param(
        {"reads": ("face_flow", 1)}, "reads is ('face_flow', 1), a tuple of str", id="reads"
    ),
    pytest.param(
        {"mutable": frozenset({1})}, "mutable is frozenset({1}), a frozenset of str", id="mutable"
    ),
    pytest.param(
        {"requires": (("flow",),)},
        "requires is (('flow',),), a tuple of (process_type, name)",
        id="requires",
    ),
    pytest.param(
        {"options": NotPydantic},
        "NotPydantic'>, a Pydantic model class or None",
        id="options",
    ),
    pytest.param(
        {"native_step": "fortnightly"},
        "native_step is 'fortnightly', a pandas frequency",
        id="native step",
    ),
]


@pytest.mark.parametrize(("members", "named"), WRONG_MEMBERS)
def test_wrong_declaration(members: dict[str, object], named: str) -> None:
    with pytest.raises(TypeError, match=re.escape(named)):
        solvers.register(fake_adapter("wrong", **members))
    assert "wrong" not in solvers.names("flow")


@pytest.mark.parametrize("attribute", ["options", "native_step"])
def test_nullable_attribute(attribute: str) -> None:
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


def test_plugin_not_an_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    class NotAnAdapter:
        process_type = "flow"
        name = "broken"

    install(monkeypatch, registry.ENTRY_POINT_GROUP, StubEntryPoint("flow_broken", NotAnAdapter))

    assert solvers.load_plugins(force=True) == 0
    assert "broken" not in solvers.names("flow")
