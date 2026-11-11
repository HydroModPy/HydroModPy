"""What this machine runs: Python, HydroModPy, the packages and the solver executables.

:func:`doctor_report` is quick by design. It starts no solver and imports only the
packages it lists, so a script can call it at import time.
"""

from __future__ import annotations

import importlib
import platform
import shutil
from dataclasses import dataclass
from typing import Any, Final

from hydromodpy.core.version import __version__

PACKAGES: Final[tuple[str, ...]] = (
    "numpy",
    "pandas",
    "scipy",
    "duckdb",
    "zarr",
    "pyproj",
    "rasterio",
    "shapely",
    "xarray",
    "flopy",
    "pydantic",
    "pint",
    "matplotlib",
    "gmsh",
    "whitebox_workflows",
    "geopandas",
)
"""The packages the report names, each with its version."""

SOLVERS: Final[tuple[str, ...]] = ("mf2005", "mfnwt", "mf6", "mp6", "mp7", "mt3dusgs")
"""The executables the report looks for on the ``PATH``."""


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """The state of the machine: versions, packages and solver executables."""

    python: str
    """Version of the Python interpreter."""
    hydromodpy: str
    """Version of HydroModPy."""
    solvers: dict[str, str | None]
    """Each solver executable and the path it was found at, ``None`` when missing."""
    optional: dict[str, str | None]
    """Each package of :data:`PACKAGES` and its version, ``None`` when it does not import."""

    def to_dict(self) -> dict[str, Any]:
        """Return the report as JSON, with ``python``, ``hydromodpy``, ``solvers`` and ``optional``."""
        return {
            "python": self.python,
            "hydromodpy": self.hydromodpy,
            "solvers": dict(self.solvers),
            "optional": dict(self.optional),
        }


def doctor_report() -> DoctorReport:
    """Return what this machine runs. No solver is started."""
    versions: dict[str, str | None] = {}
    for name in PACKAGES:
        try:
            module = importlib.import_module(name)
            versions[name] = getattr(module, "__version__", "?")
        except Exception:  # noqa: BLE001 - a package that fails to import is reported as missing
            versions[name] = None
    return DoctorReport(
        python=platform.python_version(),
        hydromodpy=__version__,
        solvers={exe: shutil.which(exe) for exe in SOLVERS},
        optional=versions,
    )
