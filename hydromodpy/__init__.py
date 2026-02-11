"""Public entry points for HydroModPy."""

import logging
import os
import re
import sys
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path

_bootstrap_logger = logging.getLogger("hydromodpy")
_MIN_PROJ_LAYOUT_MINOR = 6
_PROJ_DB_NAME = "proj.db"
_PROJ_LAYOUT_RE = re.compile(
    r"DATABASE\.LAYOUT\.VERSION\.MINOR\s*=\s*\d+\s*whereas a number >=\s*(\d+)\s*is expected"
)


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

    proj_db = env_proj_resolved / _PROJ_DB_NAME
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


def _ensure_proj_db_compatibility() -> None:
    try:
        from pyproj import CRS, datadir
    except Exception:
        return

    def _read_proj_layout_version(db_path: Path) -> tuple[int, int] | None:
        try:
            import sqlite3

            with sqlite3.connect(str(db_path)) as connection:
                columns = [row[1] for row in connection.execute("pragma table_info(metadata);")]
                key_column = "key" if "key" in columns else "name" if "name" in columns else None
                if not key_column:
                    return None

                values = dict(
                    connection.execute(
                        f"select {key_column}, value from metadata where {key_column} in (?, ?)",
                        ("DATABASE.LAYOUT.VERSION.MAJOR", "DATABASE.LAYOUT.VERSION.MINOR"),
                    ).fetchall()
                )
                major = int(values.get("DATABASE.LAYOUT.VERSION.MAJOR", -1))
                minor = int(values.get("DATABASE.LAYOUT.VERSION.MINOR", -1))
                return (major, minor) if major >= 0 and minor >= 0 else None
        except Exception:
            return None

    def _env_proj_path() -> Path | None:
        value = os.environ.get("PROJ_DATA") or os.environ.get("PROJ_LIB")
        return Path(value).expanduser() if value else None

    def _rasterio_proj_data_dirs() -> list[Path]:
        spec = find_spec("rasterio")
        if not spec or not spec.origin:
            return []

        base = Path(spec.origin).resolve().parent
        return [
            candidate
            for candidate in (
                base / "proj_data",
                base / "proj_dir" / "share" / "proj",
                base / "share" / "proj",
            )
            if (candidate / _PROJ_DB_NAME).exists()
        ]

    def _find_compatible_proj_data_dir(
        min_minor: int, pyproj_dir: Path | None
    ) -> tuple[Path | None, tuple[int, int] | None]:
        prefix = Path(sys.prefix)
        raw_candidates = [
            _env_proj_path(),
            pyproj_dir,
            prefix / "share" / "proj",
            prefix / "Library" / "share" / "proj",
            Path("/usr/local/share/proj"),
            Path("/usr/share/proj"),
            Path("/opt/homebrew/share/proj"),
            *_rasterio_proj_data_dirs(),
        ]
        seen: set[Path] = set()

        for candidate in raw_candidates:
            if not candidate:
                continue
            candidate = candidate.expanduser()
            if candidate in seen:
                continue
            seen.add(candidate)
            proj_db = candidate / _PROJ_DB_NAME
            if not proj_db.exists():
                continue
            layout = _read_proj_layout_version(proj_db)
            if layout and layout[1] >= min_minor:
                return candidate, layout
        return None, None

    def _ensure_proj_db_layout(min_minor: int, pyproj_dir: Path | None) -> None:
        current_path = _env_proj_path()
        if current_path:
            layout = _read_proj_layout_version(current_path / _PROJ_DB_NAME)
            if layout and layout[1] >= min_minor:
                return

        candidate, layout = _find_compatible_proj_data_dir(min_minor, pyproj_dir)
        if candidate:
            os.environ["PROJ_DATA"] = str(candidate)
            os.environ["PROJ_LIB"] = str(candidate)
        _bootstrap_logger.debug(
            "Detected incompatible PROJ database layout; switching PROJ_DATA/PROJ_LIB to %s (layout %s).",
            candidate,
            layout,
        )
        return

        _bootstrap_logger.warning(
            "PROJ database layout is older than expected (need >= %s). "
            "Update pyproj in the active environment (pip install -U pyproj) "
            "and avoid mixing system PROJ installs.",
            min_minor,
        )

    proj_dir = datadir.get_data_dir()
    pyproj_dir = Path(proj_dir) if proj_dir else None
    pyproj_layout = _read_proj_layout_version(pyproj_dir / _PROJ_DB_NAME) if pyproj_dir else None
    needs_check = bool(pyproj_layout and pyproj_layout[1] < _MIN_PROJ_LAYOUT_MINOR)
    min_minor = _MIN_PROJ_LAYOUT_MINOR

    try:
        CRS.from_epsg(4326)
        if not needs_check:
            return
    except Exception as exc:
        message = str(exc)
        if "DATABASE.LAYOUT.VERSION" not in message:
            return
        match = _PROJ_LAYOUT_RE.search(message)
        if match:
            min_minor = max(min_minor, int(match.group(1)))

    _ensure_proj_db_layout(min_minor, pyproj_dir)

    try:
        CRS.from_epsg(4326)
    except Exception as retry_exc:
        _bootstrap_logger.warning("PROJ database mismatch persists: %s", retry_exc)


_ensure_proj_data_from_env()
_ensure_proj_db_compatibility()

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
from hydromodpy import tools
from hydromodpy import pyhelp

__all__ = [
    "Watershed",
    "watershed",
    "modeling",
    "tools",
    "pyhelp",
    "log_manager",
    "__version__",
]
