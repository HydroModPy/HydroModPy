"""Write one cataloged example into a scaffolded workspace.

Every file goes through the blob cache first, so a second install of the same
example downloads nothing, and two examples sharing the regional DEM share the
90 MiB blob instead of fetching it twice.

The example goes into a workspace that already has a ``data/`` folder. An install keeps
a destination whose content differs, and ``hmp example add --force`` overwrites it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.payload.install import plan_files, plan_stations, write_file, write_stations
from hydromodpy.project.examples.blobs import ensure_blob, is_cached
from hydromodpy.project.examples.manifest import ExampleEntry

logger = get_logger(__name__)


@dataclass(slots=True)
class InstallReport:
    """What one ``hmp example add`` actually did."""

    example_id: str
    """Id of the installed example, as ``hmp.example()`` lists it."""
    workspace: Path
    """Workspace root the example was installed into."""
    project_dir: Path
    """Project folder of the example, ``<workspace>/projects/<directory>``."""
    source: str
    """Root the missing files were fetched from: the release tag on GitHub by
    default, or the value of ``HMP_EXAMPLES_SOURCE``.
    """
    written: list[str] = field(default_factory=list)
    """Files copied into the workspace, as paths relative to its root."""
    unchanged: list[str] = field(default_factory=list)
    """Files already there with the expected content, left as they were."""
    kept: list[str] = field(default_factory=list)
    """Files (and station rows) already there with another content, kept.

    Somebody edited them. Install again with ``force=True`` to overwrite them.
    """
    downloaded: list[str] = field(default_factory=list)
    """Files the cache did not hold and that were downloaded."""
    downloaded_bytes: int = 0
    """Size of the downloaded files, in bytes."""
    entry_config: str = ""
    """The TOML file to run first, relative to ``project_dir``."""
    stations_written: list[str] = field(default_factory=list)
    """Station rows added to or replaced in a workspace station registry."""

    @property
    def everything_was_cached(self) -> bool:
        """True when the blob cache answered every file of the payload."""
        return not self.downloaded

    def to_dict(self) -> dict[str, Any]:
        """Return what the install did as JSON: the paths as text and the files by list."""
        return {
            "workspace": str(self.workspace),
            "project_dir": str(self.project_dir),
            "entry_config": self.entry_config,
            "source": self.source,
            "downloaded": list(self.downloaded),
            "downloaded_bytes": self.downloaded_bytes,
            "written": list(self.written),
            "unchanged": list(self.unchanged),
            "kept": list(self.kept),
            "stations_written": list(self.stations_written),
        }


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
    reported, and only ``force`` overwrites it. The placement is the one of
    every package (:mod:`hydromodpy.core.payload.install`).
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

    for placement in plan_files({"workspace": root}, entry.payload):
        item = placement.item
        if placement.status == "unchanged":
            report.unchanged.append(item.dest)
            continue
        if placement.status == "differs" and not force:
            report.kept.append(item.dest)
            continue
        was_cached = is_cached(item)
        blob = ensure_blob(item, source=source)
        if not was_cached:
            report.downloaded.append(item.dest)
            report.downloaded_bytes += item.size
        write_file(placement, blob)
        report.written.append(item.dest)

    merges = plan_stations(root, entry.stations)
    if not force:
        report.kept.extend(label for merge in merges for label, _ in merge.differing)
        for merge in merges:
            merge.differing.clear()
    report.stations_written.extend(write_stations(merges, replace=force))

    logger.info(
        "example %s installed into %s (%d written, %d already there, %d downloaded)",
        entry.id,
        root,
        len(report.written),
        len(report.unchanged),
        len(report.downloaded),
    )
    return report
