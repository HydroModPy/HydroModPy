"""Write one catalogued example into a scaffolded workspace.

Every file goes through the blob cache first, so a second install of the same
example downloads nothing, and two examples sharing the regional DEM share the
90 MiB blob instead of fetching it twice.
"""

from __future__ import annotations

import csv
import io
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.core.logging import get_logger
from hydromodpy.examples.blobs import ensure_blob, is_cached, sha256_of
from hydromodpy.examples.manifest import ExampleEntry, ExampleStation

logger = get_logger(__name__)


@dataclass(slots=True)
class InstallReport:
    """What one ``hmp example add`` actually did."""

    example_id: str
    workspace: Path
    project_dir: Path
    source: str
    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    downloaded: list[str] = field(default_factory=list)
    downloaded_bytes: int = 0
    entry_config: str = ""
    stations_written: list[str] = field(default_factory=list)

    @property
    def everything_was_cached(self) -> bool:
        """True when the blob cache answered every file of the payload."""
        return not self.downloaded


def install_example(
    entry: ExampleEntry,
    *,
    workspace: Path,
    source: str,
    force: bool = False,
) -> InstallReport:
    """Fetch what is missing, verify it, and write the example into ``workspace``.

    An existing destination whose content already matches the manifest is left
    alone. One whose content differs is a file somebody edited: it is kept and
    reported, and only ``force`` overwrites it.
    """
    root = Path(workspace).expanduser().resolve()
    if not (root / "data").is_dir():
        raise DataRequestError(
            f"{root} is not a HydroModPy workspace: no data/ directory. "
            f"Run 'hmp workspace init' on it first."
        )

    report = InstallReport(
        example_id=entry.id,
        workspace=root,
        project_dir=root / "projects" / entry.directory,
        source=source,
        entry_config=entry.entry_config,
    )

    for item in entry.payload:
        destination = _destination(root, item.dest)
        if destination.is_file() and sha256_of(destination) == item.sha256:
            report.unchanged.append(item.dest)
            continue
        if destination.is_file() and not force:
            report.kept.append(item.dest)
            continue

        was_cached = is_cached(item)
        blob = ensure_blob(item, source=source)
        if not was_cached:
            report.downloaded.append(item.dest)
            report.downloaded_bytes += item.size

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(blob, destination)
        report.written.append(item.dest)

    _merge_stations(root, entry.stations, report, force=force)

    logger.info(
        "example %s installed into %s (%d written, %d already there, %d downloaded)",
        entry.id,
        root,
        len(report.written),
        len(report.unchanged),
        len(report.downloaded),
    )
    return report


def _merge_stations(
    workspace: Path,
    stations: tuple[ExampleStation, ...],
    report: InstallReport,
    *,
    force: bool,
) -> None:
    """Add each station row to its registry, keeping every row already there.

    A row with the same id and other values is somebody's edit: it is kept and
    reported, and only ``force`` replaces it.
    """
    by_registry: dict[str, list[ExampleStation]] = {}
    for station in stations:
        by_registry.setdefault(station.dest, []).append(station)

    for dest, wanted in by_registry.items():
        path = _destination(workspace, dest)
        header, rows = _read_registry(path)
        changed = False
        for station in wanted:
            values = dict(station.row)
            label = f"{dest} (station {station.id})"
            index = next((i for i, row in enumerate(rows) if row.get("id") == station.id), None)
            if index is not None and all(rows[index].get(k) == v for k, v in values.items()):
                continue
            if index is not None and not force:
                report.kept.append(label)
                continue
            header.extend(key for key in values if key not in header)
            if index is None:
                rows.append(values)
            else:
                rows[index] = values
            report.stations_written.append(label)
            changed = True
        if changed:
            _write_registry(path, header, rows)


def _read_registry(path: Path) -> tuple[list[str], list[dict[str, str]]]:
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
    path.write_text(buffer.getvalue(), encoding="utf-8")


def _destination(workspace: Path, dest: str) -> Path:
    """Resolve ``dest`` under the workspace, refusing to escape it."""
    candidate = (workspace / dest).resolve()
    if workspace not in candidate.parents:
        raise DataRequestError(
            f"The manifest destination {dest!r} resolves outside the workspace "
            f"{workspace}. A catalog entry may only write under the workspace root."
        )
    return candidate
