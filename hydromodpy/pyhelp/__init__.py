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
import platform
import warnings
from pathlib import Path

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

    binary_filename = _get_binary_filename()
    if not binary_filename:
        raise RuntimeError(f"Unsupported platform: {platform.system()} {platform.machine()}")

    cache_dir = _get_cache_dir()
    binary_path = cache_dir / binary_filename

    # If already downloaded, return
    if binary_path.exists():
        return binary_path

    print(f"Downloading HELP3O binary for {platform.system()} Python {sys.version_info.major}.{sys.version_info.minor}...")

    try:
        # Get latest release info from GitHub API
        with urllib.request.urlopen(HELP3O_BINARIES_API) as response:
            release_data = json.loads(response.read().decode())

        # Find the binary in assets
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
        print(f"  URL: {binary_url}")
        print(f"  Destination: {binary_path}")
        urllib.request.urlretrieve(binary_url, binary_path)
        print(f"✓ HELP3O binary downloaded successfully")

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

    spec = importlib.util.spec_from_file_location("HELP3O", binary_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Failed to load HELP3O from {binary_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Try to import the HELP3O Fortran extension
_HELP3O_AVAILABLE = False
HELP3O = None

# Try to load from cache directory or download from GitHub
cache_dir = _get_cache_dir()
binary_filename = _get_binary_filename()

if binary_filename:
    binary_path = cache_dir / binary_filename

    if binary_path.exists():
        # Binary already in cache
        try:
            HELP3O = _load_help3o_from_path(binary_path)
            _HELP3O_AVAILABLE = True
        except Exception as e:
            warnings.warn(f"Failed to load cached HELP3O binary: {e}", ImportWarning)
    else:
        # Download from GitHub
        try:
            binary_path = _download_help3o_binary()
            if binary_path and binary_path.exists():
                HELP3O = _load_help3o_from_path(binary_path)
                _HELP3O_AVAILABLE = True
        except Exception as e:
            warnings.warn(
                f"HELP3O Fortran extension not available: {e}\n"
                "PyHELP functionality will be limited.",
                ImportWarning
            )

try:
    from hydromodpy.pyhelp.managers import HelpManager
except ImportError as e:
    # We need to do this to avoid an error when building the
    # help extension with setup.py
    print('ImportError:', e)
