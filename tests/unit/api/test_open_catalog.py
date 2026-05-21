"""Unit tests for ``hmp.open_catalog``."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy.catalog import CatalogFacade

pytestmark = pytest.mark.fast


def test_open_catalog_returns_facade(tmp_path: Path) -> None:
    """``hmp.open_catalog`` returns a CatalogFacade bound to the workspace."""
    facade = hmp.open_catalog(tmp_path)
    try:
        assert isinstance(facade, CatalogFacade)
        assert facade.workspace == tmp_path.resolve()
    finally:
        facade.close()


def test_open_catalog_is_context_manager(tmp_path: Path) -> None:
    """The returned facade works as a context manager."""
    with hmp.open_catalog(tmp_path) as facade:
        assert isinstance(facade, CatalogFacade)
        assert hasattr(facade, "simulations")
        assert hasattr(facade, "inputs")
        assert hasattr(facade, "projects")


def test_open_catalog_uses_env_var(monkeypatch, tmp_path: Path) -> None:
    """``hmp.open_catalog(None)`` falls back to ``HMP_WORKSPACE``."""
    monkeypatch.setenv("HMP_WORKSPACE", str(tmp_path))
    with hmp.open_catalog() as facade:
        assert facade.workspace == tmp_path.resolve()


def test_open_catalog_falls_back_to_cwd(monkeypatch, tmp_path: Path) -> None:
    """Without env var nor argument, the facade points at cwd."""
    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    with hmp.open_catalog() as facade:
        assert facade.workspace == tmp_path.resolve()
