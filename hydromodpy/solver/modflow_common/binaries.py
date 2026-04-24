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

Versioning policy
-----------------

Once a binary lands in the managed cache we never auto-refresh it: the
same MODFLOW version stays in place for the lifetime of the cache, for
reproducibility (a run started today must yield the same results a year
from now unless the user opts in to an upgrade). A manifest written
alongside the binaries (``.manifest.json``) records the download date
and USGS release tag. To pull newer USGS binaries, the user runs::

    hmp install-binaries --upgrade

which forces a re-download and rewrites the manifest.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from hydromodpy.core.logging import get_logger
from hydromodpy.core.tools.cache import get_cache_bin_dir
from hydromodpy.solver.modflow_common.executables import ensure_platform_executable

logger = get_logger(__name__)

MANIFEST_FILENAME = ".manifest.json"
DEFAULT_RELEASE = "latest"


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


def _manifest_path(bindir: Path) -> Path:
    return bindir / MANIFEST_FILENAME


def read_manifest(bindir: str | os.PathLike[str] | None = None) -> dict | None:
    """Return the cache manifest dict, or ``None`` if missing/unreadable."""
    target = Path(bindir).expanduser() if bindir else get_cache_bin_dir()
    path = _manifest_path(target)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_manifest(bindir: Path, *, release: str, solvers: list[str], replace: bool) -> None:
    path = _manifest_path(bindir)
    existing = read_manifest(bindir) if not replace else None
    merged_solvers = set(solvers)
    if existing and isinstance(existing.get("solvers"), list):
        merged_solvers.update(existing["solvers"])
    manifest = {
        "release": release,
        "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "solvers": sorted(merged_solvers),
    }
    try:
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to write cache manifest %s: %s", path, exc)


def download_solver_binaries(
    bindir: str | os.PathLike[str] | None = None,
    subset: Iterable[str] | None = None,
    *,
    quiet: bool = False,
    force: bool = False,
    release: str = DEFAULT_RELEASE,
) -> Path:
    """Download solver binaries via ``flopy.utils.get_modflow``.

    ``bindir`` defaults to the managed cache. ``subset`` defaults to the
    full set of solvers this module knows about. When ``force`` is True
    the download archive is re-fetched even if previously cached by
    flopy. ``release`` pins the USGS release tag (``"latest"`` follows
    the upstream moving target, otherwise e.g. ``"18.0"``).
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

    logger.info("Downloading solver binaries %s (release=%s) into %s", names, release, target)
    get_modflow(str(target), subset=names, quiet=quiet, force=force, release_id=release)
    _write_manifest(target, release=release, solvers=names, replace=force)
    return target


def ensure_solver_binary(solver: str, bin_path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the exe for ``solver`` under ``bin_path``, downloading if needed.

    Behaviour matrix:

    * ``bin_path`` is ``None`` or matches the managed cache **and** the
      binary is present → return its path.
    * ``bin_path`` is ``None`` or managed cache, binary missing → fetch
      it via :func:`download_solver_binaries`, then return the path
      (raises :class:`FileNotFoundError` if the download failed to
      produce the expected file).
    * ``bin_path`` is user-supplied and the binary is present → return
      its path; we never touch an external directory with a download.
    * ``bin_path`` is user-supplied and the binary is missing → log a
      warning and return the *expected* path. Solver execution will
      surface the missing-file error with its own diagnostics. This
      preserves the permissive pre-v0.6 behaviour for callers that
      instantiate solvers without running them (e.g. unit tests for
      config validation).
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
    expected = target / legacy_dir / exe_filename(solver)
    logger.warning(
        "Solver '%s' not found at %s (bin_path=%s). Returning the expected path; "
        "run `hmp install-binaries` or populate the directory to avoid a "
        "runtime error when the solver executes.",
        solver,
        expected,
        target,
    )
    return expected


__all__ = [
    "DEFAULT_RELEASE",
    "MANIFEST_FILENAME",
    "available_solvers",
    "download_solver_binaries",
    "ensure_solver_binary",
    "exe_filename",
    "is_managed_cache",
    "locate_solver_binary",
    "read_manifest",
]
