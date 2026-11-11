"""What a published copy records, and what the source remembers of it.

Why
---
``hmp publish`` copies a run or a summary out of the tree. The copy must say
where it came from and what it contains, so a reader can verify it and a
source can be matched to it; the source must remember where it went, so a
delete warns. And nothing that leaves the tree may name the machine it was
computed on: the one function :func:`redact` removes the host, the user and
every absolute path from any document on its way out.

Format
------
:class:`PublicationConfig` is the ``[publication]`` section of a project file:
the licence, the creators and the attribution every copy carries.
``PUBLICATION.json`` in the copy is :class:`Publication`: what it copies
(a run, the summary or a whole project), the source by project, directory
and id, the digest of the manifest and of each copied file, the label of the
day, the version, the instant, the format and what was taken along. The copy
of a project lists its members, each by name and by the digest of its own
``PUBLICATION.json``. ``published.jsonl`` in the source is one
:class:`PublishedLine` per copy, appended.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Any, Final

from pydantic import ConfigDict, Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.stored import Vocabulary, read_stored
from hydromodpy.core.io.document_version import VersionWindow
from hydromodpy.core.state.layout import SUMMARY_DIRNAME
from hydromodpy.results.rel_dir import checked_rel_dir
from hydromodpy.results.storage.contract import PUBLICATION_FILENAME, RUN_PUBLISHED_FILENAME
from hydromodpy.results.storage.json_io import check_sealed, read_sealed_json, write_json_atomic
from hydromodpy.results.validity_rules import Label


class PublicationConfig(HydroModelBase):
    """The licence and the authorship written into every publication."""

    license: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Licence of the published results, as an SPDX identifier or a licence "
            "name (CC-BY-4.0, etalab-2.0). Required by hmp publish --public."
        ),
        examples=["etalab-2.0"],
    )
    creators: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="People or bodies credited as creators of the published results.",
        examples=[["A. Author"]],
    )
    attribution: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Attribution text the publication carries, for the data it was built on.",
        examples=["Contains data from Hub'Eau."],
    )


PUBLICATION_SCHEMA: Final[str] = "hydromodpy.publication.v1"
"""Schema id of ``PUBLICATION.json``."""

PUBLICATION_VERSIONS: Final[VersionWindow] = VersionWindow(
    oldest="hydromodpy.publication.v1", current=PUBLICATION_SCHEMA
)
"""Versions of ``PUBLICATION.json`` this code reads."""

PUBLISHED_SCHEMA: Final[str] = "hydromodpy.published.v2"
"""Schema id of one line of ``published.jsonl``."""

PUBLISHED_VERSIONS: Final[VersionWindow] = VersionWindow(
    oldest="hydromodpy.published.v2", current=PUBLISHED_SCHEMA
)
"""Versions of one line of ``published.jsonl`` this code reads."""

PUBLISHED_REMEDY: Final[str] = (
    'HydroModPy 2.1 reads lines that say kind = "copy" or "delivery". Move this file '
    "aside to keep its record; the next copy or delivery starts a new one."
)
"""What to do with a line of ``published.jsonl`` written by HydroModPy 2.0."""

REDACTED_PATH: Final[str] = "<absolute path>"
"""What an absolute path outside the project becomes."""

REDACTED_KEYS: Final[frozenset[str]] = frozenset(
    {"host", "hostname", "user", "username", "user_name"}
)
"""Keys removed from any published document, at any depth."""

PROJECT_REL_DIR: Final[str] = "."
"""``rel_dir`` of the source of a project copy: the project root itself."""

PublicationFormat = Annotated[str, Vocabulary("dir", "tar")]
PublicationExtra = Annotated[str, Vocabulary("results", "inputs")]
PublicationKind = Annotated[str, Vocabulary("run", "summary", "project")]
PublishedKind = Annotated[str, Vocabulary("copy", "delivery")]
DeliveryState = Annotated[str, Vocabulary("pending", "delivered", "failed")]


class PublicationSource(HydroModelBase):
    """The run or summary a copy was made from."""

    project: str = Field(description="Project of the source")
    rel_dir: str = Field(
        description=(
            "Directory of the source, relative to the project root; summary for a summary, "
            ". for a whole project"
        )
    )
    sim_id: str | None = Field(
        default=None, description="Id of the run; none for a summary or a project"
    )

    @field_validator("rel_dir")
    @classmethod
    def _rel_dir(cls, value: str) -> str:
        if value in (SUMMARY_DIRNAME, PROJECT_REL_DIR):
            return value
        return checked_rel_dir(value)


class PublicationMember(HydroModelBase):
    """One copy a project copy holds: a run or the summary, a folder or a tar."""

    name: str = Field(description="Folder or .tar of the member, directly under the copy")
    rel_dir: str = Field(
        description="Directory of the member's source, relative to the project root"
    )
    manifest_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        description="Digest of the sealed manifest of the run; none for the summary",
    )
    publication_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$", description="Digest of the member's own PUBLICATION.json"
    )

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not value or value in (".", "..") or "/" in value or "\\" in value:
            raise ValueError(f"{value!r} is not an entry name directly under the copy")
        return value

    @field_validator("rel_dir")
    @classmethod
    def _rel_dir(cls, value: str) -> str:
        if value == SUMMARY_DIRNAME:
            return value
        return checked_rel_dir(value)


class Publication(HydroModelBase):
    """``PUBLICATION.json``: what a published copy is."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=PUBLICATION_SCHEMA, alias="schema", description="Schema id")
    kind: PublicationKind = Field(
        default="run", description="What the copy is: one run, the summary or a whole project"
    )
    source: PublicationSource
    manifest_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$", description="Digest of the sealed manifest"
    )
    files: dict[str, str] = Field(
        default_factory=dict, description="Relative path of each copied file to its sha256"
    )
    label: Label | None = Field(default=None, description="Label of the source on the day")
    label_date: date | None = Field(default=None, description="Day the label was computed")
    hydromodpy_version: str = Field(description="Version that published")
    published_at: datetime = Field(description="Instant of the copy, UTC")
    format: PublicationFormat = Field(description="dir or tar")
    with_: list[PublicationExtra] = Field(
        default_factory=list, alias="with", description="What was taken along"
    )
    members: list[PublicationMember] = Field(
        default_factory=list,
        description="The copies a project copy holds, one per run and one for the summary",
    )

    @model_validator(mode="after")
    def _schema(self) -> Publication:
        if not PUBLICATION_VERSIONS.holds(self.schema_):
            raise ValueError(
                f"schema is {self.schema_!r}, this module reads {PUBLICATION_SCHEMA!r}"
            )
        return self

    @model_validator(mode="after")
    def _kind(self) -> Publication:
        rel_dir = self.source.rel_dir
        expected = {"summary": SUMMARY_DIRNAME, "project": PROJECT_REL_DIR}.get(self.kind)
        if expected is not None and rel_dir != expected:
            raise ValueError(f"a {self.kind} copy has source.rel_dir {expected!r}, not {rel_dir!r}")
        if self.kind == "run" and rel_dir in (SUMMARY_DIRNAME, PROJECT_REL_DIR):
            raise ValueError(
                f"a run copy names its run directory in source.rel_dir, not {rel_dir!r}"
            )
        if self.kind != "project" and self.members:
            raise ValueError(f"only a project copy lists members, not a {self.kind} copy")
        names = [member.name for member in self.members]
        if len(set(names)) != len(names):
            raise ValueError("a project copy lists each member once")
        return self


