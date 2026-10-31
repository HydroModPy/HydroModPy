"""The checks a spatial capability job makes on its input files, and the hashes of its outputs.

``domain-build`` and ``terrain-delineate`` read the same kind of request: files
named by an ``href``, optionally pinned by their ``sha256``. Both refuse a file
that is not there, a file whose bytes are not the pinned ones, and a raster no
reader opens, with the same words and the same codes. Both seal the outputs
their declaration lists.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import rasterio
from rasterio.io import DatasetReader

from hydromodpy.core.exceptions import DataContractViolation, JobInputNotFoundError
from hydromodpy.schema.capability import CapabilityDecl
from hydromodpy.schema.job.digest import sha256_file
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.outcome import OutputRecord

T = TypeVar("T")


def resolve_input_file(job: JobDirectory, href: str, *, member: str) -> Path:
    """Resolve one declared input file and prove it is there before anything runs."""
    path = job.resolve_input(href, loc=("inputs", member, "href"))
    if not path.is_file():
        raise JobInputNotFoundError(f"input {member} names {href!r}, and {path} is not a file")
    return path


def refuse_a_file_that_is_not_the_one_asked_for(
    declared: str | None, *, digest: str, href: str, member: str
) -> None:
    """Refuse a file whose bytes are not the ones the request pinned."""
    if declared is None:
        return
    if declared.lower() != digest:
        raise DataContractViolation(
            f"input {member} {href!r} hashes to {digest} and the request pinned "
            f"{declared.lower()}; the bytes are not the ones the job asked for"
        )


def read_raster_input(
    href: str, *, path: Path, member: str, read: Callable[[DatasetReader], T]
) -> T:
    """Open an input raster, return what *read* takes from it, and refuse a file that is not one.

    A file no raster reader opens, or one without a band, is bad input. Without
    this refusal it surfaced as an untyped ``HMPY.E000`` and exit 1, the code
    that means "this is a bug in HydroModPy, report it".
    """
    try:
        with rasterio.open(str(path)) as source:
            band_count = source.count
            value = read(source)
    except rasterio.errors.RasterioError as exc:
        raise DataContractViolation(
            f"input {member} {href!r} cannot be opened as a raster: {exc}"
        ) from exc
    except OSError as exc:
        raise DataContractViolation(f"input {member} {href!r} cannot be read: {exc}") from exc
    if band_count < 1:
        raise DataContractViolation(
            f"input {member} {href!r} carries {band_count} band(s); "
            "an elevation model carries at least one"
        )
    return value


def output_records(job: JobDirectory, decl: CapabilityDecl) -> tuple[OutputRecord, ...]:
    """Hash every declared artefact that exists once the job has written it.

    ``outcome.json`` is declared and absent here: it cannot carry its own
    digest. The seal hashes it from disk, which is the only place its bytes
    can be read from.
    """
    records = []
    for output in decl.outputs:
        if output.path == "outcome.json":
            continue
        path = job.resolve_output(output.path)
        digest, size = sha256_file(path)
        records.append(
            OutputRecord(
                id=output.id,
                path=output.path,
                media_type=output.media_type,
                bytes=size,
                sha256=digest,
                extra=output.extra,
            )
        )
    return tuple(records)


__all__ = [
    "output_records",
    "read_raster_input",
    "refuse_a_file_that_is_not_the_one_asked_for",
    "resolve_input_file",
]
