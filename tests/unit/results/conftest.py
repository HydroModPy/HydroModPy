"""Fixtures shared by the results tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path / "workspace"
