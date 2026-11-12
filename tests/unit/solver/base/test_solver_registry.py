"""Unit tests for ``hydromodpy.solver.base.registry``: ``solvers``, ``extractors`` and the backend hook."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import hydromodpy.core.plugin_registry as plugin_registry
from hydromodpy.mesh.port import ANY_PLANAR_ENGINE
from hydromodpy.model.transport.transport_config import (
    ConcentrationTransportParametersConfig,
    Modflow6PrtParametersConfig,
    ModpathParametersConfig,
)
from hydromodpy.solver.base import registry
from hydromodpy.solver.base.adapter_protocol import SolverAdapter
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.boussinesq.options import BoussinesqOptions
from hydromodpy.solver.linear_reservoir.options import LinearReservoirOptions
from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
from hydromodpy.solver.modflow_nwt.nwt.nwt_config import ModflowConfig
from tests._helpers.fake_solvers import FakeAdapter, fake_adapter

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


DECLARED = {
    "flow_modflow6": {
        "accepted_meshes": frozenset({"regular", "triangle", "voronoi", ANY_PLANAR_ENGINE}),
        "geometry": "cells",
        "category": "distributed",
        "options": Modflow6Config,
        "requires": (),
        "reads": (),
        "surface_excess": False,
        "mutable": frozenset({"K", "Sy"}),
    },
    "flow_modflow_nwt": {
        "accepted_meshes": frozenset({"regular"}),
        "geometry": "raster",
        "category": "distributed",
        "options": ModflowConfig,
        "requires": (),
        "reads": (),
        "surface_excess": False,
        "mutable": frozenset(),
    },
    "flow_boussinesq": {
        "accepted_meshes": frozenset({"triangle"}),
        "geometry": "cells",
        "category": "integrated",
        "options": BoussinesqOptions,
        "requires": (),
        "reads": (),
        "surface_excess": True,
        "mutable": frozenset(),
    },
    "flow_linear_reservoir": {
        "accepted_meshes": frozenset({"catchment"}),
        "geometry": "cells",
        "category": "lumped",
        "options": LinearReservoirOptions,
        "requires": (),
        "reads": (),
        "surface_excess": False,
        "mutable": frozenset(),
    },
    "transport_modflow6": {
        "accepted_meshes": frozenset(),
        "geometry": "cells",
        "category": "distributed",
        "options": ConcentrationTransportParametersConfig,
        "requires": (("flow", "modflow6"),),
        "reads": ("face_flow",),
        "surface_excess": False,
        "mutable": frozenset(),
    },
    "transport_modflow6_prt": {
        "accepted_meshes": frozenset(),
        "geometry": "cells",
        "category": "distributed",
        "options": Modflow6PrtParametersConfig,
        "requires": (("flow", "modflow6"),),
        "reads": ("face_flow",),
        "surface_excess": False,
        "mutable": frozenset(),
    },
    "transport_mt3dms": {
        "accepted_meshes": frozenset(),
        "geometry": "raster",
        "category": "distributed",
        "options": ConcentrationTransportParametersConfig,
        "requires": (("flow", "modflow_nwt"),),
        "reads": ("face_flow",),
        "surface_excess": False,
        "mutable": frozenset(),
    },
    "transport_modpath": {
        "accepted_meshes": frozenset(),
        "geometry": "raster",
        "category": "distributed",
        "options": ModpathParametersConfig,
        "requires": (("flow", "modflow_nwt"),),
        "reads": ("face_flow",),
        "surface_excess": False,
        "mutable": frozenset(),
    },
}
"""What each backend of the build declares. The extractor categories and the index
table held these values before the attributes moved to the adapter, and the
mesh, requires and surface-excess rows are what the configuration and the
planner read. Only MODFLOW 6 reruns a built model, for K and Sy. The linear
reservoir is the one lumped flow, on the one cell of the catchment engine."""


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_duplicate_raises_without_replace() -> None:
    solvers.register(fake_adapter("dup"))
    with pytest.raises(ValueError, match="already registered for 'flow_dup'"):
        solvers.register(fake_adapter("dup"))


def test_solver_config_accepts_registered_plugin_flow_solver() -> None:
    solvers.register(fake_adapter("pluginsolver"))

    cfg = SolverConfig.model_validate({"backend": " PluginSolver "})

    assert cfg.backend_name == "pluginsolver"


def test_the_fake_adapter_satisfies_the_protocol() -> None:
    assert isinstance(FakeAdapter(), SolverAdapter)


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


# ---------------------------------------------------------------------------
# Instances
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Plugin discovery via importlib.metadata entry points
# ---------------------------------------------------------------------------


def test_load_plugins_refuses_a_class_that_is_not_an_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NotAnAdapter:
        process_type = "flow"
        name = "broken"

    _install(monkeypatch, registry.ENTRY_POINT_GROUP, _StubEntryPoint("flow_broken", _NotAnAdapter))

    assert solvers.load_plugins(force=True) == 0
    assert "broken" not in solvers.names("flow")
