"""The names MODFLOW 6 gives a model and its output files.

MODFLOW 6 caps a model name at 16 characters and refuses a space in it.
"""

from __future__ import annotations

import hashlib
import re


def mf6_safe_name(name: str, max_len: int = 16) -> str:
    """Return a safe MODFLOW 6 model name: no whitespace, hashed when too long.

    MODFLOW 6 rejects a model name that contains a space, so every whitespace run
    collapses to a single underscore before the length check. The name is
    lowercased: flopy compares ``model_name.lower()`` to a package path that keeps
    its case, and a capital letter makes it fail to write the MVR. Names longer
    than ``max_len`` are hashed to stay unique and within the identifier limit.
    """
    text = re.sub(r"\s+", "_", str(name).strip()).lower()
    if len(text) <= max_len:
        return text
    if max_len <= 6:
        return text[:max_len]
    digest = hashlib.sha1(str(name).encode("utf-8")).hexdigest()[:6]
    prefix_len = max_len - 7
    return f"{text[:prefix_len]}_{digest}"


def mf6_output_name(model, extension: str = ".cbc") -> str:
    """Return the output file stem, which is the requested model name.

    The length of the path is held by the reservation of the run folder
    (``check_project_root``) and by the exact check of ``windows_paths``, so the
    name is the same on every system. ``extension`` is kept for the callers.
    """
    return str(getattr(model, "model_name", "") or "model")


__all__ = ["mf6_output_name", "mf6_safe_name"]
