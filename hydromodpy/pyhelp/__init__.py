# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright © PyHelp Project Contributors
# https://github.com/cgq-qgc/pyhelp
#
# This file is part of PyHELP.
# Licensed under the terms of the MIT License.
# -----------------------------------------------------------------------------

import os
import sys
import shutil
import platform
import warnings
from pathlib import Path

from hydromodpy.tools import get_logger

logger = get_logger(__name__)

version_info = (0, 4, 1, 'dev0')
__version__ = '.'.join(map(str, version_info))
__appname__ = 'PyHELP'
__namever__ = __appname__ + " " + __version__
__date__ = '20/06/2022'
__project_url__ = "https://github.com/cgq-qgc/pyhelp"
__releases_url__ = __project_url__ + "/releases"
__releases_api__ = "https://api.github.com/repos/cgq-qgc/pyhelp/releases"

__rootdir__ = os.path.dirname(os.path.realpath(__file__))

# GitHub repository for pre-compiled HELP3O binaries
HELP3O_BINARIES_REPO = "bastien-boivin/HELP3O-binaries"
HELP3O_BINARIES_API = f"https://api.github.com/repos/{HELP3O_BINARIES_REPO}/releases/latest"
_GITHUB_HEADERS = {
    "User-Agent": f"hydromodpy-pyhelp/{__version__}",
    "Accept": "application/vnd.github+json",
}


def _get_cache_dir():
    """Get platform-specific cache directory for HydroModPy"""
    if sys.platform == "win32":
        cache_base = Path.home() / "AppData" / "Local" / "hydromodpy"
    elif sys.platform == "darwin":
        cache_base = Path.home() / "Library" / "Caches" / "hydromodpy"
    else:  # Linux
        cache_base = Path.home() / ".cache" / "hydromodpy"

    cache_base.mkdir(parents=True, exist_ok=True)
    return cache_base


def _get_binary_filename():
    """Get the expected binary filename for current platform/Python version"""
    py_ver = f"{sys.version_info.major}{sys.version_info.minor}"
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux":
        # Format: HELP3O.cpython-311-x86_64-linux-gnu.so
        return f"HELP3O.cpython-{py_ver}-{machine}-linux-gnu.so"
    elif system == "darwin":
        # Format: HELP3O.cpython-311-macosx_arm64.so ou HELP3O.cpython-311-macosx_x86_64.so
        if machine in ["arm64", "aarch64"]:
            arch = "arm64"
        else:
            arch = "x86_64"
        return f"HELP3O.cpython-{py_ver}-macosx_{arch}.so"
    elif system == "windows":
        # Format: HELP3O.cp311-win_amd64.pyd
        return f"HELP3O.cp{py_ver}-win_amd64.pyd"
    else:
        return None


def _download_help3o_binary():
    """Download HELP3O binary from GitHub releases"""
    import urllib.request
    import json
    import tarfile
    import zipfile

    binary_filename = _get_binary_filename()
    if not binary_filename:
        raise RuntimeError(f"Unsupported platform: {platform.system()} {platform.machine()}")

    cache_dir = _get_cache_dir()
    binary_path = cache_dir / binary_filename

    # If already downloaded, return
    if binary_path.exists():
        return binary_path

    logger.info(
        "Downloading HELP3O binary for %s Python %s.%s",
        platform.system(),
        sys.version_info.major,
        sys.version_info.minor,
    )

    try:
        # Get latest release info from GitHub API
        request = urllib.request.Request(HELP3O_BINARIES_API, headers=_GITHUB_HEADERS)
        with urllib.request.urlopen(request, timeout=30) as response:
            release_data = json.loads(response.read().decode())

        system_name = platform.system()

        # On macOS, look for bundled tarball with GCC libraries
        if system_name == "Darwin":
            bundle_filename = binary_filename.replace(".so", "_bundle.tar.gz")
            bundle_url = None
            for asset in release_data.get("assets", []):
                if asset["name"] == bundle_filename:
                    bundle_url = asset["browser_download_url"]
                    break

            if bundle_url:
                # Download and extract bundle
                bundle_path = cache_dir / bundle_filename
                logger.info("Downloading macOS bundle %s", bundle_filename)
                logger.debug("macOS bundle URL: %s", bundle_url)

                bundle_request = urllib.request.Request(bundle_url, headers=_GITHUB_HEADERS)
                with urllib.request.urlopen(bundle_request, timeout=60) as response, bundle_path.open("wb") as fh:
                    shutil.copyfileobj(response, fh)

                # Extract tarball to cache directory
                logger.info("Extracting bundle to %s", cache_dir)
                with tarfile.open(bundle_path, "r:gz") as tar:
                    tar.extractall(path=cache_dir)

                # Clean up tarball
                bundle_path.unlink()
                logger.info("HELP3O bundle extracted successfully")
                return binary_path

        # On Windows, prefer the bundle zip that contains the MinGW runtime
        if system_name == "Windows":
            bundle_filename = binary_filename.replace(".pyd", "_bundle.zip")
            bundle_url = None
            for asset in release_data.get("assets", []):
                if asset["name"] == bundle_filename:
                    bundle_url = asset["browser_download_url"]
                    break

            if bundle_url:
                bundle_path = cache_dir / bundle_filename
                logger.info("Downloading Windows bundle %s", bundle_filename)
                logger.debug("Windows bundle URL: %s", bundle_url)

                bundle_request = urllib.request.Request(bundle_url, headers=_GITHUB_HEADERS)
                with urllib.request.urlopen(bundle_request, timeout=60) as response, bundle_path.open("wb") as fh:
                    shutil.copyfileobj(response, fh)

                logger.info("Extracting Windows bundle to %s", cache_dir)
                with zipfile.ZipFile(bundle_path, "r") as zip_fh:
                    zip_fh.extractall(cache_dir)

                bundle_path.unlink(missing_ok=True)
                logger.info("HELP3O Windows bundle extracted successfully")
                return binary_path

        # Fallback: download standalone binary (for Linux/Windows or old macOS releases)
        binary_url = None
        for asset in release_data.get("assets", []):
            if asset["name"] == binary_filename:
                binary_url = asset["browser_download_url"]
                break

        if not binary_url:
            raise RuntimeError(
                f"Binary '{binary_filename}' not found in latest release.\n"
                f"Available binaries: {[a['name'] for a in release_data.get('assets', [])]}"
            )

        # Download binary
        logger.info("Downloading HELP3O binary from %s", binary_url)
        logger.debug("HELP3O binary destination %s", binary_path)

        binary_request = urllib.request.Request(binary_url, headers=_GITHUB_HEADERS)
        with urllib.request.urlopen(binary_request, timeout=60) as response, binary_path.open("wb") as fh:
            shutil.copyfileobj(response, fh)
        logger.info("HELP3O binary downloaded successfully")

        return binary_path

    except Exception as e:
        warnings.warn(
            f"Failed to download HELP3O binary: {e}\n"
            f"You can:\n"
            f"  1. Check your internet connection\n"
            f"  2. Download manually from: https://github.com/{HELP3O_BINARIES_REPO}/releases/latest\n"
            f"  3. Place {binary_filename} in {cache_dir}/",
            RuntimeWarning
        )
        return None


