"""The solver-registry provider is installed once and read through a getter."""

from __future__ import annotations

import pytest

from hydromodpy.core.contracts import solver_registry


def test_a_missing_provider_raises_instead_of_returning_none(monkeypatch) -> None:
    monkeypatch.setattr(solver_registry, "_PROVIDER", None)

    with pytest.raises(RuntimeError, match="not installed"):
        solver_registry.get_solver_registry_provider()


def test_the_installed_provider_is_the_one_returned(monkeypatch) -> None:
    monkeypatch.setattr(solver_registry, "_PROVIDER", None)
    provider = object()

    solver_registry.set_solver_registry_provider(provider)  # type: ignore[arg-type]

    assert solver_registry.get_solver_registry_provider() is provider
