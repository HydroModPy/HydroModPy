"""A fake solver backend and a fake extractor, for the registry, the runner and the post-run step.

``FakeAdapter`` declares the twelve attributes of ``SolverAdapter`` and its four
methods, as a flow backend named ``fake`` on the cell mesh. ``fake_adapter``
makes a new class from it, under another key or with any attribute or method
replaced. ``FakeExtractor`` and ``fake_extractor`` do the same for the extractor
of a key. Register them through the ``isolated_solvers`` fixture of
``tests/conftest.py``. Not public API.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel

__all__ = [
    "FakeAdapter",
    "FakeExtractor",
    "fake_adapter",
    "fake_extractor",
]


class FakeAdapter:
    """A flow backend that solves nothing and records the calls the runner makes."""

    name: ClassVar[str] = "fake"
    process_type: ClassVar[str] = "flow"
    accepted_meshes: ClassVar[frozenset[str]] = frozenset({"regular"})
    geometry: ClassVar[str] = "cells"
    writes: ClassVar[tuple[str, ...]] = ("head",)
    reads: ClassVar[tuple[str, ...]] = ()
    supports: ClassVar[frozenset[str]] = frozenset({"head_rule", "steady_start"})
    options: ClassVar[type[BaseModel] | None] = None
    category: ClassVar[str] = "distributed"
    native_step: ClassVar[str | None] = None
    mutable: ClassVar[frozenset[str]] = frozenset()
    requires: ClassVar[tuple[tuple[str, str], ...]] = ()

    def __init__(self) -> None:
        self.calls: list[str] = []

    def validate(self, ctx: Any) -> None:
        self.calls.append("validate")

    def execute(self, ctx: Any) -> Any:
        self.calls.append("execute")
        return None

    def cleanup(self, ctx: Any) -> None:
        self.calls.append("cleanup")

    def extract_observables(
        self, ctx: Any, store: Any, requests: Any, **kwargs: Any
    ) -> dict[str, Any]:
        self.calls.append("extract_observables")
        return {}


def fake_adapter(name: str = "fake", process_type: str = "flow", **members: object) -> type:
    """Return a new ``FakeAdapter`` class keyed ``<process_type>_<name>``.

    *members* replace attributes or methods; ``None`` leaves a member unusable,
    which the registry refuses.
    """
    attributes: dict[str, object] = {"name": name, "process_type": process_type, **members}
    return type(f"FakeAdapter[{process_type}_{name}]", (FakeAdapter,), attributes)


class FakeExtractor:
    """An extractor that reads nothing and counts its calls."""

    process_type: ClassVar[str] = "flow"
    solver_name: ClassVar[str] = "fake"
    calls: ClassVar[int] = 0

    def extract(self, *args: object, **kwargs: object) -> None:
        type(self).calls += 1


def fake_extractor(
    solver_name: str = "fake", process_type: str = "flow", **members: object
) -> type:
    """Return a new ``FakeExtractor`` class for ``<process_type>_<solver_name>``, with no call yet."""
    attributes: dict[str, object] = {
        "solver_name": solver_name,
        "process_type": process_type,
        "calls": 0,
        **members,
    }
    return type(f"FakeExtractor[{process_type}_{solver_name}]", (FakeExtractor,), attributes)
