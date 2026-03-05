"""Materialize process-level runtime objects from validated config.

This factory centralizes the creation of shared process objects (`flow`,
`transport`) so orchestration layers can request them without duplicating
construction logic.
"""

from __future__ import annotations

from typing import Any, Protocol

from hydromodpy.process import Flow, Transport

_REQUIRED_COMPONENTS_BY_PROCESS: dict[str, tuple[str, ...]] = {
    "flow": ("flow",),
    # Transport hooks and adapters commonly need both transport settings and
    # the shared flow process context.
    "transport": ("flow", "transport"),
}


class ProcessContextState(Protocol):
    """Minimal state shape required to materialize process objects."""

    cfg: Any
    setup: Any


class ProcessContextFactory:
    """Idempotent factory for process-level runtime objects."""

    def ensure_for_process(self, state: ProcessContextState, process_type: str) -> None:
        """Ensure all process objects required by ``process_type`` exist."""

        components = _REQUIRED_COMPONENTS_BY_PROCESS.get(process_type)
        if components is None:
            supported = ", ".join(sorted(_REQUIRED_COMPONENTS_BY_PROCESS))
            raise ValueError(
                f"Unsupported process type '{process_type}'. Supported process types: {supported}."
            )
        for component_name in components:
            self._ensure_component(state, component_name)

    def ensure_flow(self, state: ProcessContextState) -> None:
        """Create ``state.setup.flow`` from ``state.cfg.flow`` when missing."""

        if state.setup.flow is None:
            state.setup.flow = Flow(config=state.cfg.flow)

    def ensure_transport(self, state: ProcessContextState) -> None:
        """Create ``state.setup.transport`` from ``state.cfg.transport`` when missing."""

        if state.setup.transport is None:
            state.setup.transport = Transport(config=state.cfg.transport)

    def _ensure_component(self, state: ProcessContextState, component_name: str) -> None:
        if component_name == "flow":
            self.ensure_flow(state)
            return
        if component_name == "transport":
            self.ensure_transport(state)
            return
        raise ValueError(f"Unsupported process component '{component_name}'.")
