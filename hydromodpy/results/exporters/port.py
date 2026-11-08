"""The export port: one writer per format, declared by the format itself.

A format is a class. It declares what it is and what it writes, and the one
method :meth:`ExportWriter.write` does the writing. The declarations are the
vocabulary the rest of the package reads: the suffix of a planned file, the
formats a kind of data can go to, the formats that hold one instant per file,
the ones that do not reproject, and the views that describe the whole run.
Nothing else may restate them.

Seven formats ship in the wheel: six file formats in
:mod:`hydromodpy.results.exporters.formats` and the RO-Crate view in
:mod:`hydromodpy.results.export.rocrate`. Every one of them is registered in
:mod:`hydromodpy.results.exporters.registry`; a format outside the wheel joins
the same registry through the ``hydromodpy.export.format`` entry-point group.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from hydromodpy.results.exporters.export_spec import PlannedFile
    from hydromodpy.results.exporters.job import ExportJob

RUN_VIEW = "run"
"""The one ``writes`` value of a format that describes the whole run.

It is not one of the :class:`ExportKind` values: a view writes no variable, it
renders the seal, so it takes ``variables = "all"`` and no selector."""

EXPORT_WRITER_MEMBERS: tuple[str, ...] = (
    "name",
    "suffix",
    "writes",
    "natural",
    "instants",
    "reprojects",
    "help",
    "write",
)
"""The members a format declares, checked by the registry at registration."""


@runtime_checkable
class ExportWriter(Protocol):
    """One export format.

    A format declares itself with seven class attributes and one method:

    ``name``
        The word a document and the CLI write, ``"netcdf"`` or ``"rocrate"``.
        It is the id the registry resolves.
    ``suffix``
        The extension of the files it writes, ``".nc"``. A view names its
        view file by its own suffix, read from the storage contract.
    ``writes``
        The kinds of data it can hold, each an :class:`ExportKind` value, or
        ``(RUN_VIEW,)`` for a view that describes the whole run.
    ``natural``
        The kinds for which it is the default format. The first format that
        declares a kind natural is the one an unformatted request takes.
    ``instants``
        ``"one"`` when one file holds one instant of a field, so several dates
        write one file each, ``"many"`` otherwise.
    ``reprojects``
        False when the format keeps the model CRS and refuses a ``crs``.
    ``help``
        One sentence, the description the config schema prints for the value.

    ``write(job, item, dest)`` writes one planned file and returns the paths
    written. A data format receives the :class:`~hydromodpy.results.exporters.job.ExportJob`
    it reads the run through, and a view receives ``None`` for both ``job``
    and ``item``: it renders the seal, and *dest* is what it gets, the run
    directory (the view names its file inside it) or one exact path.
    """

    name: str
    suffix: str
    writes: tuple[str, ...]
    natural: tuple[str, ...]
    instants: str
    reprojects: bool
    help: str

    def write(
        self,
        job: ExportJob | None,
        item: PlannedFile | None,
        dest: Path,
    ) -> list[Path]:
        """Write one planned file at *dest* and return the paths written."""
        ...


__all__ = ["EXPORT_WRITER_MEMBERS", "ExportWriter", "RUN_VIEW"]
