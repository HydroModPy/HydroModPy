"""Protocol decoupling the TOML generator from physics/spatial.

The 14x14 layer matrix forbids ``core -> physics`` and ``core -> spatial``.
The TOML scaffolding generator emits documented examples for the dynamic
``[flow.param.*]``, ``[flow.bc.*]`` and ``[flow.sinks_sources.*]`` blocks
that depend on classes living in those layers. The provider below is wired in
at package bootstrap by :mod:`hydromodpy._bootstrap`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class DynamicFlowExamplesProvider(Protocol):
    """Render commented TOML example blocks for the dynamic flow sections."""

    def render(self, threshold: int, section_renderer: Callable) -> list[str]:
        """Return the list of lines for the dynamic flow examples."""


_PROVIDER: DynamicFlowExamplesProvider | None = None


def set_dynamic_flow_examples_provider(provider: DynamicFlowExamplesProvider) -> None:
    """Install the dynamic-flow examples provider used by the TOML generator."""
    global _PROVIDER
    _PROVIDER = provider


def get_dynamic_flow_examples_provider() -> DynamicFlowExamplesProvider | None:
    """Return the installed provider or ``None`` when not yet wired."""
    return _PROVIDER


__all__ = (
    "DynamicFlowExamplesProvider",
    "get_dynamic_flow_examples_provider",
    "set_dynamic_flow_examples_provider",
)