DELIVERY_ATTEMPTS: Final = 3
"""Tries of one file on one destination; a final delivery line counts 1 to this."""

_UNREAD_FIELDS: Final[tuple[str, ...]] = ("sha256", "bytes")
"""What a failed delivery line omits when its file could not be read."""

_COPY_FIELDS: Final[tuple[str, ...]] = ("to", "format", "publication_sha256")
"""The fields a ``copy`` line carries: where a copy went."""

_DELIVERY_FIELDS: Final[tuple[str, ...]] = (
    "file",
    "destination",
    "state",
    "sha256",
    "bytes",
    "attempts",
)
"""The fields a ``delivery`` line carries: where one file of the run goes."""


class PublishedLine(HydroModelBase):
    """One line of ``published.jsonl``: where a copy went, or where a file goes.

    A ``copy`` line records a copy of the run or the summary, once it is
    written. A ``delivery`` line records one file of the run sent to one
    destination, and what became of it.
    """

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=PUBLISHED_SCHEMA, alias="schema", description="Schema id")
    kind: PublishedKind = Field(description='What the line records: "copy" or "delivery"')
    published_at: datetime = Field(description="Instant of the line, UTC")
    to: str | None = Field(default=None, description="Destination of the copy, as given")
    format: PublicationFormat | None = Field(default=None, description="Format of the copy")
    publication_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        description="Digest of the PUBLICATION.json written there",
    )
    file: str | None = Field(
        default=None, description="File delivered, its path relative to the run directory"
    )
    destination: str | None = Field(
        default=None, description="Address the file was delivered to, without identity"
    )
    state: DeliveryState | None = Field(default=None, description="What became of the delivery")
    sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        description="Digest of the file pushed; absent on a failed line whose file was not read",
    )
    bytes: int | None = Field(
        default=None,
        ge=0,
        description="Size of the file pushed, in bytes; absent on a failed line whose file was not read",
    )
    attempts: int | None = Field(
        default=None,
        description=f"Attempts made: 0 while pending, 1 to {DELIVERY_ATTEMPTS} otherwise",
    )
    error: str | None = Field(
        default=None, description="Why the last attempt failed; only on a failed delivery"
    )

    def to_dict(self) -> dict[str, Any]:
        """Return the line as JSON, without the members it does not carry."""
        return self.model_dump(mode="json", exclude_none=True)

    @property
    def pair(self) -> tuple[str, str]:
        """Return what the line is the latest state of: a delivered file, or a copy."""
        if self.kind == "delivery":
            return (self.file or "", self.destination or "")
        return ("", self.to or "")

    @model_validator(mode="after")
    def _check_kind(self) -> PublishedLine:
        if self.kind == "copy":
            self._require(_COPY_FIELDS, "a copy")
            self._refuse(_DELIVERY_FIELDS, "a copy")
            if self.error is not None:
                raise ValueError("only a failed delivery line carries error.")
            return self
        needed = _DELIVERY_FIELDS
        if self.state == "failed":
            needed = tuple(name for name in needed if name not in _UNREAD_FIELDS)
            if (self.sha256 is None) != (self.bytes is None):
                raise ValueError(
                    "a failed delivery line carries both sha256 and bytes, or neither."
                )
        self._require(needed, "a delivery")
        self._refuse(_COPY_FIELDS, "a delivery")
        if self.state == "failed":
            if self.error is None:
                raise ValueError(
                    "a failed delivery line carries error, the reason of the last attempt."
                )
        elif self.error is not None:
            raise ValueError("only a failed delivery line carries error.")
        if self.state == "pending" and self.attempts != 0:
            raise ValueError("a pending delivery line has attempts = 0.")
        if self.state != "pending" and not 1 <= (self.attempts or 0) <= DELIVERY_ATTEMPTS:
            raise ValueError(
                f"a delivered or failed delivery line has attempts = 1 to {DELIVERY_ATTEMPTS}, "
                "the tries made."
            )
        return self

    def _require(self, names: tuple[str, ...], what: str) -> None:
        missing = [name for name in names if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{what} line requires {', '.join(missing)}.")

    def _refuse(self, names: tuple[str, ...], what: str) -> None:
        given = [name for name in names if getattr(self, name) is not None]
        if given:
            raise ValueError(f"{what} line carries no {', '.join(given)}.")


def latest_by_pair(lines: Iterable[PublishedLine]) -> dict[tuple[str, str], PublishedLine]:
    """Return the last line of each pair, in the order the pairs first appear.

    A pair is the file and the destination of a delivery, or the destination
    of a copy. This is the only reader of the state of ``published.jsonl``.
    """
    latest: dict[tuple[str, str], PublishedLine] = {}
    for line in lines:
        latest[line.pair] = line
    return latest


def deliveries_of(run_dir: str | Path) -> tuple[PublishedLine, ...]:
    """Return the latest delivery line of each pair of a run, in the order they appear."""
    deliveries = (line for line in read_published(run_dir) if line.kind == "delivery")
    return tuple(latest_by_pair(deliveries).values())


def publication_path(directory: str | Path) -> Path:
    """Return ``<copy>/PUBLICATION.json``."""
    return Path(directory) / PUBLICATION_FILENAME


def write_publication(directory: str | Path, publication: Publication) -> Path:
    """Write ``PUBLICATION.json`` in a copy and return its path."""
    return write_json_atomic(
        publication_path(directory), publication.model_dump(mode="json", by_alias=True)
    )


def read_publication(directory: str | Path) -> Publication:
    """Read ``PUBLICATION.json`` of a copy."""
    return read_stored(
        Publication, read_sealed_json(publication_path(directory), PUBLICATION_VERSIONS)
    )


def published_path(source_dir: str | Path) -> Path:
    """Return ``<source>/published.jsonl``."""
    return Path(source_dir) / RUN_PUBLISHED_FILENAME


def append_published(source_dir: str | Path, line: PublishedLine) -> Path:
    """Append one line to ``published.jsonl`` of a source and return its path."""
    target = published_path(source_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(line.model_dump(mode="json", by_alias=True), ensure_ascii=False) + "\n"
    fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    return target


def read_published(source_dir: str | Path) -> list[PublishedLine]:
    """Return every line of ``published.jsonl``, empty when nothing was published."""
    target = published_path(source_dir)
    if not target.is_file():
        return []
    complete = target.read_text(encoding="utf-8").split("\n")[:-1]
    return [
        read_stored(
            PublishedLine,
            check_sealed(
                json.loads(text),
                PUBLISHED_VERSIONS,
                path=target,
                line=number,
                remedy=PUBLISHED_REMEDY,
            ),
        )
        for number, text in enumerate(complete, start=1)
        if text.strip()
    ]


_POSIX_ABSOLUTE = re.compile(r"(?<![\w:/.])/(?:[^\s\"'<>|/]+)(?:/[^\s\"'<>|/]*)*")
_WINDOWS_ABSOLUTE = re.compile(r"(?<!\w)[A-Za-z]:[\\/][^\s\"'<>|]*")


def redact(payload: Mapping[str, Any], *, project_root: Path | None) -> dict[str, Any]:
    """Return *payload* without host, user or absolute path, at any depth.

    A key of :data:`REDACTED_KEYS` is dropped. A string that is, or holds,
    an absolute path has it replaced: by its path relative to *project_root*
    when it lies under it, by :data:`REDACTED_PATH` otherwise. Lists and
    nested mappings are walked; anything else is kept as it is.
    """
    root = None if project_root is None else Path(project_root).resolve()
    return {
        key: _redact_value(value, root)
        for key, value in payload.items()
        if key not in REDACTED_KEYS
    }


def _redact_value(value: Any, root: Path | None) -> Any:
    if isinstance(value, Mapping):
        return {k: _redact_value(v, root) for k, v in value.items() if k not in REDACTED_KEYS}
    if isinstance(value, list):
        return [_redact_value(item, root) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item, root) for item in value)
    if isinstance(value, str):
        return _redact_text(value, root)
    return value


def _redact_text(text: str, root: Path | None) -> str:
    def posix(match: re.Match[str]) -> str:
        return _relative_or_redacted(PurePosixPath(match.group(0)), root)

    def windows(match: re.Match[str]) -> str:
        return _relative_or_redacted(PureWindowsPath(match.group(0)), root)

    text = _WINDOWS_ABSOLUTE.sub(windows, text)
    return _POSIX_ABSOLUTE.sub(posix, text)


def _relative_or_redacted(path: PurePosixPath | PureWindowsPath, root: Path | None) -> str:
    if root is not None:
        try:
            return Path(path).resolve().relative_to(root).as_posix()
        except ValueError:
            pass
    return REDACTED_PATH


__all__ = [
    "DELIVERY_ATTEMPTS",
    "PUBLICATION_SCHEMA",
    "PUBLICATION_VERSIONS",
    "PROJECT_REL_DIR",
    "PUBLISHED_REMEDY",
    "PUBLISHED_SCHEMA",
    "PUBLISHED_VERSIONS",
    "REDACTED_KEYS",
    "REDACTED_PATH",
    "DeliveryState",
    "Publication",
    "PublicationConfig",
    "PublicationExtra",
    "PublicationFormat",
    "PublicationKind",
    "PublicationMember",
    "PublicationSource",
    "PublishedKind",
    "PublishedLine",
    "append_published",
    "deliveries_of",
    "latest_by_pair",
    "publication_path",
    "published_path",
    "read_publication",
    "read_published",
    "redact",
    "write_publication",
]
