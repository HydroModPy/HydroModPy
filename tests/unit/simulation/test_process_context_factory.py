"""Unit tests for process-context materialization."""

from types import SimpleNamespace

import pytest

from hydromodpy.process import Flow, Transport
from hydromodpy.process.flow.flow_config import FlowConfig
from hydromodpy.process.transport.transport_config import TransportConfig
from hydromodpy.simulation.runtime.runner import ProcessContextFactory


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
    factory = ProcessContextFactory()
    state = _build_state()

    factory.ensure_flow(state)
    first_flow = state.setup.flow
    factory.ensure_flow(state)

    assert isinstance(state.setup.flow, Flow)
    assert state.setup.flow is first_flow


def test_ensure_for_transport_process_creates_flow_and_transport() -> None:
    factory = ProcessContextFactory()
    state = _build_state()

    factory.ensure_for_process(state, "transport")

    assert isinstance(state.setup.flow, Flow)
    assert isinstance(state.setup.transport, Transport)


def test_ensure_for_process_accepts_unknown_type_as_noop() -> None:
    """Unknown process types are silently accepted (no components to create)."""
    factory = ProcessContextFactory()
    state = _build_state()

    factory.ensure_for_process(state, "postprocess")

    assert state.setup.flow is None
    assert state.setup.transport is None
