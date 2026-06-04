"""Lazy bootstrap trigger shared across layers.

The root ``hydromodpy._bootstrap`` registers its ``bootstrap`` callable here at
import time (cheap: it only stores a reference). Layers that need the fully
wired config / DI graph (config validation, the functional verbs, ``Project``,
the CLI) call :func:`ensure_bootstrapped` instead of importing the root
``_bootstrap`` module, which would be a forbidden upward import edge.

Deferring the heavy bootstrap from package import to first real use keeps
``import hydromodpy`` and ``hmp --help`` fast.
"""

from __future__ import annotations

from collections.abc import Callable

_HOOK: Callable[[], None] | None = None


def set_bootstrap_hook(hook: Callable[[], None]) -> None:
    """Register the bootstrap callable (called once by the root package)."""
    global _HOOK
    _HOOK = hook


def ensure_bootstrapped() -> None:
    """Run the registered bootstrap once. No-op if already done or unset."""
    if _HOOK is not None:
        _HOOK()


__all__ = ["ensure_bootstrapped", "set_bootstrap_hook"]
