"""Unit tests for ``hydromodpy.solver.base.registry``."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from hydromodpy.solver.base import registry
from hydromodpy.solver.base.solver_config import SolverConfig

ROOT = Path(__file__).resolve().parents[3]


class FakeAdapter:
    process_type = "flow"
    solver_name = "fake"
    requires: tuple[tuple[str, str], ...] = ()

    def validate(self, ctx):
        pass

    def execute(self, ctx):
        return None

    def cleanup(self, ctx):
        pass

    def extract_calibration_series(self, ctx, store, **kwargs):
        import pandas as pd

        return pd.Series(dtype=float)


class AnotherFakeAdapter(FakeAdapter):
    pass


class FakeExtractor:
    def extract(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot the registry and restore it after each test.

    Both the eager ``_REGISTRY`` cache and the lazy ``_BUILTIN_PATHS``
    map are isolated so tests can mutate either without leaking state.
    """
    eager = dict(registry._REGISTRY)
    lazy = dict(registry._BUILTIN_PATHS)
    capabilities = dict(registry._BUILTIN_CAPABILITIES)
    extractor_eager = dict(registry._EXTRACTOR_REGISTRY)
    extractor_lazy = dict(registry._BUILTIN_EXTRACTOR_PATHS)
    plugins_loaded = registry._PLUGINS_LOADED
    extractor_plugins_loaded = registry._EXTRACTOR_PLUGINS_LOADED
    try:
        yield
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(eager)
        registry._BUILTIN_PATHS.clear()
        registry._BUILTIN_PATHS.update(lazy)
        registry._BUILTIN_CAPABILITIES.clear()
        registry._BUILTIN_CAPABILITIES.update(capabilities)
        registry._EXTRACTOR_REGISTRY.clear()
        registry._EXTRACTOR_REGISTRY.update(extractor_eager)
        registry._BUILTIN_EXTRACTOR_PATHS.clear()
        registry._BUILTIN_EXTRACTOR_PATHS.update(extractor_lazy)
        registry._PLUGINS_LOADED = plugins_loaded
        registry._EXTRACTOR_PLUGINS_LOADED = extractor_plugins_loaded


def test_every_declared_backend_has_an_extractor() -> None:
    """A backend the config can select must still be readable after the solve.

    An adapter without an extractor solves, then loses the run at ingestion.
    """
    orphans = sorted(
        pair for pair in registry.list_pairs() if pair not in registry.list_extractor_pairs()
    )
    assert orphans == []


