"""The licence a run may state, derived from the inputs it read.

The members are the source of every loaded record (its provider slug and
the digest of its bytes) and every tracked input file (its location and its
digest). A ``custom`` record is a user file: it counts through the tracked
file that holds its bytes, matched on sha256, or through the sidecar digests
of a tracked directory. A ``custom`` record no tracked file holds is
undetermined on its own, and so is a member whose licence cannot be read.
No member at all gives ``LicenseRef-undetermined``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import decode_workspace_path

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LicenceMember:
    """One input that contributes to the licence of a run."""

    source: str
    """Provider slug of a loaded record, or ``custom`` for a user file."""

    sha256: str | None
    """Digest of the bytes, when known."""


@dataclass(frozen=True, slots=True)
class TrackedPath:
    """One tracked input file of the configuration, as the run recorded it."""

    encoded_path: str
    """Workspace-encoded location of the file or directory."""

    sha256: str
    """Digest of the file, or of the directory tree."""


def _tracked_path(workspace: Path | None, encoded: str) -> Path | None:
    """Return the on-disk path of a tracked entry, or None when it cannot be read."""
    if workspace is None and not Path(encoded).is_absolute() and "://" not in encoded:
        return None
    return decode_workspace_path(workspace if workspace is not None else Path("/"), encoded)


def _sidecar_digests(directory: Path) -> set[str]:
    """Return the sha256 each sidecar under *directory* records for its file."""
    from hydromodpy.schema.sources import SIDECAR_SUFFIX

    found: set[str] = set()
    for item in directory.rglob(f"*{SIDECAR_SUFFIX}"):
        try:
            payload = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        digest = payload.get("sha256") if isinstance(payload, dict) else None
        if isinstance(digest, str) and digest:
            found.add(digest)
    return found


def run_licence(
    members: Iterable[LicenceMember],
    tracked: Iterable[TrackedPath],
    workspace: Path | None = None,
) -> str:
    """Return the licence a run may state from its loaded records and tracked files."""
    from hydromodpy.schema.job.inputset import UNDETERMINED
    from hydromodpy.schema.sources import derived_licence, input_licence, licence_for_source

    records = list(members)
    licences = [licence_for_source(m.source) for m in records if m.source != "custom"]
    held: set[str] = set()
    directories: list[Path] = []
    for entry in tracked:
        path = _tracked_path(workspace, entry.encoded_path)
        if path is None:
            licences.append(UNDETERMINED)
            continue
        licences.append(input_licence(path))
        if path.is_dir():
            directories.append(path)
        elif entry.sha256:
            held.add(entry.sha256)
    custom = [m.sha256 for m in records if m.source == "custom"]
    if any(digest is None or digest not in held for digest in custom):
        for directory in directories:
            held |= _sidecar_digests(directory)
    for digest in custom:
        if digest is None or digest not in held:
            licences.append(UNDETERMINED)
    if not licences:
        return UNDETERMINED_LICENSE
    return derived_licence(licences)


__all__ = ["LicenceMember", "TrackedPath", "run_licence"]
