"""Shared fixtures for validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATION_CASES_ROOT = REPO_ROOT / "validation_cases"


@pytest.fixture(scope="session")
def validation_cases_root() -> Path:
    """Return the repository root that contains validation cases."""
    return VALIDATION_CASES_ROOT
