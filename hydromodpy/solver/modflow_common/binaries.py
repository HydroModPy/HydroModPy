"""Solver binary resolution and verified download.

Downstream solvers (MODFLOW 6, MODFLOW-NWT, MODPATH, MT3D-USGS) ask for
an executable by its canonical name (``"mf6"``, ``"mfnwt"``, ``"mp6"``,
``"mp7"``, ``"mt3dusgs"``). This module locates the file in ``bin_path``
and, when ``bin_path`` is the HydroModPy-managed cache, installs it from the
pinned release if missing.

Layout
------

Solvers are looked up under ``<bin_path>/<exe>``, a flat folder. The managed
cache lives at ``~/.cache/hydromodpy/bin/`` (or the platform equivalent) and a
custom directory may be passed via the ``HMP_BIN`` env var or the ``--to``
flag of ``hmp install-binaries``.

Versioning policy
-----------------

A release of ``MODFLOW-ORG/executables`` holds one zip per platform, with every
solver inside. :data:`RELEASE_ASSETS` writes the sha256 of each zip of each
release HydroModPy installs, so one digest covers every binary this module
manages. A zip that hashes to anything else is refused, before a file of it
reaches ``bin_path``. A release with no digests here is refused too. A new entry
is a number change until proven otherwise, under the rule of the page
``contribute/architecture/how-to/cut-a-release``.

Once a binary lands in the managed cache we never auto-refresh it: the
same MODFLOW version stays in place for the lifetime of the cache, for
reproducibility (a run started today must yield the same results a year
from now unless the user opts in to an upgrade). A manifest written
alongside the binaries (``.manifest.json``) records the download date,
the release tag and the zip with its sha256. To download the binaries again,
the user runs::

    hmp install-binaries --upgrade

which forces a re-download and rewrites the manifest.
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from hydromodpy.core.console import progress
from hydromodpy.core.exceptions import NetworkError, SolverBinaryError
from hydromodpy.core.io.fetch import fetch_pinned
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.portable import cache_dir
from hydromodpy.core.workspace.workspace import resolve_bin_path

logger = get_logger(__name__)

MANIFEST_FILENAME = ".manifest.json"
DEFAULT_RELEASE = "23.0"

BINARIES_REPOSITORY = "MODFLOW-ORG/executables"
"""GitHub repository the solver binaries are downloaded from."""

RELEASE_ASSETS: dict[str, dict[str, str]] = {
    "23.0": {
        "linux.zip": "610bb1918e3f9d9b7d0124de158b65281e42a086205c3adf342324ca7d067adb",
        "mac.zip": "2a8c31084e20d4d0318fbb2e54cedee6799fda2205b796af6c18e7732acde14b",
        "macarm.zip": "a075ea618d38d8cdf32d5ecd4f354f173950239639a86391dbf4236b68c0e6d2",
        "win64.zip": "83f95eaf5c2492b0471d621de960893a1576d4ba6db80195d789dd28503df7d2",
    },
}
"""The sha256 of each platform zip, per release HydroModPy installs."""

SOLVER_EXECUTABLES: dict[str, str] = {"modflow6": "mf6", "modflow_nwt": "mfnwt"}
"""Catalog solver code -> canonical executable this module can fetch."""

SOLVER_LIBRARIES: dict[str, str] = {"modflow6": "libmf6"}
"""The shared library a solver runs from in ``api`` mode, by solver name."""


def ensure_platform_executable(path: str | Path) -> Path:
    """Ensure one bundled solver binary is executable on POSIX checkouts."""
    executable = Path(path)
    if os.name == "nt" or not executable.is_file():
        return executable

    try:
        current_mode = executable.stat().st_mode
    except OSError:
        return executable

    execute_bits = 0
    if current_mode & stat.S_IRUSR:
        execute_bits |= stat.S_IXUSR
    if current_mode & stat.S_IRGRP:
        execute_bits |= stat.S_IXGRP
    if current_mode & stat.S_IROTH:
        execute_bits |= stat.S_IXOTH

    if execute_bits == 0 or (current_mode & execute_bits) == execute_bits:
        return executable

    try:
        executable.chmod(current_mode | execute_bits)
    except OSError:
        return executable
    return executable


_SOLVER_FILENAMES: dict[str, dict[str, str]] = {
    "mf6": {"win": "mf6.exe", "linux": "mf6", "darwin": "mf6"},
    "mfnwt": {"win": "mfnwt.exe", "linux": "mfnwt", "darwin": "mfnwt"},
    "mp6": {"win": "mp6.exe", "linux": "mp6", "darwin": "mp6"},
    "mp7": {"win": "mp7.exe", "linux": "mp7", "darwin": "mp7"},
    "mt3dusgs": {"win": "mt3dusgs.exe", "linux": "mt3dusgs", "darwin": "mt3dusgs"},
    "libmf6": {"win": "libmf6.dll", "linux": "libmf6.so", "darwin": "libmf6.dylib"},
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
    """Return True when ``bin_path`` resolves to the HydroModPy cache; creates nothing."""
    try:
        return Path(bin_path).expanduser().resolve() == (cache_dir() / "bin").resolve()
    except OSError:
        return False


def locate_solver_binary(bin_path: str | os.PathLike[str], solver: str) -> Path | None:
    """Return the exe path under ``bin_path`` or ``None`` if missing."""
    bin_dir = Path(bin_path).expanduser()
    candidate = bin_dir / exe_filename(solver)
    return candidate if candidate.is_file() else None


def _manifest_path(bindir: Path) -> Path:
    return bindir / MANIFEST_FILENAME


def read_manifest(bindir: str | os.PathLike[str] | None = None) -> dict | None:
    """Return the cache manifest dict, or ``None`` if missing/unreadable."""
    target = Path(bindir).expanduser() if bindir else Path(resolve_bin_path())
    path = _manifest_path(target)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_manifest(
    bindir: Path, *, release: str, asset: str, solvers: list[str], replace: bool
) -> None:
    path = _manifest_path(bindir)
    existing = read_manifest(bindir) if not replace else None
    merged_solvers = set(solvers)
    if existing and isinstance(existing.get("solvers"), list):
        merged_solvers.update(existing["solvers"])
    manifest = {
        "release": release,
        "asset": asset,
        "asset_sha256": RELEASE_ASSETS[release][asset],
        "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "solvers": sorted(merged_solvers),
    }
    try:
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to write cache manifest %s: %s", path, exc)


def _release_asset() -> str:
    """Return the name of the zip of a release that serves this platform."""
    key = _platform_key()
    if key == "win":
        return "win64.zip"
    if key == "darwin":
        return "macarm.zip" if platform.machine().lower() in {"arm64", "aarch64"} else "mac.zip"
    return "linux.zip"


def asset_url(release: str, asset: str) -> str:
    """Return the address of one zip of ``release``."""
    return f"https://github.com/{BINARIES_REPOSITORY}/releases/download/{release}/{asset}"


def _pinned_digest(release: str, asset: str) -> str:
    """Return the sha256 of ``asset``; refuse a release with no digest in the package."""
    digest = RELEASE_ASSETS.get(release, {}).get(asset)
    if digest is None:
        raise SolverBinaryError(
            f"HydroModPy holds no sha256 for {asset} of MODFLOW release {release}, so it does "
            f"not install it. It installs release {', '.join(RELEASE_ASSETS)}. To run another "
            f"build, fetch it yourself (get-modflow <folder> --release-id {release}) and set "
            "HMP_BIN to that folder. Each run records the sha256 of the binary it used."
        )
    return digest


def download_solver_binaries(
    bindir: str | os.PathLike[str] | None = None,
    subset: Iterable[str] | None = None,
    *,
    quiet: bool = False,
    force: bool = False,
    release: str = DEFAULT_RELEASE,
) -> Path:
    """Install solver binaries from the zip of ``release``, verified against its sha256.

    ``bindir`` defaults to :func:`resolve_bin_path`. ``subset`` defaults to the
    full set of solvers this module knows about. The zip stays in the cache, so
    another subset costs no second download. When ``force`` is True it is
    fetched again. ``release`` pins the MODFLOW-ORG/executables tag.
    """
    target = Path(bindir).expanduser() if bindir else Path(resolve_bin_path())
    target.mkdir(parents=True, exist_ok=True)

    names = list(subset) if subset is not None else list(available_solvers())
    unknown = [name for name in names if name not in _SOLVER_FILENAMES]
    if unknown:
        raise ValueError(
            f"Unknown solver name(s): {unknown}. Expected subset of {list(available_solvers())}."
        )

    asset = _release_asset()
    digest = _pinned_digest(release, asset)
    url = asset_url(release, asset)
    if not quiet:
        logger.info("Downloading solver binaries %s (release=%s) into %s", names, release, target)
    try:
        archive = fetch_pinned(
            url,
            cache_dir() / "bin-archives" / f"modflow_executables-{release}-{asset}",
            sha256=digest,
            remedy=_mismatch_remedy(target),
            force=force,
        )
    except NetworkError as exc:
        raise _download_failed(release, url, target, exc) from exc
    _extract_solvers(archive, names, target)
    _write_manifest(target, release=release, asset=asset, solvers=names, replace=force)
    return target


def _mismatch_remedy(target: Path) -> str:
    """Say what to do when a download is not the file this version was released with."""
    return (
        "This is not the file this version of HydroModPy was released with, so do not use it. "
        "Check your proxy, try again later, and report it at "
        "https://github.com/HydroModPy/HydroModPy/issues if it stays. To run meanwhile, copy "
        f"executables you trust into {target}, or into a folder named by HMP_BIN."
    )


def _extract_solvers(archive: Path, names: list[str], target: Path) -> None:
    """Place the executables ``names`` of a verified zip in ``target``, one rename each."""
    with zipfile.ZipFile(archive) as bundle:
        present = set(bundle.namelist())
        for name in names:
            filename = exe_filename(name)
            if filename not in present:
                raise SolverBinaryError(
                    f"{archive} holds no {filename}, so {name} cannot be installed from it."
                )
            partial = target / f".{filename}.{os.getpid()}.part"
            try:
                with bundle.open(filename) as reader, partial.open("wb") as writer:
                    shutil.copyfileobj(reader, writer)
                ensure_platform_executable(partial).replace(target / filename)
            finally:
                partial.unlink(missing_ok=True)


def _download_failed(release: str, url: str, target: Path, exc: NetworkError) -> NetworkError:
    """Name the address, the cause and what to set, for a download that did not reach GitHub."""
    reason = exc.context.get("last_exception") or exc
    return NetworkError(
        f"Could not download the MODFLOW binaries of release {release} from {url}: {reason}. "
        "Behind a proxy, set HTTPS_PROXY (and HTTP_PROXY). "
        f"Without network, copy the executables into {target}, or into a folder named by "
        "HMP_BIN."
    )


def ensure_solver_binary(solver: str, bin_path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the exe for ``solver`` under ``bin_path``, downloading if needed.

    Behavior matrix:

    * ``bin_path`` is ``None`` and means ``resolve_bin_path()``: ``HMP_BIN`` when
      it is set, else the managed cache.
    * the folder is the managed cache and the binary is present → return its path.
    * the folder is the managed cache and the binary is missing → fetch
      it via :func:`download_solver_binaries`, then return the path
      (raises :class:`FileNotFoundError` if the download failed to
      produce the expected file).
    * the folder is not the managed cache and the binary is present → return
      its path; we never touch an external directory with a download.
    * the folder is not the managed cache and the binary is missing → log a
      warning and return the *expected* path. Solver execution will
      surface the missing-file error with its own diagnostics. This
      preserves the permissive pre-v0.6 behavior for callers that
      instantiate solvers without running them (e.g. unit tests for
      config validation).
    """
    target = Path(bin_path).expanduser() if bin_path else Path(resolve_bin_path())

    located = locate_solver_binary(target, solver)
    if located is not None:
        return Path(ensure_platform_executable(located))

    if is_managed_cache(target):
        with progress.status(f"Fetching {solver} binary"):
            download_solver_binaries(target, subset=[solver], quiet=True)
        located = locate_solver_binary(target, solver)
        if located is not None:
            return Path(ensure_platform_executable(located))
        raise FileNotFoundError(
            f"Solver '{solver}' not found under {target} after download attempt. "
            f"Expected file: {target / exe_filename(solver)}."
        )

    expected = target / exe_filename(solver)
    logger.warning(
        "Solver '%s' not found at %s (bin_path=%s). Returning the expected path; "
        "run `hmp install-binaries` or populate the directory to avoid a "
        "runtime error when the solver executes.",
        solver,
        expected,
        target,
    )
    return expected


