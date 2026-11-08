"""Unit tests for process-context materialization functions."""

from types import SimpleNamespace

import pytest

from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.transport.transport import Transport
from hydromodpy.model.transport.transport_config import TransportConfig
from hydromodpy.solver.base.runner import ensure_process_context, ensure_transport


def _build_state(*, flow=None, transport=None) -> SimpleNamespace:
    return SimpleNamespace(
        cfg=SimpleNamespace(
            flow=FlowConfig(),
            transport=TransportConfig(),
        ),
        setup=SimpleNamespace(
            flow=flow,
            transport=transport,
        ),
    )


def test_ensure_transport_is_idempotent() -> None:
    state = _build_state()

    ensure_transport(state)
    first_transport = state.setup.transport
    ensure_transport(state)

    assert isinstance(state.setup.transport, Transport)
    assert state.setup.transport is first_transport


def test_ensure_process_context_transport_creates_the_transport_and_leaves_the_flow() -> None:
    """The flow is made by the setup step, never by the runner."""
    state = _build_state()

    ensure_process_context(state, "transport")

    assert state.setup.flow is None
    assert isinstance(state.setup.transport, Transport)


@pytest.mark.parametrize("process_type", ["flow", "postprocess"])
def test_ensure_process_context_creates_nothing_for_a_process_without_components(
    process_type: str,
) -> None:
    """A flow run needs no component the runner could create, and an unknown type none at all."""
    state = _build_state()

    ensure_process_context(state, process_type)

    assert state.setup.flow is None
    assert state.setup.transport is None
