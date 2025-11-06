"""Public entry points for HydroModPy."""

import os
import warnings
from importlib import metadata
from pathlib import Path

# Permit pyproj to fetch missing grid files over the network when available.
os.environ.setdefault("PROJ_NETWORK", "ON")


def _check_proj_connectivity():
    """Warn early if pyproj cannot access grid data (offline or missing files)."""
    try:
        from pyproj import Transformer
        transformer = Transformer.from_crs("EPSG:4326", "EPSG:2056", always_xy=True)
        # Trigger actual use so PROJ requests the grid if needed.
        transformer.transform(0.0, 0.0)
    except ImportError:
        # pyproj is an explicit dependency; if absent, later imports will fail normally.
        return
    except Exception as exc:  # pragma: no cover - network/PROJ specific paths
        hint = (
            "HydroModPy detected that pyproj cannot access required grid files. "
            "Ensure the machine has internet access or install the 'pyproj-data' "
            "package to provide them offline. Details: "
        )
        warnings.warn(f"{hint}{exc}", RuntimeWarning, stacklevel=2)


_check_proj_connectivity()

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
