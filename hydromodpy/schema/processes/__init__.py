"""The process descriptions this build ships, read from package data.

One JSON document per capability, generated from the declaration and the
Pydantic request model by ``python -m tools.processes`` and committed next to
this module. A shim reads them to learn what it can invoke without importing
HydroModPy, and a gate refuses a committed file that the generator no longer
reproduces.

The file name carries the **major** version: a breaking change to inputs or
outputs mints ``terrain-delineate@2.json`` and both ship side by side, while a
compatible change bumps ``version`` inside the existing file. A caller pins the
major and survives a minor bump.

Nothing here generates anything. This module reads package data with
``importlib.resources``, so it works the same from a source checkout and from
an installed wheel, and it imports no model, no engine and no runtime.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from hydromodpy.core.exceptions import JobUsageError

INDEX_FILENAME = "index.json"
"""Capability id to file, version and title. The only entry point of the set."""

PROCESS_PROFILE = "urn:hmp:profile:process:v1"
"""The profile a description conforms to. Resolves to nothing, by design."""

INDEX_PROFILE = "urn:hmp:profile:process-index:v1"
"""The profile the index conforms to."""


def description_filename(capability_id: str, major: int) -> str:
    """Return the package-data file name of one description."""
    return f"{capability_id}@{major}.json"


def _read(filename: str) -> dict[str, Any]:
    resource = files(__name__).joinpath(filename)
    return json.loads(resource.read_text(encoding="utf-8"))


def read_index() -> dict[str, Any]:
    """Return the committed index of every description this build ships."""
    return _read(INDEX_FILENAME)


def described_ids() -> tuple[str, ...]:
    """Return every capability id the index names, sorted."""
    return tuple(sorted(entry["id"] for entry in read_index()["processes"]))


def _resolve_file(capability_id: str, major: int | None) -> str:
    """Return the file name of one description, refusing an id nobody describes.

    :class:`JobUsageError` and not a file error: the id comes from a caller, so
    getting it wrong is an invocation mistake, which is the one failure a shim
    has to tell apart from the job failing.
    """
    index = read_index()
    for entry in index["processes"]:
        if entry["id"] != capability_id:
            continue
        if major is not None and entry["major"] != major:
            continue
        return str(entry["file"])

    served = ", ".join(sorted(entry["id"] for entry in index["processes"])) or "none"
    pinned = f" at major {major}" if major is not None else ""
    raise JobUsageError(
        f"no process description for {capability_id!r}{pinned}; this build describes {served}"
    )


def read_description_text(capability_id: str, major: int | None = None) -> str:
    """Return the exact bytes of one description, as they ship in the wheel.

    With *major* omitted, the index decides which one this build serves. The
    text and not a re-render: what a caller reads out of a pipe and what a
    caller reads out of the wheel are then the same document, and nothing can
    make them disagree.
    """
    return files(__name__).joinpath(_resolve_file(capability_id, major)).read_text(encoding="utf-8")


def read_description(capability_id: str, major: int | None = None) -> dict[str, Any]:
    """Return the description of one capability, parsed."""
    return json.loads(read_description_text(capability_id, major))


__all__ = [
    "INDEX_FILENAME",
    "INDEX_PROFILE",
    "PROCESS_PROFILE",
    "described_ids",
    "description_filename",
    "read_description",
    "read_description_text",
    "read_index",
]
