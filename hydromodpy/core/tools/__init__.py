"""Residual tool helpers.

Only things that don't fit the canonical taxonomy (``core/io/``,
``core/logging/``, ``core/exceptions``) remain here:

Submodules
----------
filesystem  -- directory creation, CSV loading
statistics  -- hydrological metrics (RMSE, NSE, KGE, etc.)
display     -- matplotlib styling, ASCII banner
io_utils    -- legacy watershed-era helpers (scheduled for removal)

Logging and raster / vector / CRS I/O live in :mod:`hydromodpy.core.logging`
and :mod:`hydromodpy.core.io` respectively.
"""

from hydromodpy.core.tools.log_manager import LogManager, get_logger, setup_simulation_log

__all__ = ["LogManager", "get_logger", "setup_simulation_log"]
