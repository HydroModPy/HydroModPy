"""Place the files and station rows of an install index under a workspace.

Every placement is planned before one is written. A file already there with
the same bytes costs nothing. A file absent is copied, with its sidecar. A
file there with other bytes is somebody's: the caller decides whether it is
kept (``hmp example add``), replaced (``--force``) or refused by name with
both digests (an import), and :func:`refuse_conflicts` refuses before
anything is written. A station row is merged into its registry the same way:
a row of the same id with other values is a conflict.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import shutil
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from hydromodpy.core.exceptions import DataRequestError, ImportConflictError
from hydromodpy.core.payload.index import SIDECAR_SUFFIX, PayloadFile, PayloadStation

Status = Literal["unchanged", "absent", "differs"]
"""What a destination holds against the file of the index."""


class PayloadConflictError(ImportConflictError):
    """A file or a station row of a package would replace another one; nothing was written."""

    def __init__(self, conflicts: Sequence[str], *, advice: str) -> None:
        self.conflicts = tuple(conflicts)
        lines = "\n".join(f"  {line}" for line in self.conflicts)
        super().__init__(f"{len(self.conflicts)} conflict(s), nothing written:\n{lines}\n{advice}")


@dataclass(frozen=True, slots=True)
class Placement:
    """Where one file of the index lands, and what is there now."""

    item: PayloadFile
    path: Path
    status: Status
    found_sha256: str | None = None
    """Digest of the bytes there, when they differ."""

    @property
    def label(self) -> str:
        """The destination as the index names it."""
        return self.item.dest if self.item.root == "workspace" else f"<project>/{self.item.dest}"

    def conflict(self) -> str:
        """Say which bytes are there and which the package brings."""
        return (
            f"{self.label}: the workspace holds sha256 {self.found_sha256}, "
            f"the package brings sha256 {self.item.sha256}"
        )


@dataclass(slots=True)
class StationMerge:
    """One station registry with the rows of the index merged in."""

    dest: str
    path: Path
    header: list[str]
    rows: list[dict[str, str]]
    added: list[str] = field(default_factory=list)
    """Labels of the rows the registry did not hold."""
    differing: list[tuple[str, PayloadStation]] = field(default_factory=list)
    """Labels of the rows held under the same id with other values, and the wanted row."""

    @property
    def changed(self) -> bool:
        return bool(self.added)


def destination(root: Path, dest: str) -> Path:
    """Resolve *dest* under *root*, refusing a destination outside it."""
    base = Path(root).resolve()
    candidate = (base / dest).resolve()
    if base not in candidate.parents:
        raise DataRequestError(
            f"The destination {dest!r} resolves outside the workspace or project {base}. "
            "A package may only write under the workspace root or its project."
        )
    return candidate


def plan_files(roots: Mapping[str, Path], files: Iterable[PayloadFile]) -> list[Placement]:
    """Return where each file lands and what is there now; nothing is written.

    *roots* maps ``"workspace"`` (and ``"project"`` when the index has
    project files) to the folder a destination is relative to.
    """
    placements: list[Placement] = []
    for item in files:
        path = destination(roots[item.root], item.dest)
        if not path.is_file():
            placements.append(Placement(item, path, "absent"))
            continue
        found = sha256_of(path)
        status: Status = "unchanged" if found == item.sha256 else "differs"
        placements.append(
            Placement(item, path, status, found_sha256=None if status == "unchanged" else found)
        )
    return placements


def refuse_conflicts(
    placements: Sequence[Placement],
    merges: Sequence[StationMerge] = (),
    *,
    others: Sequence[str] = (),
    advice: str,
) -> None:
    """Raise :class:`PayloadConflictError` naming every conflict; return when there is none."""
    conflicts = [placement.conflict() for placement in placements if placement.status == "differs"]
    for merge in merges:
        conflicts += [
            f"{label}: the registry holds other values than the package"
            for label, _ in merge.differing
        ]
    conflicts += list(others)
    if conflicts:
        raise PayloadConflictError(conflicts, advice=advice)


def write_file(placement: Placement, blob: Path, *, sidecar: Path | None = None) -> None:
    """Copy the bytes of *placement* from *blob*, and its sidecar beside it when given.

    The bytes land under a temporary name and are renamed into place, so a
    reader never sees part of a file. A sidecar already there is left as it is.
    """
    target = placement.path
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.{os.getpid()}.partial")
    shutil.copyfile(blob, partial)
    os.replace(partial, target)
    if sidecar is not None:
        described = target.with_name(target.name + SIDECAR_SUFFIX)
        if not described.exists():
            shutil.copyfile(sidecar, described)


def plan_stations(workspace: Path, stations: Iterable[PayloadStation]) -> list[StationMerge]:
    """Return each registry with the rows of the index merged in; nothing is written.

    A row the registry holds with the same values is left alone. A row the
    registry does not hold is added. A row held under the same id with other
    values is listed in ``differing``, for the caller to keep, replace or refuse.
    """
    by_registry: dict[str, list[PayloadStation]] = {}
    for station in stations:
        by_registry.setdefault(station.dest, []).append(station)
    merges: list[StationMerge] = []
    for dest, wanted in by_registry.items():
        path = destination(workspace, dest)
        header, rows = read_registry(path)
        merge = StationMerge(dest=dest, path=path, header=header, rows=rows)
        for station in wanted:
            values = dict(station.row)
            label = f"{dest} (station {station.id})"
            index = next((i for i, row in enumerate(rows) if row.get("id") == station.id), None)
            if index is not None and all(rows[index].get(k) == v for k, v in values.items()):
                continue
            if index is not None:
                merge.differing.append((label, station))
                continue
            merge.header.extend(key for key in values if key not in merge.header)
            merge.rows.append(values)
            merge.added.append(label)
        merges.append(merge)
    return merges


def write_stations(merges: Sequence[StationMerge], *, replace: bool = False) -> list[str]:
    """Write every registry that changed; with *replace* a differing row is replaced.

    Return the labels of the rows written.
    """
    written: list[str] = []
    for merge in merges:
        if replace:
            for label, station in merge.differing:
                values = dict(station.row)
                merge.header.extend(key for key in values if key not in merge.header)
                index = next(i for i, row in enumerate(merge.rows) if row.get("id") == station.id)
                merge.rows[index] = values
                merge.added.append(label)
            merge.differing.clear()
        if merge.changed:
            _write_registry(merge.path, merge.header, merge.rows)
            written += merge.added
    return written


def read_registry(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Return the header and the rows of a station registry; an absent file has none."""
    if not path.is_file():
        return [], []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = [{k: v for k, v in row.items() if k is not None} for row in reader]
        return list(reader.fieldnames or []), rows


def _write_registry(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=header, restval="", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.{os.getpid()}.partial")
    partial.write_text(buffer.getvalue(), encoding="utf-8")
    os.replace(partial, path)


def sha256_of(path: Path) -> str:
    """Return the sha256 of a file, read in chunks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


BlobOf = Callable[[PayloadFile], Path]
"""Return the local file that holds the bytes of one index file."""


__all__ = [
    "BlobOf",
    "PayloadConflictError",
    "Placement",
    "StationMerge",
    "Status",
    "destination",
    "plan_files",
    "plan_stations",
    "read_registry",
    "refuse_conflicts",
    "sha256_of",
    "write_file",
    "write_stations",
]
