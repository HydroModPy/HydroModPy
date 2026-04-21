"""Fixtures and configuration specific to the e2e tier."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def e2e_workspace(tmp_path: Path) -> Path:
    """Provide an isolated workspace directory for an e2e scenario."""
    wsp = tmp_path / "workspace"
    wsp.mkdir(parents=True, exist_ok=True)
    return wsp
