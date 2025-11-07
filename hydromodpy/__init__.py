"""Public entry points for HydroModPy."""

import logging
import os
from importlib import metadata
from pathlib import Path

_bootstrap_logger = logging.getLogger("hydromodpy")


def _ensure_proj_data_from_env() -> None:
    """Force PROJ to use the database that ships with the active environment."""
    current_proj_data = os.environ.get("PROJ_DATA")
    if current_proj_data:
        _bootstrap_logger.debug(
            "PROJ_DATA already defined (%s); HydroModPy will not override it.",
            current_proj_data,
        )
        return

    try:
        from pyproj import datadir
    except Exception:
        return

    proj_dir = datadir.get_data_dir()
    if not proj_dir:
        return

    if os.path.isdir(proj_dir):
        os.environ.setdefault("PROJ_DATA", proj_dir)
        os.environ.setdefault("PROJ_LIB", proj_dir)
        _bootstrap_logger.debug("PROJ_DATA/PROJ_LIB set to %s via pyproj.datadir", proj_dir)
    else:
        _bootstrap_logger.debug(
            "pyproj datadir %s does not exist on disk; PROJ environment variables unchanged.",
            proj_dir,
        )


_ensure_proj_data_from_env()

try:
    __version__ = metadata.version("hydromodpy")
except metadata.PackageNotFoundError:
    import tomllib

    _pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with _pyproject.open("rb") as fh:
        __version__ = tomllib.load(fh)["project"]["version"]

__author__ = "Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy"
__email__ = "alexandre.gauvain.ag@gmail.com, ronan.abherve@gmail.com, jean-raynald.de-dreuzy@univ-rennes.fr"

# Initialize logging system
from hydromodpy.tools.log_manager import LogManager
_log_manager = LogManager(mode="verbose", log_dir=None, overwrite=False)
# Public access to log manager for users
log_manager = _log_manager

# Import main class
from hydromodpy.watershed_root import Watershed

# Import submodules for convenience
from hydromodpy import watershed
from hydromodpy import modeling
from hydromodpy import display
from hydromodpy import tools
from hydromodpy import pyhelp

__all__ = [
    "Watershed",
    "watershed",
    "modeling",
    "display",
    "tools",
    "pyhelp",
    "log_manager",
    "__version__",
]
