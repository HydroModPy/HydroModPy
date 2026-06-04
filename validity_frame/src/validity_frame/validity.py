"""Implementation of a minimal validity frame external package.

This module does not depend on HydroModPy. It uses duck-typing on the
`state` object (it must expose the attributes required by your rules).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class ValidityFrame:
    """Minimal API: `verify(state, steps)`."""

    def __init__(self, *, tolerant: bool = False) -> None:
        self.tolerant = bool(tolerant)

    def verify(self, state: Any, steps: Iterable) -> None:
        """Check some simple, generic invariants.

        Adjust these checks according to your model or calling project.
        """
        try:
            if getattr(state, "run_id", None) is None:
                raise RuntimeError("validity: missing run_id")

            if not hasattr(steps, "__iter__"):
                raise RuntimeError("validity: steps must be iterable")

            data = getattr(state, "data", None)
            if data in (None, {}, ""):
                raise RuntimeError("validity: state.data is empty or missing")
        except Exception:
            if self.tolerant:
                return
            else:
                raise
