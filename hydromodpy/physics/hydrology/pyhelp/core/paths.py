# -----------------------------------------------------------------------------
# Copyright © PyHelp Project Contributors
# https://github.com/cgq-qgc/pyhelp
#
# This file is part of PyHELP.
# Licensed under the terms of the MIT License.
# -----------------------------------------------------------------------------

"""Cache paths and on-demand loader for the HELP3O Fortran extension.

HELP3O is native code loaded into this process, so it comes from one pinned
release: one tag, and one sha256 per platform and Python version. The check of
:mod:`hydromodpy.core.io.pinned_download` runs before every load, in every process.
A platform the release does not cover is refused, and nothing else is ever loaded.
A new tag is a number change, under the rule of the page
``contribute/architecture/how-to/cut-a-release``.

On Linux the asset is the extension itself. On macOS and Windows it is a bundle
with the compiler runtime beside the extension, so the files loaded are checked
against the members of the verified bundle.
"""

import contextlib
import os
import platform
import sys
import tarfile
import zipfile
from collections.abc import Iterator
from pathlib import Path

from hydromodpy.core.console import progress
from hydromodpy.core.exceptions import NetworkError, SolverBinaryError
from hydromodpy.core.io.pinned_download import fetch_pinned
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import cache_dir as _hmp_cache_dir

logger = get_logger(__name__)

version_info = (0, 4, 1, "dev0")
__version__ = ".".join(map(str, version_info))
__appname__ = "PyHELP"
__namever__ = __appname__ + " " + __version__
__date__ = "20/06/2022"
__project_url__ = "https://github.com/cgq-qgc/pyhelp"
__releases_url__ = __project_url__ + "/releases"
__releases_api__ = "https://api.github.com/repos/cgq-qgc/pyhelp/releases"

__rootdir__ = os.path.dirname(os.path.realpath(__file__))

HELP3O_BINARIES_REPO = "HydroModPy/HELP3O-binaries"
"""GitHub repository of the pre-compiled HELP3O binaries."""

HELP3O_RELEASE = "v2025.11-34"
"""The tag of that repository HydroModPy loads."""

HELP3O_ASSETS: dict[str, str] = {
    "HELP3O.cpython-311-x86_64-linux-gnu.so": (
        "9827073946ef0ca7576c35de7799de76757af6efd90bbe7dc666b15224ca5ea0"
    ),
    "HELP3O.cpython-312-x86_64-linux-gnu.so": (
        "01a5a3de10cde4005eca7782566e4675a5b747c344dc585dbd9f190f66e303b9"
    ),
    "HELP3O.cpython-313-x86_64-linux-gnu.so": (
        "2c5f2d68eafefc62b19417303c144d7ddeedadd63c3562ad70ca762655b28dd3"
    ),
    "HELP3O.cpython-311-macosx_arm64_bundle.tar.gz": (
        "69ddc57830950f111cb37a51c71d8274b166957898a971ee949974a809b2c73e"
    ),
    "HELP3O.cpython-312-macosx_arm64_bundle.tar.gz": (
        "14ad4c7e3f4de6feb037382c0fc41ea6fd8f009047c92e987e51b346629806d1"
    ),
    "HELP3O.cpython-313-macosx_arm64_bundle.tar.gz": (
        "31b44321d17ce1c4556106bba5dd62d5698272be61112a4296949fa1aaf6d677"
    ),
    "HELP3O.cpython-311-macosx_x86_64_bundle.tar.gz": (
        "7744bf6acb0d858f5d73ff1eb24a3f9a27e0bf2764ff7596cb2cafc456b40416"
    ),
    "HELP3O.cpython-312-macosx_x86_64_bundle.tar.gz": (
        "3b08717c457b15d1a182c33a41322319f025a2c41b07b6c87638718da843f92a"
    ),
    "HELP3O.cpython-313-macosx_x86_64_bundle.tar.gz": (
        "0a89f617b14b67946bb352c0d9db2c2fb73618e935c2f572d8174ef19fddaadc"
    ),
    "HELP3O.cp311-win_amd64_bundle.zip": (
        "344b024a538b316a0c61f50c55c7def8e12068c5e0385a45fbabef711c234105"
    ),
    "HELP3O.cp312-win_amd64_bundle.zip": (
        "3ccad537b25260950221edae0ee81868b370f1321f36d3d0246d959332670fed"
    ),
    "HELP3O.cp313-win_amd64_bundle.zip": (
        "fd8787ecdf6ff1e7f893e61bdebfda261c129b726775fa41825bc3f4fbb85b1c"
    ),
}
"""The sha256 of the asset of :data:`HELP3O_RELEASE` for each platform and Python version."""

