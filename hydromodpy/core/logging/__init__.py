"""HydroModPy logging subsystem.

Thin wrapper around the standard library :mod:`logging` module that adds
three-tier console verbosity (``dev`` / ``verbose`` / ``quiet``) and a
per-simulation debug log written alongside the simulation folder.

Public API::

    from hydromodpy.core.logging import LogManager, get_logger, setup_simulation_log
"""

from __future__ import annotations

from hydromodpy.core.logging.manager import (
    LogManager,
    get_logger,
    setup_simulation_log,
)

__all__ = ["LogManager", "get_logger", "setup_simulation_log"]
