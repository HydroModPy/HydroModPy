"""Public entry points for HydroModPy."""

import os
import warnings
from importlib import metadata
from pathlib import Path


def _configure_proj_support():
    """Register bundled and user-provided PROJ data directories."""
    try:
        from pyproj import datadir, network
    except ImportError:
        return

    os.environ.setdefault("PROJ_NETWORK", "ON")

    try:
        network.set_network_enabled(True)
    except Exception:
        pass

    package_dir = Path(__file__).resolve().parent
    project_root = package_dir.parent

    extra_dirs = [
        package_dir / "proj_data",
        project_root / "bin" / "proj_data",
        Path.home() / ".cache" / "hydromodpy" / "proj",
    ]

    custom_dir = os.environ.get("HYDROMODPY_PROJ_DATA")
    if custom_dir:
        extra_dirs.append(Path(custom_dir).expanduser())

    for proj_dir in extra_dirs:
        if not proj_dir or not proj_dir.exists():
            continue
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
