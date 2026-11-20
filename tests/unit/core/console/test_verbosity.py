"""The console verbosity scale: what each level lets through."""

from __future__ import annotations

import io
import warnings

import pytest
from rich.console import Console

from hydromodpy.core.console import progress as core_progress
from hydromodpy.core.console.progress import MILESTONE
from hydromodpy.core.logging import (
    LogManager,
    current_verbosity,
    get_logger,
    normalize_verbosity,
    set_verbosity,
    verbosity_from_env,
)


@pytest.fixture
def console_output():
    # The console is put back before the level on purpose. Restoring the level
    # rebuilds the console handler, and doing it against the fake terminal would
    # leave a handler writing into this buffer for the rest of the session.
    buffer = io.StringIO()
    original = core_progress.console
    previous = current_verbosity()
    core_progress.console = Console(file=buffer, force_terminal=True, width=200)
    try:
        yield buffer
    finally:
        core_progress.console = original
        set_verbosity(previous)


def _emit(level: str) -> None:
    set_verbosity(level)
    logger = get_logger("hydromodpy.test.verbosity")
    logger.debug("a debug line")
    logger.info("an ordinary info line")
    logger.info("a milestone line", extra=MILESTONE)
    logger.warning("a warning line")


def test_debug_shows_origin(console_output):
    _emit("debug")
    text = console_output.getvalue()
    assert "a debug line" in text
    assert "hydromodpy.test.verbosity" in text


def test_live_display_levels(console_output):
    for level in ("normal", "verbose"):
        set_verbosity(level)
        with core_progress.phase(f"phase at {level}"):
            pass
        assert "✓" in console_output.getvalue(), level
    buffer_before_quiet = console_output.getvalue()
    for level in ("quiet", "debug"):
        set_verbosity(level)
        with core_progress.phase(f"phase at {level}"):
            pass
    assert console_output.getvalue().count("✓") == buffer_before_quiet.count("✓")


def test_third_party_deprecation_hidden(console_output):
    LogManager(mode="normal")
    warnings.warn_explicit(
        "shape assignment is deprecated",
        DeprecationWarning,
        "/opt/env/lib/python3.13/site-packages/xarray/backends/netCDF4_.py",
        96,
    )
    assert "shape assignment" not in console_output.getvalue()


def test_third_party_runtime_warning_shown(console_output):
    LogManager(mode="normal")
    warnings.warn_explicit(
        "mean of empty slice",
        RuntimeWarning,
        "/opt/env/lib/python3.13/site-packages/numpy/_core/_methods.py",
        200,
    )
    assert "mean of empty slice" in console_output.getvalue()


def test_unknown_level():
    with pytest.raises(ValueError, match="quiet, normal, verbose, debug"):
        normalize_verbosity("loud")


def test_level_from_environment(monkeypatch):
    monkeypatch.setenv("HMP_VERBOSITY", "  DEBUG ")
    assert verbosity_from_env() == "debug"
    monkeypatch.delenv("HMP_VERBOSITY")
    assert verbosity_from_env() is None


def test_a_repeated_warning_is_shown_once(console_output):
    set_verbosity("normal")
    logger = get_logger("hydromodpy.test.verbosity")
    for _ in range(2):
        logger.warning("same warning")
    assert console_output.getvalue().count("same warning") == 1
