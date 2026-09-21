"""Write one catalogued example into a scaffolded workspace.

Every file goes through the blob cache first, so a second install of the same
example downloads nothing, and two examples sharing the regional DEM share the
90 MiB blob instead of fetching it twice.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.core.logging import get_logger
from hydromodpy.examples.blobs import ensure_blob, is_cached, sha256_of
from hydromodpy.examples.manifest import ExampleEntry, ExampleFile

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
        destination = _destination(root, item)
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

    logger.info(
        "example %s installed into %s (%d written, %d already there, %d downloaded)",
        entry.id,
        root,
        len(report.written),
        len(report.unchanged),
        len(report.downloaded),
    )
    return report


def _destination(workspace: Path, item: ExampleFile) -> Path:
    """Resolve ``item.dest`` under the workspace, refusing to escape it."""
    candidate = (workspace / item.dest).resolve()
    if workspace not in candidate.parents:
        raise DataRequestError(
            f"The manifest destination {item.dest!r} resolves outside the workspace "
            f"{workspace}. A catalog entry may only write under the workspace root."
        )
    return candidate
