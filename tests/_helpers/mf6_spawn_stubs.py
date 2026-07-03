"""Spawn-importable child entry stubs for the isolated-api-runner tests.

These live in an importable package (not a test module) so ``spawn`` can re-import
the target in the child process without a real MODFLOW solve.
"""

from __future__ import annotations

import time


def sleep_entry(result_queue, sim_ws, band_specs, lib_path) -> None:
    """A child that never posts a result, to exercise the parent timeout path."""
    del result_queue, sim_ws, band_specs, lib_path
    time.sleep(120)


def crash_entry(result_queue, sim_ws, band_specs, lib_path) -> None:
    """A child that exits without posting a result, simulating a libmf6 crash."""
    del result_queue, sim_ws, band_specs, lib_path
    import os

    os._exit(1)