def ensure_solver_library(
    solver: str = "libmf6", bin_path: str | os.PathLike[str] | None = None
) -> Path:
    """Resolve a MODFLOW shared library (e.g. ``libmf6``) under ``bin_path``.

    Mirrors :func:`ensure_solver_binary`: on a managed-cache miss the library is
    installed from the same zip before failing, keeping the api runner as zero-setup
    as the subprocess runner. ``bin_path`` defaults to :func:`resolve_bin_path`.
    """
    bindir = Path(bin_path).expanduser() if bin_path else Path(resolve_bin_path())
    found = locate_solver_binary(bindir, solver)
    if found is not None:
        return ensure_platform_executable(found)
    if is_managed_cache(bindir):
        with progress.status(f"Fetching {solver} library"):
            download_solver_binaries(bindir, subset=[solver], quiet=True)
        found = locate_solver_binary(bindir, solver)
        if found is not None:
            return ensure_platform_executable(found)
    raise FileNotFoundError(
        f"{exe_filename(solver)} not found in {bindir} after a download attempt. "
        "Run `hmp install-binaries` or copy the MODFLOW 6 shared library into the cache."
    )


_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")
_MF6_VERSION_PARITY_CHECKED = False
_MISMATCH_ENV_VAR = "HMP_SILENCE_MF6_VERSION_MISMATCH"


