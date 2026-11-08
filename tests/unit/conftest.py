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

Hermetic also means order-independent, which is what the runtime bootstrap
fixture below buys: a unit test must not need another test module to have
initialized the model runtime first.
"""

from __future__ import annotations

import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

_MESSAGE = (
    "subprocess is forbidden in unit/; network access is also forbidden - "
    "move this test to integration/ "
    "or e2e/, or mark it @pytest.mark.allow_subprocess to opt in."
)

_STDLIB_DIR = Path(sysconfig.get_paths()["stdlib"]).resolve()
_CONFTEST_FILE = Path(__file__).resolve()

_ORIG_RUN = subprocess.run
_ORIG_POPEN = subprocess.Popen
_ORIG_CALL = subprocess.call
_ORIG_CHECK_CALL = subprocess.check_call


def _caller_is_user_code(*, frame_offset: int) -> bool:
    """Return True when the *immediate* caller is outside stdlib.

    We only look at the first non-conftest frame: this keeps transitive
    stdlib calls (``subprocess.check_output`` → ``subprocess.run``, or
    ``platform.processor`` → ``subprocess.check_output`` via h5py's
    import side-effects) out of the ban while still catching direct
    ``subprocess.run(...)`` invocations from a test module.
    """
    frame = sys._getframe(frame_offset)
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
        if _caller_is_user_code(frame_offset=2):
            raise RuntimeError(_MESSAGE)
        return orig(*args, **kwargs)

    return _wrapper


class _GuardedPopen(_ORIG_POPEN):
    """Class-preserving guard used by unit tests."""

    def __init__(self, *args, **kwargs):
        if _caller_is_user_code(frame_offset=2):
            raise RuntimeError(_MESSAGE)
        super().__init__(*args, **kwargs)


@pytest.fixture(autouse=True)
def _forbid_subprocess_in_unit(request, monkeypatch):
    """Patch ``subprocess`` entry points to fail fast in unit tests."""
    if request.node.get_closest_marker("allow_subprocess") is not None:
        yield
        return

    monkeypatch.setattr(subprocess, "run", _wrap(_ORIG_RUN))
    monkeypatch.setattr(subprocess, "Popen", _GuardedPopen)
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
        monkeypatch.setattr(requests.Session, "request", _deny)

    yield


@pytest.fixture(scope="session", autouse=True)
def _fill_the_trial_pipeline() -> None:
    """Fill the one global the library keeps, the trial pipeline of a calibration.

    The library has no start-up call: every other service a unit test needs
    arrives as a constructor argument. The trial pipeline is the one exception
    the architecture keeps, and :func:`fill_trial_pipeline` is idempotent, so a
    test that reads a calibration file finds the pipeline it reads through.
    """
    from hydromodpy.project.trial_pipeline import fill_trial_pipeline

    fill_trial_pipeline()
