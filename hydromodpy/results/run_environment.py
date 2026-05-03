"""Capture host environment metadata for the ``runs_environment`` table.

What
----
``capture_environment`` returns a typed snapshot of the Python runtime,
host hardware, git commit (HydroModPy + project root), installed packages,
and the SHA-256 of the active MODFLOW binary when known. Output matches
the column layout of :data:`hydromodpy.results.catalog_schema._RUNS_ENVIRONMENT_DDL`.

Why
---
ML pipelines that train on HydroModPy results need to filter / stratify by
hardware and software so that model performance is comparable across runs.
The snapshot is recorded once per simulation at registration time so the
data is reproducible weeks later.
"""

from __future__ import annotations

import hashlib
import os
import platform as _platform
import socket
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


class EnvironmentSnapshot(TypedDict, total=False):
    """Typed dict matching ``runs_environment`` columns."""

    python_version: str
    hydromodpy_version: str
    platform: str
    hostname: str
    user_name: str
    cpu_info: dict
    memory_gb: float | None
    git_commit: str | None
    project_git_commit: str | None
    mf6_binary_sha256: str | None
    mf6_version_text: str | None
    conda_env_hash: str | None
    env_packages: list[str]
    rng_seed: int | None


def _git_head(cwd: Path) -> str | None:
    """Return the short HEAD SHA at ``cwd``, or ``None`` if not a repo."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return None
    return out.strip() or None


def _hydromodpy_root() -> Path:
    """Return the on-disk root of the installed ``hydromodpy`` package."""
    return Path(__file__).resolve().parent.parent.parent


def _python_version() -> str:
    info = sys.version_info
    return f"{info.major}.{info.minor}.{info.micro}"


def _user_name() -> str | None:
    try:
        return os.getlogin()
    except OSError:
        # ``getlogin`` fails when the controlling tty is missing (CI, daemon).
        return os.environ.get("USER") or os.environ.get("LOGNAME")


def _memory_gb() -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    try:
        return round(psutil.virtual_memory().total / 1e9, 2)
    except Exception:
        return None


def _cpu_info() -> dict:
    info: dict = {"machine": _platform.machine(), "processor": _platform.processor()}
    try:
        import cpuinfo
    except ImportError:
        return info
    try:
        raw = cpuinfo.get_cpu_info()
    except Exception:
        return info
    for key in ("brand_raw", "arch", "bits", "count", "hz_advertised_friendly"):
        val = raw.get(key)
        if val is not None:
            info[key] = val
    return info


def _hydromodpy_version() -> str:
    from hydromodpy.core.version import __version__

    return __version__


def _env_packages() -> list[str]:
    """Return ``pip freeze``-equivalent lines, or an empty list on failure."""
    try:
        out = subprocess.check_output(
            [sys.executable, "-m", "pip", "list", "--format=freeze"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _binary_sha256(path: Path | str | None) -> str | None:
    if path is None:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    try:
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _mf6_version_text(path: Path | str | None) -> str | None:
    """Capture the textual MF6 version banner from ``mf6 --version``."""
    if path is None:
        return None
    p = Path(path)
    if not p.is_file() or not os.access(p, os.X_OK):
        return None
    try:
        out = subprocess.check_output(
            [str(p), "--version"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return out.strip() or None


def _conda_env_hash() -> str | None:
    """Return SHA-256 of ``mamba env export`` (or ``conda env export``).

    Stable hash of the active conda/mamba environment, including channel
    pins and exact package versions. Returns None when neither tool is on
    the PATH or the export fails.
    """
    for tool in ("mamba", "conda"):
        try:
            out = subprocess.check_output(
                [tool, "env", "export", "--no-builds"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=15,
            )
        except (subprocess.SubprocessError, OSError, FileNotFoundError):
            continue
        if not out.strip():
            continue
        return hashlib.sha256(out.encode("utf-8")).hexdigest()
    return None


def capture_environment(
    *,
    project_root: Path | str | None = None,
    mf6_binary_path: Path | str | None = None,
) -> EnvironmentSnapshot:
    """Snapshot the host environment for one simulation.

    Parameters
    ----------
    project_root
        Path to the user's project (workflow root). Used to record the
        project's git commit when the user works inside a versioned
        project. ``None`` skips that field.
    mf6_binary_path
        Path to the MODFLOW binary used by this run. The SHA-256 is
        computed and stored when readable. ``None`` skips it.
    """
    snapshot: EnvironmentSnapshot = {
        "python_version": _python_version(),
        "hydromodpy_version": _hydromodpy_version(),
        "platform": _platform.platform(),
        "hostname": socket.gethostname(),
        "user_name": _user_name() or "",
        "cpu_info": _cpu_info(),
        "memory_gb": _memory_gb(),
        "git_commit": _git_head(_hydromodpy_root()),
        "project_git_commit": _git_head(Path(project_root)) if project_root else None,
        "mf6_binary_sha256": _binary_sha256(mf6_binary_path),
        "mf6_version_text": _mf6_version_text(mf6_binary_path),
        "conda_env_hash": _conda_env_hash(),
        "env_packages": _env_packages(),
    }
    return snapshot
