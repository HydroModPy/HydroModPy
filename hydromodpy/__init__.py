"""Public entry points for HydroModPy."""

import logging
import os
import sys
from importlib import metadata
from pathlib import Path

_bootstrap_logger = logging.getLogger("hydromodpy")


def _ensure_proj_data_from_env() -> None:
    """Force PROJ to use the database that ships with the active environment."""
    try:
        from pyproj import datadir
    except Exception:  # pyproj optional in some contexts
        return

    proj_dir = datadir.get_data_dir()
    if not proj_dir:
        _bootstrap_logger.debug("pyproj.datadir returned an empty path; PROJ env unchanged.")
        return

    env_proj_path = Path(proj_dir).expanduser()
    try:
        env_proj_resolved = env_proj_path.resolve()
    except OSError:
        env_proj_resolved = env_proj_path

    proj_db = env_proj_resolved / "proj.db"
    if not proj_db.exists():
        _bootstrap_logger.debug(
            "pyproj datadir %s does not contain proj.db; PROJ environment variables unchanged.",
            env_proj_resolved,
        )
        return

    env_root = Path(sys.prefix)

    def _within_env(path: Path) -> bool:
        try:
            path.resolve().relative_to(env_root.resolve())
            return True
        except Exception:
            return False

    current_proj_data = os.environ.get("PROJ_DATA")
    if current_proj_data:
        try:
            current_path = Path(current_proj_data).expanduser()
            current_resolved = current_path.resolve()
        except OSError:
            current_path = Path(current_proj_data)
            current_resolved = current_path

        if current_resolved == env_proj_resolved:
            _bootstrap_logger.debug(
                "PROJ_DATA already targets the environment-specific directory %s; keeping as-is.",
                current_proj_data,
            )
            os.environ.setdefault("PROJ_LIB", current_proj_data)
            return

        if current_path.exists() and _within_env(current_resolved):
            _bootstrap_logger.debug(
                "PROJ_DATA=%s already points inside the active environment (%s); keeping user setting.",
                current_proj_data,
                env_root,
            )
            os.environ.setdefault("PROJ_LIB", current_proj_data)
            return

        reason = (
            "does not exist on disk" if not current_path.exists() else "points outside the active environment"
        )
        _bootstrap_logger.warning(
            "PROJ_DATA=%s %s; switching HydroModPy to %s instead.",
            current_proj_data,
            reason,
            env_proj_resolved,
        )

    os.environ["PROJ_DATA"] = str(env_proj_resolved)
    os.environ["PROJ_LIB"] = str(env_proj_resolved)
    _bootstrap_logger.debug("PROJ_DATA/PROJ_LIB set to %s via pyproj.datadir", env_proj_resolved)


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
