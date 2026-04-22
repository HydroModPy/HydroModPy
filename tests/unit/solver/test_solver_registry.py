"""Unit tests for ``hydromodpy.solver.base.registry``."""

from __future__ import annotations

import pytest

from hydromodpy.solver.base import registry
from hydromodpy.solver.base.protocol import RunResult


class FakeAdapter:
    process_type = "flow"
    solver_name = "fake"

    def setup(self, config):
        pass

    def build(self, plan):
        pass

    def run(self):
        return RunResult(converged=True)

    def extract(self, store):
        pass

    def cleanup(self):
        pass


class AnotherFakeAdapter(FakeAdapter):
    pass


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot the registry and restore it after each test."""
    snapshot = dict(registry._REGISTRY)
    try:
        yield
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(snapshot)


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
    registry.register("flow", "b", FakeAdapter)
    registry.register("flow", "a", FakeAdapter)
    registry.register("transport", "c", FakeAdapter)
    assert registry.list_pairs() == [("flow", "a"), ("flow", "b"), ("transport", "c")]


def test_pairs_for_process_filters_by_type() -> None:
    registry._REGISTRY.clear()
    registry.register("flow", "a", FakeAdapter)
    registry.register("transport", "b", FakeAdapter)
    assert list(registry.pairs_for_process("flow")) == [("flow", "a")]


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
