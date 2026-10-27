"""Fixtures of the planner tests: the built-in engines as the planner sees them."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests._helpers.fake_engines import patch_builtin_engines


@pytest.fixture
def builtin_engines(monkeypatch: pytest.MonkeyPatch) -> dict[str, SimpleNamespace]:
    """Make ``registry.get`` answer the capabilities of the built-in engines, without importing them.

    A test file of the planner asks for it with
    ``pytestmark = pytest.mark.usefixtures("builtin_engines")``.
    """
    return patch_builtin_engines(monkeypatch)
