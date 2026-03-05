"""Discovers and calls user-defined hooks from a ``hooks.py`` file.

Convention
----------
Place a ``hooks.py`` file in the same directory as your ``config.toml``.
Define functions named ``on_before_<phase>`` or ``on_after_<phase>``; they
receive a single :class:`LauncherRunState` argument and return ``None``.

Any hook name not present in ``hooks.py`` is silently ignored (no-op).
Exceptions raised inside a hook are re-raised as :class:`HookError` with the
original traceback attached.

Example ``hooks.py``::

    from launchers import LauncherRunState

    def on_before_flow(result: LauncherRunState) -> None:
        result.setup.flow.set_recharge(...)
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from launchers.process_simulation.run_state import LauncherRunState

KNOWN_HOOKS: list[str] = [
    "on_before_setup",
    "on_after_setup",
    "on_before_data",
    "on_after_data",
    "on_before_flow",
    "on_after_flow",
    "on_before_transport",
    "on_after_transport",
]


class HookError(RuntimeError):
    """Raised when a user hook raises an exception."""


class HookRegistry:
    """Holds references to hook callables discovered from a ``hooks.py`` file."""

    def __init__(self) -> None:
        self._hooks: dict[str, Callable] = {}

    @classmethod
    def discover(cls, config_path: Path) -> "HookRegistry":
        """Load ``hooks.py`` from the same directory as *config_path*.

        Returns an empty registry (all no-ops) if ``hooks.py`` is absent.
        """
        registry = cls()
        hooks_path = Path(config_path).parent / "hooks.py"
        if not hooks_path.exists():
            return registry

        spec = importlib.util.spec_from_file_location("_hmp_hooks", hooks_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for name in KNOWN_HOOKS:
            fn = getattr(module, name, None)
            if fn is not None and callable(fn):
                registry._hooks[name] = fn

        loaded = [n for n in KNOWN_HOOKS if n in registry._hooks]
        if loaded:
            print(f"[HookRegistry] Loaded from {hooks_path.name}: {', '.join(loaded)}")

        return registry

    def call(self, name: str, result: "LauncherRunState") -> None:
        """Call the hook named *name* with *result*, or do nothing if absent."""
        fn = self._hooks.get(name)
        if fn is None:
            return
        try:
            fn(result)
        except Exception as exc:
            raise HookError(
                f"Hook '{name}' raised an exception in hooks.py"
            ) from exc