_COVERED = "Python 3.11, 3.12 and 3.13 on Linux x86_64, macOS arm64 and x86_64, and Windows amd64"


def _get_binary_filename() -> str:
    """Return the name of the extension for this platform and Python version."""
    py_ver = f"{sys.version_info.major}{sys.version_info.minor}"
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux":
        return f"HELP3O.cpython-{py_ver}-{machine}-linux-gnu.so"
    if system == "darwin":
        arch = "arm64" if machine in {"arm64", "aarch64"} else machine
        return f"HELP3O.cpython-{py_ver}-macosx_{arch}.so"
    if system == "windows":
        arch = "amd64" if machine in {"amd64", "x86_64"} else machine
        return f"HELP3O.cp{py_ver}-win_{arch}.pyd"
    return f"HELP3O.cp{py_ver}-{system}_{machine}"


def _asset_filename(binary_filename: str) -> str:
    """Return the name of the asset that holds the extension."""
    if binary_filename.endswith(".pyd"):
        return binary_filename.removesuffix(".pyd") + "_bundle.zip"
    if "-macosx_" in binary_filename:
        return binary_filename.removesuffix(".so") + "_bundle.tar.gz"
    return binary_filename


def _bundle_members(archive: Path) -> Iterator[tuple[str, bytes]]:
    """Yield the name and the bytes of each file of a verified bundle."""
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                yield name, bundle.read(name)
        return
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            reader = bundle.extractfile(member) if member.isfile() else None
            if reader is not None:
                yield member.name, reader.read()


def _unpack_bundle(archive: Path, folder: Path) -> Path:
    """Make the files of *folder* equal to the members of a verified bundle, and return it."""
    folder.mkdir(parents=True, exist_ok=True)
    for name, payload in _bundle_members(archive):
        target = folder / Path(name).name
        if target.is_file() and target.read_bytes() == payload:
            continue
        partial = target.with_name(f".{target.name}.{os.getpid()}.part")
        partial.write_bytes(payload)
        partial.replace(target)
    return folder


def _install_help3o() -> Path:
    """Return the extension of this platform, verified against its pin in this very call."""
    binary_filename = _get_binary_filename()
    asset = _asset_filename(binary_filename)
    sha256 = HELP3O_ASSETS.get(asset)
    if sha256 is None:
        raise SolverBinaryError(
            f"HELP3O has no pinned build for Python {sys.version_info.major}."
            f"{sys.version_info.minor} on {platform.system()} {platform.machine()} (asset "
            f"{asset}). Release {HELP3O_RELEASE} of {HELP3O_BINARIES_REPO} covers {_COVERED}. "
            "HydroModPy loads no extension it cannot verify, so run on one of these."
        )

    folder = _hmp_cache_dir() / "help3o" / HELP3O_RELEASE
    url = f"https://github.com/{HELP3O_BINARIES_REPO}/releases/download/{HELP3O_RELEASE}/{asset}"
    present = (folder / asset).is_file()
    try:
        with contextlib.nullcontext() if present else progress.status("Downloading HELP3O binary"):
            verified = fetch_pinned(
                url,
                folder / asset,
                sha256=sha256,
                remedy=(
                    f"This is not the {asset} this version of HydroModPy was released with, so "
                    "it will not be loaded. Check your proxy, try again later, and report it at "
                    "https://github.com/HydroModPy/HydroModPy/issues if it stays."
                ),
            )
    except NetworkError as exc:
        raise NetworkError(
            f"Could not download HELP3O from {url}: {exc.context.get('last_exception') or exc}. "
            "Behind a proxy, set HTTPS_PROXY (and HTTP_PROXY). Without network, download that "
            f"file elsewhere and place it in {folder}: it is checked against its pin before "
            "it is loaded."
        ) from exc

    if asset == binary_filename:
        return verified
    return _unpack_bundle(verified, folder / Path(binary_filename).stem) / binary_filename


def _load_help3o_from_path(binary_path):
    """Load HELP3O module from a specific path"""
    import ctypes
    import importlib.util

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


HELP3O = None


def ensure_help3o_loaded():
    """Return the HELP3O module, loaded on demand from the verified extension.

    Refuses by name a platform the pinned release does not cover, bytes that do not
    hash to the pin and an extension that does not load.
    """
    global HELP3O

    if HELP3O is None:
        binary_path = _install_help3o()
        try:
            HELP3O = _load_help3o_from_path(binary_path)
        except (OSError, ImportError) as exc:
            raise SolverBinaryError(
                f"The HELP3O extension {binary_path} passed its sha256 check but did not load "
                f"on this system: {exc}."
            ) from exc
    return HELP3O
