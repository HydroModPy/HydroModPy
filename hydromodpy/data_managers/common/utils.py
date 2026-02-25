"""Small utility helpers shared across data managers."""

from __future__ import annotations


def safe_file_token(value: str) -> str:
    """Return a filesystem-safe token from an arbitrary identifier.

    Any non-alphanumeric character is replaced by ``_``.
    """
    return "".join(char if char.isalnum() else "_" for char in str(value))
