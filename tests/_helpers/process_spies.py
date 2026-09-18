"""The write spies a capability confinement gate runs its subject under.

Lifted out of the ``data-fetch`` gate when a second capability needed the same
script: ``domain-build`` declares it writes nowhere but its job directory, and a
claim of that shape is only worth what the spy behind it catches. The socket
spies stayed where they are -- the two that exist differ, one asserting that
nothing non-local was resolved and the other that everything resolved was
declared -- and only this constant was shared.
"""

from __future__ import annotations

WRITE_SPIES = (
    "import builtins, io, os, tempfile\n"
    "seen = []\n"
    "def _note(target):\n"
    "    try:\n"
    "        seen.append(os.fspath(target))\n"
    "    except TypeError:\n"
    # A file descriptor, not a path: whatever it names was opened by a call
    # this spy already saw, or by a C library no spy of this kind can see.
    "        pass\n"
    "real_mkdtemp, real_mkstemp = tempfile.mkdtemp, tempfile.mkstemp\n"
    "real_bopen, real_ioopen, real_osopen = builtins.open, io.open, os.open\n"
    "real_mkdir, real_makedirs = os.mkdir, os.makedirs\n"
    "real_rename, real_replace = os.rename, os.replace\n"
    "WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND\n"
    "def spy_mkdtemp(*a, **k):\n"
    "    path = real_mkdtemp(*a, **k)\n"
    "    _note(path)\n"
    "    return path\n"
    "def spy_mkstemp(*a, **k):\n"
    "    handle, path = real_mkstemp(*a, **k)\n"
    "    _note(path)\n"
    "    return handle, path\n"
    "def _spy_open(real):\n"
    "    def opener(file, mode='r', *a, **k):\n"
    "        if any(flag in mode for flag in 'wax+'):\n"
    "            _note(file)\n"
    "        return real(file, mode, *a, **k)\n"
    "    return opener\n"
    "def spy_osopen(path, flags, *a, **k):\n"
    "    if flags & WRITE_FLAGS:\n"
    "        _note(path)\n"
    "    return real_osopen(path, flags, *a, **k)\n"
    "def spy_mkdir(path, *a, **k):\n"
    "    _note(path)\n"
    "    return real_mkdir(path, *a, **k)\n"
    "def spy_makedirs(name, *a, **k):\n"
    "    _note(name)\n"
    "    return real_makedirs(name, *a, **k)\n"
    "def spy_rename(src, dst, *a, **k):\n"
    "    _note(dst)\n"
    "    return real_rename(src, dst, *a, **k)\n"
    "def spy_replace(src, dst, *a, **k):\n"
    "    _note(dst)\n"
    "    return real_replace(src, dst, *a, **k)\n"
    "tempfile.mkdtemp, tempfile.mkstemp = spy_mkdtemp, spy_mkstemp\n"
    # ``io.open`` as well as ``builtins.open``: they are one function object, but
    # ``pathlib`` reaches it through the ``io`` module, so rebinding only the
    # builtin leaves ``Path.write_text`` invisible -- which is exactly the hole
    # the adversarial gate walked through.
    "builtins.open, io.open = _spy_open(real_bopen), _spy_open(real_ioopen)\n"
    "os.open, os.mkdir, os.makedirs = spy_osopen, spy_mkdir, spy_makedirs\n"
    "os.rename, os.replace = spy_rename, spy_replace\n"
)
"""Every Python-level way this tree creates something on disk, recorded.

The ceiling is stated rather than hidden: a C extension that opens its own
descriptors -- GDAL under ``to_file``, netCDF4 under ``to_netcdf``, pyarrow
under ``write_table`` -- is not seen here, the same way a child process is not
seen by a socket spy. The controlled ``HOME`` below is what covers that gap for
the one location it matters at, and the job directory listing covers the rest.
"""


__all__ = ["WRITE_SPIES"]
