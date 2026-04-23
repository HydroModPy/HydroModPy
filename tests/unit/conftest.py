"""Guardrails for the unit tier.

Unit tests must remain hermetic: no real subprocess, no network, no I/O
against external services. A test that legitimately needs such a call
opts in explicitly with ``@pytest.mark.allow_subprocess``; everything
else fails fast with an actionable error message suggesting the
``integration/`` or ``e2e/`` tier.

The hook is caller-aware: transitive stdlib subprocess calls (e.g.
``platform.processor``, triggered indirectly by h5py's cython bindings
during import) are allowed through, so the ban only fires when user or
HydroModPy code is the one issuing the shell-out.
"""

from __future__ import annotations

import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

_MESSAGE = (
    "subprocess is forbidden in unit/ - move this test to integration/ "
    "or e2e/, or mark it @pytest.mark.allow_subprocess to opt in."
)

_STDLIB_DIR = Path(sysconfig.get_paths()["stdlib"]).resolve()
_CONFTEST_FILE = Path(__file__).resolve()

_ORIG_RUN = subprocess.run
_ORIG_POPEN = subprocess.Popen
_ORIG_CALL = subprocess.call
_ORIG_CHECK_CALL = subprocess.check_call


def _caller_is_user_code() -> bool:
    """Return True when the *immediate* caller is outside stdlib.

    We only look at the first non-conftest frame: this keeps transitive
    stdlib calls (``subprocess.check_output`` → ``subprocess.run``, or
    ``platform.processor`` → ``subprocess.check_output`` via h5py's
    import side-effects) out of the ban while still catching direct
    ``subprocess.run(...)`` invocations from a test module.
    """
    frame = sys._getframe(2)  # skip _wrapper + _caller_is_user_code
    while frame is not None:
        fname = frame.f_code.co_filename
        try:
            resolved = Path(fname).resolve()
        except OSError:
            return True
        if resolved == _CONFTEST_FILE:
            frame = frame.f_back
            continue
        try:
            resolved.relative_to(_STDLIB_DIR)
            return False
        except ValueError:
            return True
    return False


def _wrap(orig):
    def _wrapper(*args, **kwargs):
        if _caller_is_user_code():
            raise RuntimeError(_MESSAGE)
        return orig(*args, **kwargs)

    return _wrapper


@pytest.fixture(autouse=True)
def _forbid_subprocess_in_unit(request, monkeypatch):
    """Patch ``subprocess`` entry points to fail fast in unit tests."""
    if request.node.get_closest_marker("allow_subprocess") is not None:
        yield
        return

    monkeypatch.setattr(subprocess, "run", _wrap(_ORIG_RUN))
    monkeypatch.setattr(subprocess, "Popen", _wrap(_ORIG_POPEN))
    monkeypatch.setattr(subprocess, "call", _wrap(_ORIG_CALL))
    monkeypatch.setattr(subprocess, "check_call", _wrap(_ORIG_CHECK_CALL))

    try:
        import requests  # type: ignore
    except ImportError:
        pass
    else:

        def _deny(*_args, **_kwargs):
            raise RuntimeError(_MESSAGE)

        monkeypatch.setattr(requests, "get", _deny)
        monkeypatch.setattr(requests, "post", _deny)
        monkeypatch.setattr(requests, "request", _deny)

    yield
