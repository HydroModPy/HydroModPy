"""Rerun provider contract.

The catalog (``results`` layer) must not import ``project``/``workflow`` to
re-launch a run. It calls a :class:`RerunProvider` registered at bootstrap by
the ``project`` layer (same inversion as the calibration trial providers), so
the dependency points the allowed direction (project -> results).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class RerunProvider(Protocol):
    """Re-launch a simulation from a stored config snapshot with overrides."""

    def rerun(
        self,
        snapshot: Mapping[str, Any],
        *,
        overrides: Mapping[str, Any],
        name: str | None,
        source_sim_id: str | None = None,
    ) -> str:
        """Run a fresh simulation and return its new ``sim_id``.

        ``source_sim_id`` is pinned as the child's ``parent_sim_id`` for lineage.
        """


_provider: RerunProvider | None = None


def register_rerun_provider(provider: RerunProvider) -> None:
    """Register the workflow-backed provider used by ``catalog.rerun``."""
    global _provider
    _provider = provider


def get_rerun_provider() -> RerunProvider:
    """Return the registered rerun provider, or raise if none is wired."""
    if _provider is None:
        raise RuntimeError(
            "RerunProvider is not registered. Import 'hydromodpy' "
            "(or call hydromodpy.bootstrap()) before re-running simulations."
        )
    return _provider


__all__ = ["RerunProvider", "register_rerun_provider", "get_rerun_provider"]