def mf6_executable_version(exe_path: str | os.PathLike[str]) -> str | None:
    """Return the MODFLOW 6 executable version (e.g. ``'6.6.3'``), or ``None``."""
    try:
        out = subprocess.run(  # noqa: S603 - trusted managed binary
            [str(exe_path), "-v"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = _VERSION_RE.search(f"{out.stdout}\n{out.stderr}")
    return match.group(1) if match else None


def libmf6_version(lib_path: str | os.PathLike[str]) -> str | None:
    """Return the libmf6 shared-library version via xmipy, or ``None``.

    Loads the library only to read its BMI ``get_version``; no simulation is
    initialized, so it is safe to call once before the isolated solves spawn.
    """
    try:
        from xmipy import XmiWrapper

        match = _VERSION_RE.search(str(XmiWrapper(str(lib_path)).get_version()))
        return match.group(1) if match else None
    except Exception:  # noqa: BLE001 - version probe must never break a solve
        return None


def _package_version_and_editable(name: str) -> tuple[str | None, bool]:
    """Return one Python package's version and whether it is a dev/editable install."""
    try:
        module = importlib.import_module(name)
    except Exception:  # noqa: BLE001 - a version probe must never break a solve
        return None, False
    version = getattr(module, "__version__", None)
    if version is None:
        try:
            from importlib.metadata import version as _metadata_version

            version = _metadata_version(name)
        except Exception:  # noqa: BLE001
            version = None
    origin = getattr(module, "__file__", "") or ""
    is_dev = bool(version) and ".dev" in str(version)
    is_editable = "site-packages" not in origin and "dist-packages" not in origin
    return version, bool(is_dev or is_editable)


def solver_python_stack() -> str:
    """Return the ``modflowapi``/``xmipy`` versions, flagged when dev/editable.

    The api runner loads libmf6 through these wrappers, so an unpinned dev/editable
    install is part of the reproducibility surface and worth recording once.
    """
    parts: list[str] = []
    for name in ("modflowapi", "xmipy"):
        version, editable = _package_version_and_editable(name)
        if version is None:
            parts.append(f"{name} (absent)")
        else:
            parts.append(f"{name} {version}{' (editable)' if editable else ''}")
    return ", ".join(parts)


@dataclass(frozen=True, slots=True)
class SolverEngine:
    """The binary a run actually executes, and how the run drives it.

    ``kind`` says what the file is (a standalone executable, or a shared
    library loaded in-process through the BMI/XMI wrappers) and
    ``execution_mode`` says how it was driven. They move together today, but
    provenance records both because a reader must not have to infer one from
    the other.
    """

    solver: str
    kind: Literal["executable", "library"]
    execution_mode: Literal["subprocess", "api"]
    path: Path
    version: str | None


def resolve_solver_engine(
    solver: str,
    *,
    execution_mode: str = "subprocess",
    bin_path: str | os.PathLike[str] | None = None,
) -> SolverEngine | None:
    """Return the engine a run executes, or ``None`` for a binary-less solver.

    ``execution_mode`` is the dispatch the run selected: ``'api'`` loads the
    MODFLOW 6 shared library, anything else runs the executable. Solvers with
    no bundled binary (Boussinesq, GR4J) return ``None``. Resolution failures
    (binary absent and not downloadable) also return ``None``: provenance must
    never be the reason a run does not start.
    """
    if execution_mode == "api" and solver == "modflow6":
        try:
            lib = ensure_solver_library("libmf6", bin_path)
        except Exception:  # noqa: BLE001 - provenance never breaks a run
            logger.debug("Could not resolve libmf6 for provenance", exc_info=True)
            return None
        return SolverEngine(
            solver=solver,
            kind="library",
            execution_mode="api",
            path=lib,
            version=libmf6_version(lib),
        )

    exe_name = SOLVER_EXECUTABLES.get(solver)
    if exe_name is None:
        return None
    try:
        exe = ensure_solver_binary(exe_name, bin_path)
    except Exception:  # noqa: BLE001 - provenance never breaks a run
        logger.debug("Could not resolve the %s executable for provenance", exe_name, exc_info=True)
        return None
    return SolverEngine(
        solver=solver,
        kind="executable",
        execution_mode="subprocess",
        path=exe,
        version=mf6_executable_version(exe),
    )


def warn_on_mf6_version_mismatch(
    exe_path: str | os.PathLike[str], lib_path: str | os.PathLike[str]
) -> None:
    """Log the mf6 exe and libmf6 versions once and warn on a major.minor mismatch.

    The api runner solves with libmf6 while the subprocess runner and the
    per-trial steady-state init use the exe, so a version skew means calibrated
    optima may not reproduce a subprocess ``hmp run``. A mismatch warns once (loud,
    with the fix); silence it with ``HMP_SILENCE_MF6_VERSION_MISMATCH``. It never
    raises, so an existing mixed install keeps working.
    """
    global _MF6_VERSION_PARITY_CHECKED
    if _MF6_VERSION_PARITY_CHECKED:
        return
    _MF6_VERSION_PARITY_CHECKED = True

    exe_v = mf6_executable_version(exe_path)
    lib_v = libmf6_version(lib_path)
    logger.info(
        "MODFLOW 6 engines: exe %s, libmf6 %s | %s",
        exe_v or "?",
        lib_v or "?",
        solver_python_stack(),
    )
    if not exe_v or not lib_v or exe_v.split(".")[:2] == lib_v.split(".")[:2]:
        return

    silence = os.environ.get(_MISMATCH_ENV_VAR, "")
    if silence.strip().lower() not in ("", "0", "false", "no"):
        return
    logger.warning(
        "MODFLOW 6 version mismatch: executable %s vs libmf6 %s. The api solves and the "
        "per-trial steady-state init use different engine builds, so calibrated optima may not "
        "reproduce a subprocess 'hmp run'. Re-align them with 'hmp install-binaries' (or set "
        "%s to silence).",
        exe_v,
        lib_v,
        _MISMATCH_ENV_VAR,
    )


__all__ = [
    "ensure_platform_executable",
    "DEFAULT_RELEASE",
    "MANIFEST_FILENAME",
    "RELEASE_ASSETS",
    "SOLVER_EXECUTABLES",
    "SOLVER_LIBRARIES",
    "SolverEngine",
    "asset_url",
    "available_solvers",
    "download_solver_binaries",
    "ensure_solver_binary",
    "ensure_solver_library",
    "exe_filename",
    "is_managed_cache",
    "libmf6_version",
    "locate_solver_binary",
    "mf6_executable_version",
    "read_manifest",
    "resolve_solver_engine",
    "solver_python_stack",
    "warn_on_mf6_version_mismatch",
]
