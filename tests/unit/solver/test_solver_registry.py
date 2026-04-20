"""Unit tests for ``hydromodpy.solver.base.registry``."""

from __future__ import annotations

import pytest

from hydromodpy.solver.base import registry
from hydromodpy.solver.base.protocol import RunResult


class FakeAdapter:
    process_type = "flow"
    solver_name = "fake"

    def setup(self, config): pass
    def build(self, plan): pass
    def run(self): return RunResult(converged=True)
    def extract(self, store): pass
    def cleanup(self): pass


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
