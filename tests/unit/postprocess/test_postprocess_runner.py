"""Unit tests for launcher-managed postprocess dispatch."""

from types import SimpleNamespace

from hydromodpy.postprocess.postprocess_config import PostprocessConfig
from hydromodpy.postprocess.runner import PostprocessRunner


def test_postprocess_runner_is_disabled_by_default() -> None:
    runner = PostprocessRunner(PostprocessConfig())
    called: list[str] = []
    runner._after_flow = lambda state: called.append("flow")  # type: ignore[method-assign]
    runner._after_transport = lambda state: called.append("transport")  # type: ignore[method-assign]

    runner.after_process("flow", SimpleNamespace())
    runner.after_process("transport", SimpleNamespace())

    assert called == []


def test_postprocess_runner_dispatches_flow_and_transport() -> None:
    runner = PostprocessRunner(PostprocessConfig(enabled=True))
    called: list[str] = []
    runner._after_flow = lambda state: called.append("flow")  # type: ignore[method-assign]
    runner._after_transport = lambda state: called.append("transport")  # type: ignore[method-assign]

    runner.after_process(" flow ", SimpleNamespace())
    runner.after_process("transport", SimpleNamespace())

    assert called == ["flow", "transport"]


def test_postprocess_runner_ignores_unknown_process_type() -> None:
    runner = PostprocessRunner(PostprocessConfig(enabled=True))
    called: list[str] = []
    runner._after_flow = lambda state: called.append("flow")  # type: ignore[method-assign]
    runner._after_transport = lambda state: called.append("transport")  # type: ignore[method-assign]

    runner.after_process("particles", SimpleNamespace())

    assert called == []
