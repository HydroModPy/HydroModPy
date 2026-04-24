"""Solver binary resolution and lazy download.

Downstream solvers (MODFLOW 6, MODFLOW-NWT, MODPATH, MT3D-USGS) ask for
an executable by its canonical name (``"mf6"``, ``"mfnwt"``, ``"mp6"``,
``"mp7"``, ``"mt3dusgs"``). This module locates the file in ``bin_path``
and, when ``bin_path`` is the HydroModPy-managed cache, downloads it via
``flopy.utils.get_modflow`` if missing.

Two ``bin_path`` layouts are recognised:

1. **Legacy repo layout** - ``<bin_path>/{linux,win,mac}/<exe>``, shipped
   for years inside ``<repo>/bin``. Auto-download never fires here; we
   just locate the bundled file.
2. **Flat cache layout** - ``<bin_path>/<exe>`` - the layout produced by
   ``flopy.utils.get_modflow`` when it extracts into the managed cache
   (``~/.cache/hydromodpy/bin/`` and platform-equivalents).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from pathlib import Path

from hydromodpy.core.logging import get_logger
from hydromodpy.core.tools.cache import get_cache_bin_dir
from hydromodpy.solver.modflow_common.executables import ensure_platform_executable

logger = get_logger(__name__)


_SOLVER_FILENAMES: dict[str, dict[str, str]] = {
    "mf6": {"win": "mf6.exe", "linux": "mf6", "darwin": "mf6"},
    "mfnwt": {"win": "mfnwt.exe", "linux": "mfnwt", "darwin": "mfnwt"},
    "mp6": {"win": "mp6.exe", "linux": "mp6", "darwin": "mp6"},
    "mp7": {"win": "mp7.exe", "linux": "mp7", "darwin": "mp7"},
    "mt3dusgs": {"win": "mt3dusgs.exe", "linux": "mt3dusgs", "darwin": "mt3dusgs"},
}

_LEGACY_PLATFORM_DIR = {"win32": "win", "win64": "win", "linux": "linux", "darwin": "mac"}

# Windows MT3D-USGS shipped historically under the versioned filename
_LEGACY_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "mt3dusgs": {"win": ("mt3d-usgs_1.1.0_64.exe",)},
}


def available_solvers() -> tuple[str, ...]:
    """Return the canonical names of solvers this module can fetch."""
    return tuple(_SOLVER_FILENAMES.keys())


def _platform_key() -> str:
    if sys.platform.startswith("win"):
        return "win"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def exe_filename(solver: str) -> str:
    """Canonical executable filename for ``solver`` on the current OS."""
    try:
        return _SOLVER_FILENAMES[solver][_platform_key()]
    except KeyError as exc:
        known = ", ".join(available_solvers())
        raise ValueError(f"Unknown solver '{solver}'. Expected one of: {known}") from exc


def is_managed_cache(bin_path: str | os.PathLike[str]) -> bool:
    """Return True when ``bin_path`` resolves to the HydroModPy cache."""
    try:
        return Path(bin_path).expanduser().resolve() == get_cache_bin_dir().resolve()
    except OSError:
        return False


def locate_solver_binary(bin_path: str | os.PathLike[str], solver: str) -> Path | None:
    """Return the exe path under ``bin_path`` or ``None`` if missing.

    Checks the legacy ``<bin_path>/<os>/<exe>`` layout first, then the
    flat ``<bin_path>/<exe>`` layout, then any legacy filename aliases.
    """
    bin_dir = Path(bin_path).expanduser()
    plat_key = _platform_key()
    exe = exe_filename(solver)
    legacy_dir = _LEGACY_PLATFORM_DIR.get(sys.platform, plat_key)

    candidates: list[Path] = [
        bin_dir / legacy_dir / exe,
        bin_dir / exe,
    ]
    for alias in _LEGACY_ALIASES.get(solver, {}).get(plat_key, ()):
        candidates.append(bin_dir / legacy_dir / alias)
        candidates.append(bin_dir / alias)

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def download_solver_binaries(
    bindir: str | os.PathLike[str] | None = None,
    subset: Iterable[str] | None = None,
    *,
    quiet: bool = False,
) -> Path:
    """Download solver binaries via ``flopy.utils.get_modflow``.

    ``bindir`` defaults to the managed cache. ``subset`` defaults to the
    full set of solvers this module knows about.
    """
    target = Path(bindir).expanduser() if bindir else get_cache_bin_dir()
    target.mkdir(parents=True, exist_ok=True)

    names = list(subset) if subset is not None else list(available_solvers())
    unknown = [name for name in names if name not in _SOLVER_FILENAMES]
    if unknown:
        raise ValueError(
            f"Unknown solver name(s): {unknown}. Expected subset of {list(available_solvers())}."
        )

    try:
        from flopy.utils import get_modflow
    except ImportError as exc:
        raise RuntimeError(
            "flopy is required to download solver binaries. "
            "Install it via `pip install flopy` or re-run `pip install -e .`."
        ) from exc

    logger.info("Downloading solver binaries %s into %s", names, target)
    get_modflow(str(target), subset=names, quiet=quiet)
    return target


def ensure_solver_binary(solver: str, bin_path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the exe for ``solver`` under ``bin_path``, downloading if needed.

    If ``bin_path`` is ``None`` or matches the managed cache and the
    binary is missing, it is fetched via :func:`download_solver_binaries`.
    For any other (user-supplied) ``bin_path``, a missing binary raises
    :class:`FileNotFoundError` - we never download into an external
    directory the user provided explicitly.
    """
    target = Path(bin_path).expanduser() if bin_path else get_cache_bin_dir()

    located = locate_solver_binary(target, solver)
    if located is not None:
        return Path(ensure_platform_executable(located))

    if bin_path is None or is_managed_cache(target):
        download_solver_binaries(target, subset=[solver])
        located = locate_solver_binary(target, solver)
        if located is not None:
            return Path(ensure_platform_executable(located))
        raise FileNotFoundError(
            f"Solver '{solver}' not found under {target} after download attempt. "
            f"Expected file: {target / exe_filename(solver)}."
        )

    legacy_dir = _LEGACY_PLATFORM_DIR.get(sys.platform, _platform_key())
    raise FileNotFoundError(
        f"Solver '{solver}' binary not found in {target}. "
        f"Expected {target / legacy_dir / exe_filename(solver)} "
        f"or {target / exe_filename(solver)}. "
        f"Either populate this directory manually, unset HYDROMODPY_BIN / "
        f"bin_path (to use the HydroModPy-managed cache), or run "
        f"`hmp install-binaries`."
    )


__all__ = [
    "available_solvers",
    "download_solver_binaries",
    "ensure_solver_binary",
    "exe_filename",
    "is_managed_cache",
    "locate_solver_binary",
]