def test_no_entry_point_gives_a_backend_a_second_name() -> None:
    """In-tree backends are declared once, in the registry, never as plugins.

    ``flow_modflownwt`` split into ``flow/modflownwt`` (the loader cuts the
    name at the first underscore), a pair with an adapter but no extractor.
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = pyproject["project"].get("entry-points", {}).get(registry.ENTRY_POINT_GROUP, {})
    for name in declared:
        process_type, _, solver_name = name.partition("_")
        assert (process_type, solver_name) in registry.list_extractor_pairs(), (
            f"entry-point {name!r} declares {process_type}/{solver_name}, "
            "a pair no extractor can read back"
        )


def test_register_and_get_returns_cls() -> None:
    registry.register("flow", "fake", FakeAdapter)
    assert registry.get("flow", "fake") is FakeAdapter


def test_register_duplicate_raises_without_replace() -> None:
    registry.register("flow", "dup", FakeAdapter)
    with pytest.raises(ValueError):
        registry.register("flow", "dup", FakeAdapter)


def test_register_duplicate_with_replace_overwrites() -> None:
    registry.register("flow", "dup2", FakeAdapter)
    registry.register("flow", "dup2", AnotherFakeAdapter, replace=True)
    assert registry.get("flow", "dup2") is AnotherFakeAdapter


def test_get_unknown_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        registry.get("flow", "nope")


def test_list_pairs_is_sorted() -> None:
    registry._REGISTRY.clear()
    registry._BUILTIN_PATHS.clear()
    registry.register("flow", "b", FakeAdapter)
    registry.register("flow", "a", FakeAdapter)
    registry.register("transport", "c", FakeAdapter)
    assert registry.list_pairs() == [("flow", "a"), ("flow", "b"), ("transport", "c")]


def test_pairs_for_process_filters_by_type() -> None:
    registry._REGISTRY.clear()
    registry._BUILTIN_PATHS.clear()
    registry.register("flow", "a", FakeAdapter)
    registry.register("transport", "b", FakeAdapter)
    assert list(registry.pairs_for_process("flow")) == [("flow", "a")]


def test_builtin_process_types_exclude_workflow_stub_phases() -> None:
    assert "postprocess" not in registry.known_process_types()
    assert "display" not in registry.known_process_types()


def test_transport_capabilities_are_explicit() -> None:
    assert registry.capabilities("transport", "modpath") == frozenset(
        {"transport", "transport:particles"}
    )
    assert registry.capabilities("transport", "mt3dms") == frozenset(
        {"transport", "transport:concentration"}
    )
    assert registry.capabilities("transport", "modflow6") == frozenset(
        {"transport", "transport:concentration"}
    )
    assert registry.capabilities("transport", "modflow6_prt") == frozenset(
        {"transport", "transport:particles"}
    )


def test_modflow6_prt_adapter_and_extractor_are_registered() -> None:
    adapter_cls = registry.get("transport", "modflow6_prt")
    extractor_cls = registry.get_extractor("transport", "modflow6_prt")

    assert adapter_cls.__name__ == "Modflow6PrtTransportAdapter"
    assert extractor_cls.__name__ == "Modflow6PrtOutputAdapter"


def test_solver_config_accepts_registered_plugin_flow_solver() -> None:
    registry.register("flow", "pluginsolver", FakeAdapter)

    cfg = SolverConfig.model_validate({"backend": {"backend": "custom", "name": "pluginsolver"}})

    assert cfg.backend_name == "pluginsolver"


def test_solver_config_rejects_unknown_flow_solver() -> None:
    cfg = SolverConfig.model_validate({"backend": {"backend": "custom", "name": "missing"}})
    with pytest.raises(ValueError, match="Unknown flow solver"):
        cfg.validate_registry()


def test_unregister_removes_entry() -> None:
    registry.register("flow", "tmp", FakeAdapter)
    registry.unregister("flow", "tmp")
    assert ("flow", "tmp") not in registry.list_pairs()


def test_is_adapter_true_for_fake_adapter() -> None:
    assert registry.is_adapter(FakeAdapter())


def test_is_adapter_false_for_plain_object() -> None:
    class NotAnAdapter:
        pass

    assert not registry.is_adapter(NotAnAdapter())


# ---------------------------------------------------------------------------
# Instance retrieval (merged registry contract)
# ---------------------------------------------------------------------------


def test_get_solver_adapter_returns_fresh_instance() -> None:
    registry.register("flow", "fresh", FakeAdapter)
    a = registry.get_solver_adapter("flow", "fresh")
    b = registry.get_solver_adapter("flow", "fresh")
    assert isinstance(a, FakeAdapter)
    assert isinstance(b, FakeAdapter)
    assert a is not b  # one instance per call


def test_get_solver_adapter_unknown_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        registry.get_solver_adapter("flow", "missing")


# ---------------------------------------------------------------------------
# Plugin discovery via importlib.metadata entry-points
# ---------------------------------------------------------------------------


def test_load_plugins_is_idempotent() -> None:
    # First call may register the in-repo entry-points (zero or more); the
    # second call must always return 0 because _PLUGINS_LOADED is set.
    registry.load_plugins()
    assert registry.load_plugins() == 0


def test_load_plugins_registers_entry_point(monkeypatch) -> None:
    # Reset the loaded marker so the function is allowed to run again.
    monkeypatch.setattr(registry, "_PLUGINS_LOADED", False)

    class _StubEntryPoint:
        def __init__(self, name: str, target: type) -> None:
            self.name = name
            self._target = target

        def load(self) -> type:
            return self._target

    stub = _StubEntryPoint("flow_pluginsolver", FakeAdapter)

    def _fake_entry_points(*, group: str):
        assert group == registry.ENTRY_POINT_GROUP
        return [stub]

    monkeypatch.setattr(registry, "entry_points", _fake_entry_points)
    count = registry.load_plugins(force=True)
    assert count >= 1
    assert ("flow", "pluginsolver") in registry.list_pairs()


def test_load_plugins_skips_malformed_entry_point_name(monkeypatch) -> None:
    monkeypatch.setattr(registry, "_PLUGINS_LOADED", False)

    class _StubEntryPoint:
        name = "no-underscore-here"

        def load(self) -> type:
            return FakeAdapter

    monkeypatch.setattr(
        registry,
        "entry_points",
        lambda *, group: [_StubEntryPoint()],
    )
    pairs_before = set(registry.list_pairs())
    count = registry.load_plugins(force=True)
    pairs_after = set(registry.list_pairs())
    # Malformed entry-points must not pollute the registry.
    assert count == 0
    assert pairs_after == pairs_before


def test_get_extractor_loads_plugin_lazily(monkeypatch) -> None:
    monkeypatch.setattr(registry, "_EXTRACTOR_PLUGINS_LOADED", False)

    class _StubEntryPoint:
        name = "flow_pluginflow"

        def load(self) -> type:
            return FakeExtractor

    monkeypatch.setattr(
        registry,
        "entry_points",
        lambda *, group: (
            [_StubEntryPoint()] if group == registry.EXTRACTOR_ENTRY_POINT_GROUP else []
        ),
    )

    assert registry.get_extractor("flow", "pluginflow") is FakeExtractor


def test_get_loads_plugin_lazily(monkeypatch) -> None:
    """An out-of-tree adapter resolves on first lookup, with no eager scan."""
    monkeypatch.setattr(registry, "_PLUGINS_LOADED", False)
    scans: list[str] = []

    class _StubEntryPoint:
        name = "flow_lazyplugin"

        def load(self) -> type:
            return FakeAdapter

    def _fake_entry_points(*, group: str):
        scans.append(group)
        return [_StubEntryPoint()] if group == registry.ENTRY_POINT_GROUP else []

    monkeypatch.setattr(registry, "entry_points", _fake_entry_points)

    # A built-in pair is served from the dotted-path table without any scan.
    assert registry.get("flow", "modflow6") is not None
    assert scans == []

    assert registry.get("flow", "lazyplugin") is FakeAdapter
    assert scans == [registry.ENTRY_POINT_GROUP]
