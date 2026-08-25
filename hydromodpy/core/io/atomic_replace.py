"""Replace one file by another in a single rename, readers included.

A publish that unlinks before it moves leaves the name missing for an
instant; one that writes into the live file leaves it half-written for much
longer. Both are visible to whoever reads the file meanwhile, so the only
safe publish is one atomic rename. This module is that rename, for the two
platforms HydroModPy runs on.
"""

from __future__ import annotations

import os
from pathlib import Path

# Win32 constants used by the POSIX-semantics rename, from winbase.h and winnt.h.
_FILE_RENAME_INFO_EX = 22
_RENAME_REPLACE_IF_EXISTS = 0x1
_RENAME_POSIX_SEMANTICS = 0x2
_DELETE_ACCESS = 0x00010000
_SYNCHRONIZE_ACCESS = 0x00100000
_SHARE_READ_WRITE_DELETE = 0x00000007
_OPEN_EXISTING = 3


def rename_over_open_file(source: Path, target: Path) -> None:
    """Rename ``source`` onto ``target`` even while ``target`` is open.

    On POSIX this is ``os.replace`` and nothing more: ``rename(2)`` unlinks
    the target from its directory, the handles already on it keep reading the
    bytes they opened, and the new name appears in the same atomic step.

    On Windows ``os.replace`` calls ``MoveFileExW``, which deletes the target
    eagerly and therefore raises ``PermissionError`` as soon as another handle
    is on it. The rename is then asked of the kernel directly with
    ``FILE_RENAME_POSIX_SEMANTICS``, which unlinks the target instead of
    deleting it and so behaves like ``rename(2)``. It needs Windows 10 1709 or
    later on NTFS, and the open handles must have allowed ``FILE_SHARE_DELETE``;
    anywhere else it raises ``OSError`` and the target is left untouched.
    """
    try:
        os.replace(source, target)
        return
    except PermissionError:
        if os.name != "nt":
            raise

    _rename_with_posix_semantics(source, target)


def _rename_with_posix_semantics(source: Path, target: Path) -> None:
    """Ask the Windows kernel for a ``rename(2)``-shaped rename."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.SetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    name = str(target)

    class _RenameInfo(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * (len(name) + 1)),
        ]

    handle = kernel32.CreateFileW(
        str(source),
        _DELETE_ACCESS | _SYNCHRONIZE_ACCESS,
        _SHARE_READ_WRITE_DELETE,
        None,
        _OPEN_EXISTING,
        0,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = _RenameInfo(
            Flags=_RENAME_REPLACE_IF_EXISTS | _RENAME_POSIX_SEMANTICS,
            RootDirectory=None,
            FileNameLength=len(name) * ctypes.sizeof(wintypes.WCHAR),
            FileName=name,
        )
        renamed = kernel32.SetFileInformationByHandle(
            handle, _FILE_RENAME_INFO_EX, ctypes.byref(info), ctypes.sizeof(info)
        )
        if not renamed:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)


__all__ = ["rename_over_open_file"]
