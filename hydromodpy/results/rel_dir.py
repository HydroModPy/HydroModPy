"""One check for every ``rel_dir`` a result document carries.

Why
---
A run, a trial or a session is found again by its directory relative to the
project root. The grammar of that path has one owner,
:func:`hydromodpy.core.state.paths.parse_rel_dir`. Every model field that
stores such a path validates it here, so a document cannot hold an absolute
path, a ``..`` or a directory under another root.
"""

from __future__ import annotations

from hydromodpy.core.state.paths import parse_rel_dir


def checked_rel_dir(value: str) -> str:
    """Return *value* when it is a result directory; raise ``ValueError`` otherwise.

    Accepted forms are those of :func:`~hydromodpy.core.state.paths.parse_rel_dir`:
    ``runs/<name>``, ``sessions/<name>`` and ``sessions/<name>/trials/<nnnn>``.
    """
    return parse_rel_dir(value).as_posix()


__all__ = ["checked_rel_dir"]
