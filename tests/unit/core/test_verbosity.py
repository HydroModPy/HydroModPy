"""The console verbosity scale: what each level lets through."""

from __future__ import annotations

import io
import logging

import pytest
from rich.console import Console

from hydromodpy.core import progress as core_progress
from hydromodpy.core.logging import (
    LogManager,
    current_verbosity,
    get_logger,
    normalize_verbosity,
    set_verbosity,
    verbosity_from_env,
)
from hydromodpy.core.progress import MILESTONE


@pytest.fixture
def console_output():
    """Capture what the shared console prints, and restore the level after.

    The console is put back before the level is, on purpose: restoring the
    level rebuilds the console handler, and rebuilding it against the fake
    terminal would leave a handler writing into this buffer for the rest of
    the session.
    """
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
    """Log one line of each kind at *level*."""
    set_verbosity(level)
    logger = get_logger("hydromodpy.test.verbosity")
    logger.debug("a debug line")
    logger.info("an ordinary info line")
    logger.info("a milestone line", extra=MILESTONE)
    logger.warning("a warning line")


def test_normal_keeps_milestones_and_warnings(console_output):
    _emit("normal")
    text = console_output.getvalue()
    assert "a milestone line" in text
    assert "a warning line" in text
    assert "an ordinary info line" not in text
    assert "a debug line" not in text


def test_normal_prints_a_milestone_without_a_level_prefix(console_output):
    _emit("normal")
    text = console_output.getvalue()
    assert "[INFO]" not in text
    assert "[WARNING] a warning line" in text


def test_verbose_keeps_every_info_line(console_output):
    _emit("verbose")
    text = console_output.getvalue()
    assert "an ordinary info line" in text
    assert "a debug line" not in text


def test_quiet_keeps_warnings_only(console_output):
    _emit("quiet")
    text = console_output.getvalue()
    assert "a warning line" in text
    assert "a milestone line" not in text


def test_debug_keeps_everything_with_its_origin(console_output):
    _emit("debug")
    text = console_output.getvalue()
    assert "a debug line" in text
    assert "hydromodpy.test.verbosity" in text


def test_a_warning_repeated_verbatim_is_printed_once(console_output):
    set_verbosity("normal")
    logger = get_logger("hydromodpy.test.verbosity")
    logger.warning("outlet snapped 130.5 m")
    logger.warning("outlet snapped 130.5 m")
    assert console_output.getvalue().count("outlet snapped") == 1


def test_the_live_display_runs_at_normal_and_verbose(console_output):
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


def test_a_third_party_deprecation_does_not_warn(console_output):
    import warnings

    LogManager(mode="normal")
    warnings.warn_explicit(
        "shape assignment is deprecated",
        DeprecationWarning,
        "/opt/env/lib/python3.13/site-packages/xarray/backends/netCDF4_.py",
        96,
    )
    assert "shape assignment" not in console_output.getvalue()


def test_a_third_party_runtime_warning_still_warns(console_output):
    import warnings

    LogManager(mode="normal")
    warnings.warn_explicit(
        "mean of empty slice",
        RuntimeWarning,
        "/opt/env/lib/python3.13/site-packages/numpy/_core/_methods.py",
        200,
    )
    assert "mean of empty slice" in console_output.getvalue()


def test_an_unknown_level_is_refused():
    with pytest.raises(ValueError, match="quiet, normal, verbose, debug"):
        normalize_verbosity("loud")


def test_the_environment_names_a_level(monkeypatch):
    monkeypatch.setenv("HMP_VERBOSITY", "  DEBUG ")
    assert verbosity_from_env() == "debug"
    monkeypatch.delenv("HMP_VERBOSITY")
    assert verbosity_from_env() is None