def _load_help3o_from_path(binary_path):
    """Load HELP3O module from a specific path"""
    import importlib.util
    import ctypes

    binary_path = Path(binary_path)
    dll_token = None

    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        try:
            dll_token = os.add_dll_directory(str(binary_path.parent))
        except FileNotFoundError:
            dll_token = None
        else:
            for dll in sorted(binary_path.parent.glob("lib*.dll")):
                try:
                    ctypes.WinDLL(str(dll))
                except OSError as exc:
                    logger.error("Failed to preload dependency %s: %s", dll.name, exc)
                    raise

    try:
        spec = importlib.util.spec_from_file_location("HELP3O", str(binary_path))
        if spec is None or spec.loader is None:
            raise ImportError(f"Failed to load HELP3O from {binary_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if dll_token is not None:
            dll_token.close()


_HELP3O_AVAILABLE = False
_HELP3O_ERROR = None
HELP3O = None


def ensure_help3o_loaded():
    """Load HELP3O on demand. Return the module or None if not usable."""
    global HELP3O, _HELP3O_AVAILABLE, _HELP3O_ERROR

    if HELP3O is not None:
        return HELP3O
    if _HELP3O_ERROR is not None:
        return None

    binary_filename = _get_binary_filename()
    if not binary_filename:
        _HELP3O_ERROR = RuntimeError(f"Unsupported platform: {platform.system()} {platform.machine()}")
        warnings.warn(str(_HELP3O_ERROR), ImportWarning)
        return None

    cache_dir = _get_cache_dir()
    binary_path = cache_dir / binary_filename

    if not binary_path.exists():
        binary_path = _download_help3o_binary() or binary_path

    if not binary_path.exists():
        _HELP3O_ERROR = FileNotFoundError(
            f"HELP3O binary {binary_filename} not found; download it into {cache_dir}"
        )
        warnings.warn(str(_HELP3O_ERROR), ImportWarning)
        return None

    try:
        HELP3O = _load_help3o_from_path(binary_path)
    except OSError as exc:
        _HELP3O_ERROR = exc
        logger.error("Failed to load HELP3O binary %s: %s", binary_path, exc)
        warnings.warn(
            f"HELP3O binary present at {binary_path} but could not be loaded: {exc}",
            ImportWarning,
        )
        return None
    except Exception as exc:
        _HELP3O_ERROR = exc
        logger.exception("Failed to load HELP3O binary from %s", binary_path)
        warnings.warn(
            f"HELP3O Fortran extension not available: {exc}\n"
            "PyHELP functionality will be limited.",
            ImportWarning,
        )
        return None

    _HELP3O_AVAILABLE = True
    return HELP3O


def help3o_available() -> bool:
    """Return True if HELP3O could be loaded successfully."""
    return ensure_help3o_loaded() is not None


def __getattr__(name):
    if name == "HELP3O":
        return ensure_help3o_loaded()
    raise AttributeError(f"module {__name__} has no attribute {name}")

try:
    from hydromodpy.pyhelp.managers import HelpManager
except ImportError as e:
    # We need to do this to avoid an error when building the
    # help extension with setup.py
    logger.warning("HelpManager import failed: %s", e)
