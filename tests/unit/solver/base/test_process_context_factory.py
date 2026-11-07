"""Unit tests for process-context materialization functions."""

from types import SimpleNamespace

from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.model import Flow
from hydromodpy.model.transport.transport import Transport
from hydromodpy.model.transport.transport_config import TransportConfig
from hydromodpy.solver.base.runner import ensure_flow, ensure_process_context, ensure_transport


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


def test_ensure_flow_is_idempotent() -> None:
    state = _build_state()

    ensure_flow(state)
    first_flow = state.setup.flow
    ensure_flow(state)

    assert isinstance(state.setup.flow, Flow)
    assert state.setup.flow is first_flow


def test_ensure_process_context_transport_creates_flow_and_transport() -> None:
    state = _build_state()

    ensure_process_context(state, "transport")

    assert isinstance(state.setup.flow, Flow)
    assert isinstance(state.setup.transport, Transport)


def test_ensure_process_context_accepts_unknown_type_as_noop() -> None:
    """Unknown process types are silently accepted (no components to create)."""
    state = _build_state()

    ensure_process_context(state, "postprocess")

    assert state.setup.flow is None
    assert state.setup.transport is None
