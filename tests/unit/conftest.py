"""Guardrails for the unit tier.

Unit tests must remain hermetic: no real subprocess, no network, no I/O
against external services. A test that legitimately needs such a call
opts in explicitly with ``@pytest.mark.allow_subprocess``; everything
else fails fast with an actionable error message suggesting the
``integration/`` or ``e2e/`` tier.
"""

from __future__ import annotations

import subprocess

import pytest


_MESSAGE = (
    "subprocess is forbidden in unit/ — move this test to integration/ "
    "or e2e/, or mark it @pytest.mark.allow_subprocess to opt in."
)


def _deny_subprocess(*_args, **_kwargs):
    raise RuntimeError(_MESSAGE)


@pytest.fixture(autouse=True)
def _forbid_subprocess_in_unit(request, monkeypatch):
    """Patch ``subprocess`` entry points to fail fast in unit tests."""
    if request.node.get_closest_marker("allow_subprocess") is not None:
        yield
        return

    monkeypatch.setattr(subprocess, "run", _deny_subprocess)
    monkeypatch.setattr(subprocess, "Popen", _deny_subprocess)
    monkeypatch.setattr(subprocess, "call", _deny_subprocess)
    monkeypatch.setattr(subprocess, "check_call", _deny_subprocess)
    monkeypatch.setattr(subprocess, "check_output", _deny_subprocess)

    try:
        import requests  # type: ignore
    except ImportError:
        pass
    else:
        monkeypatch.setattr(requests, "get", _deny_subprocess)
        monkeypatch.setattr(requests, "post", _deny_subprocess)
        monkeypatch.setattr(requests, "request", _deny_subprocess)

    yield
