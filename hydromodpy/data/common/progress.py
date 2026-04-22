"""Unified progress and logging interface for data managers.

Provides structured logging with visual hierarchy and optional tqdm
progress bars for long-running operations. All output goes through
the standard logging module — no print() calls.
"""

from __future__ import annotations

import time
from collections.abc import Generator, Iterable
from contextlib import contextmanager

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


@contextmanager
def data_phase(variable: str) -> Generator[None, None, None]:
    """Context manager for loading one variable type.

    Logs the variable name at the start. The caller is responsible
    for logging the outcome via ``log_loaded()``.
    """
    logger.info("[data] %s", variable)
    t0 = time.perf_counter()
    yield
    dt = time.perf_counter() - t0
    if dt > 2.0:
        logger.debug("       completed in %.1fs", dt)


def log_step(message: str) -> None:
    """Log a sub-step within a data phase (visually indented)."""
    logger.info("       %s", message)


def log_loaded(n_records: int, detail: str = "") -> None:
    """Log the outcome of a data phase."""
    msg = f"       {n_records} record(s) loaded"
    if detail:
        msg += f" ({detail})"
    logger.info(msg)


def iter_progress(
    iterable: Iterable,
    *,
    desc: str,
    total: int | None = None,
) -> Iterable:
    """Wrap an iterable with a tqdm progress bar for long loops.

    Skips the progress bar when total <= 3 (not worth displaying).
    Falls back to plain iteration if tqdm is not installed.
    """
    n = total if total is not None else (
        len(iterable) if hasattr(iterable, "__len__") else None
    )
    if n is not None and n <= 3:
        return iterable
    try:
        from tqdm import tqdm
        return tqdm(iterable, desc=f"       {desc}", total=n, leave=False)
    except ImportError:
        return iterable
