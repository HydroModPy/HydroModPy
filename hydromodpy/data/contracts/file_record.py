"""A file a fetch hands back, with the digest of its bytes.

A ``FetchResult`` of the ``files`` kind used to carry bare paths. The path said
where the bytes were, and nothing else: two sources writing the same tile left
two objects a consumer could not tell apart, and the digest that sealed a run
had to be computed somewhere else, by someone who no longer knew which service
had answered. A :class:`FileRecord` carries what the seal and the licence pages
need, in one place, read once.

:func:`FileRecord.of` is the constructor a source calls. It hashes the file
through :func:`hydromodpy.core.io.file_digest.sha256_of`, in blocks, without
writing anything: the file is sealed as it was answered.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import DataProductError

if TYPE_CHECKING:
    from hydromodpy.schema.job.inputset import InputState

ALL_INPUT_STATES: tuple[str, ...] = ("raw", "conditioned")
"""The two states a file can be sealed in; the vocabulary lives in ``schema``."""


class FileRecord:
    """One file a source produced, named by what is known about it.

    ``state`` says how far the bytes were carried from their origin, and is
    ``None`` for a source that cannot know. ``nodata`` is the value that means
    "no measurement here" in the file, a number the reader of a raster needs and
    cannot guess. ``origin`` names where the bytes came from, the service that
    answered, kept as one word so a table can group on it.
    """

    __slots__ = ("path", "sha256", "state", "nodata", "origin")

    def __init__(
        self,
        path: str | Path,
        sha256: str,
        *,
        state: InputState | None = None,
        nodata: float | int | None = None,
        origin: str,
    ) -> None:
        if not isinstance(path, (str, Path)):
            raise DataProductError(f"A file record carries path={path!r}, which is not a path.")
        try:
            digest = str(sha256)
        except Exception as exc:  # pragma: no cover - str() does not fail on str
            raise DataProductError(f"A file record carries sha256={sha256!r}.") from exc
        digest = digest.strip().lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise DataProductError(
                f"A file record carries sha256={sha256!r}, which is not a sha256 hex digest."
            )
        if state is not None and state not in ALL_INPUT_STATES:
            raise DataProductError(
                f"A file record carries state={state!r}. It is one of {list(ALL_INPUT_STATES)}, "
                "or None when the source cannot know."
            )
        if nodata is not None and isinstance(nodata, bool):
            raise DataProductError(f"A file record carries nodata={nodata!r}, which is a boolean.")
        if not isinstance(origin, str) or not origin.strip():
            raise DataProductError(
                f"A file record carries origin={origin!r}. Name where the bytes came from."
            )
        self.path = Path(path)
        self.sha256 = digest
        self.state = state
        self.nodata = nodata
        self.origin = origin.strip()

    @classmethod
    def of(
        cls,
        path: str | Path,
        *,
        state: InputState | None = None,
        nodata: float | int | None = None,
        origin: str,
    ) -> FileRecord:
        """Hash the file at *path* and return the record of it.

        The file is read and never written: a fetch answers with the bytes it
        received, and the digest is computed over exactly those.
        """
        from hydromodpy.core.io.file_digest import sha256_and_size

        try:
            sha256, _bytes = sha256_and_size(path)
        except OSError as exc:
            raise DataProductError(
                f"A fetch cannot seal {Path(path)!r}: reading it for its digest failed ({exc})."
            ) from exc
        return cls(path, sha256, state=state, nodata=nodata, origin=origin)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FileRecord):
            return NotImplemented
        return (self.path, self.sha256, self.state, self.nodata, self.origin) == (
            other.path,
            other.sha256,
            other.state,
            other.nodata,
            other.origin,
        )

    def __hash__(self) -> int:
        return hash((self.path, self.sha256, self.state, self.nodata, self.origin))

    def __repr__(self) -> str:
        return (
            f"FileRecord(path={str(self.path)!r}, sha256={self.sha256!r}, "
            f"state={self.state!r}, nodata={self.nodata!r}, origin={self.origin!r})"
        )


__all__ = ["ALL_INPUT_STATES", "FileRecord"]
