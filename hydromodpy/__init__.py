"""Public entry points for HydroModPy."""

import os
import warnings
from importlib import metadata
from pathlib import Path

def _configure_proj_support():
    """Register known PROJ data locations so coordinate transforms work out-of-the-box."""
    try:
        from importlib import resources
        from pyproj import datadir, network
    except ImportError:
        return

    os.environ.setdefault("PROJ_NETWORK", "ON")

    try:
        network.set_network_enabled(True)
    except Exception:
        pass

    extra_dirs = []

    try:
        pkg_proj_dir = resources.files("hydromodpy").joinpath("proj_data")
        if pkg_proj_dir.is_dir():
            extra_dirs.append(pkg_proj_dir)
    except Exception:
        pass

    cache_dir = Path.home() / ".cache" / "hydromodpy" / "proj"
    if cache_dir.exists():
        extra_dirs.append(cache_dir)

    custom_dir = os.environ.get("HYDROMODPY_PROJ_DATA")
    if custom_dir:
        custom_path = Path(custom_dir).expanduser()
        if custom_path.exists():
            extra_dirs.append(custom_path)

    for proj_dir in extra_dirs:
        try:
            datadir.append_data_dir(str(proj_dir))
        except Exception:
            warnings.warn(
                f"Unable to register PROJ data directory '{proj_dir}'. "
                "Install the required grid files or adjust HYDROMODPY_PROJ_DATA.",
                RuntimeWarning,
                stacklevel=2,
            )


_configure_proj_support()

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
