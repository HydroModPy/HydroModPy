"""Public entry points for HydroModPy."""

import os
import warnings
from importlib import metadata
from pathlib import Path

# Permit pyproj to fetch missing grid files over the network when available.
os.environ.setdefault("PROJ_NETWORK", "ON")


def _enable_pyproj_network():
    """Ensure pyproj network access is enabled even if pyproj was imported earlier."""
    try:
        from pyproj import network
    except ImportError:
        return

    try:
        network.set_network_enabled(True)
    except Exception as exc:  # pragma: no cover - platform specific behaviour
        warnings.warn(
            f"HydroModPy could not enable pyproj network access automatically ({exc}). "
            "Install the 'pyproj-data' package or set PROJ_NETWORK=ON before importing "
            "HydroModPy if reprojection grids are missing.",
            RuntimeWarning,
            stacklevel=2,
        )


def _ensure_proj_data_dir():
    """Point pyproj to the bundled data directory if pyproj-data is installed."""
    try:
        from pyproj import datadir
        import pyproj_data
    except ImportError:
        return

    try:
        data_dir = pyproj_data.get_data_dir()
        if data_dir and os.path.isdir(data_dir):
            datadir.set_data_dir(data_dir)
    except Exception as exc:  # pragma: no cover - environment specific
        warnings.warn(
            f"HydroModPy could not configure pyproj data directory automatically ({exc}). "
            "If coordinate transformations fail, install the 'pyproj-data' package or "
            "set the PROJ_DATA environment variable to the directory containing grid files.",
            RuntimeWarning,
            stacklevel=2,
        )


_TRANSFORMER_PATCHED = False


def _patch_transformer_fallback():
    """Patch pyproj Transformer to fall back to ballpark transforms when grids are missing."""
    global _TRANSFORMER_PATCHED
    if _TRANSFORMER_PATCHED:
        return
    try:
        from pyproj import Transformer
        from pyproj.exceptions import ProjError
    except ImportError:
        return

    original_from_crs = Transformer.from_crs

    def from_crs_with_fallback(*args, **kwargs):
        try:
            return original_from_crs(*args, **kwargs)
        except ProjError as exc:
            if kwargs.get("allow_ballpark"):
                raise
            fallback_kwargs = dict(kwargs)
            fallback_kwargs["allow_ballpark"] = True
            warnings.warn(
                (
                    "pyproj could not locate high-accuracy grid files for the requested "
                    "CRS transformation. Falling back to a lower-accuracy transformation "
                    "with allow_ballpark=True. Install the official PROJ grids or set "
                    "PROJ_NETWORK=ON for full accuracy."
                ),
                RuntimeWarning,
                stacklevel=3,
            )
            return original_from_crs(*args, **fallback_kwargs)

    Transformer.from_crs = staticmethod(from_crs_with_fallback)
    _TRANSFORMER_PATCHED = True


def _check_proj_connectivity():
    """Warn early if pyproj cannot access grid data (offline or missing files)."""
    try:
        from pyproj import Transformer
        _enable_pyproj_network()
        _ensure_proj_data_dir()
        _patch_transformer_fallback()
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
