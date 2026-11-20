"""Skip a validation test when the Linux PETSc runtime is missing."""

from __future__ import annotations

import platform

import pytest


def require_linux_petsc4py() -> None:
    """Skip the calling test off Linux or without ``petsc4py``."""
    if platform.system().strip().lower() != "linux":
        pytest.skip("Boussinesq PETSc runtime is Linux-only.")
    pytest.importorskip("petsc4py")
